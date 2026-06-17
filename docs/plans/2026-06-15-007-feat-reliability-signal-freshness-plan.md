---
title: "feat: Reliability signal freshness (recheck cadence + coverage alarm + selector-drift schedule)"
type: feat
status: shipped
date: 2026-06-15
origin: docs/brainstorms/2026-06-15-reliability-observe-to-enforce-hardening-requirements.md
claims: {}
---

# feat: Reliability signal freshness

## Overview

Follow-up to the merged observe→enforce work (PR #8). That round built the
measurement substrate; B1 (Plan 2026-06-15-001) already built recheck
prioritization, per-probe timeout, batch budget, and **coverage-within-window**
measurement (`scorecard/coverage.py::recheck_coverage`, a freshness property vs a
cumulative count). What is still missing is keeping those panel signals *fresh and
trustworthy over time*:

1. **No proactive alarm** when within-window liveness coverage drops below the
   `target_pct` — `publish-metrics` reports `coverage_meets_target` but is
   advisory-only (exit 0), so a regression is invisible unless someone reads it.
2. **Recheck cadence is weekly** (`com.dex.bp-recheck.plist`, Mon 04:30) — too
   sparse to *hold* ≥50% within `stale_days=30` against publish inflow (flagged in
   the PR #8 feasibility review).
3. **Selector-drift is unscheduled** — `make selector-drift` (static manifest
   check) exists but no schedule runs it, so browser-tier selector regressions
   surface only by chance.

> **Honest scope note**: liveness coverage (R8) does NOT feed the enforce-readiness
> *verdict* (that is would_skip-based and fresh on every publish via PR #8). This
> round hardens the **/health panel signals** (coverage + selector-drift), i.e.
> dashboard trustworthiness — not the enforce decision path.

## Requirements Trace

- R8a. A schedulable alarm that fails (non-zero) when within-window coverage is
  below target, so a scheduled job surfaces the regression.
- R8b. Recheck cadence raised to hold ≥50% steady-state (weekly → daily), with the
  cadence/budget math documented.
- R9. Selector-drift static check runs on a schedule (committed plist), with the
  static-vs-attended distinction documented (live smoke stays operator-run).

## Scope Boundaries

- No change to `recheck_coverage` math, recheck prioritization, or the probe
  timeout/budget — all already built in B1.
- Default `publish-metrics` behavior unchanged (exit 0, advisory); the alarm is opt-in.
- Does not touch the enforce path, the readiness verdict, or the wip/inflight pile.
- Installing the launchd plists is an operator action (the plist files + install
  wiring are committed; activation is manual).
- The attended live selector smoke (`make selector-smoke`, needs attached Chrome)
  stays operator-run — only the static manifest check is scheduled.

## Context & Research

- `cli/publish_metrics.py` — already computes `recheck_coverage` + emits
  `coverage_meets_target` / `coverage_target_pct` in the `_summary` line. Exit 0
  always (advisory). The alarm hooks in here.
- `scorecard/coverage.py::recheck_coverage` — returns `CoverageReport` with
  `coverage_pct`, `target_pct`, `meets_target`, `stale_days`, `per_channel`.
- `cli/recheck_backlinks.py` — `_PER_TARGET_TIMEOUT=10.0`, `_BATCH_BUDGET_S=600.0`,
  `--limit`; batch deadline loop already bounds the run.
- `scripts/com.dex.bp-recheck.plist` (weekly Mon 04:30), `run-recheck-periodic.sh`
  (`--probe --limit $RECHECK_LIMIT`), `install-recheck-launchd.sh`.
- `Makefile` `selector-drift` target → `pytest tests/test_browser_selector_manifest.py`.
- Exit-code convention: 6 = advisory domain-alarm (used by anchor-distribution /
  `--fail-on-dead`); reuse it for the coverage alarm.

## Implementation Units

- [x] **Unit 1: coverage-freshness alarm (`publish-metrics --alarm`)**

**Goal:** An opt-in flag that makes `publish-metrics` exit 6 when overall
within-window coverage is below target, so a scheduled job catches the regression.
Default (no flag) stays exit 0 / advisory.

**Requirements:** R8a

**Files:**
- Modify: `src/backlink_publisher/cli/publish_metrics.py` (add `--alarm` /
  `--coverage-fail-under`; after writing JSONL, exit 6 if below target)
- Test: `tests/test_cli_publish_metrics.py` (extend)

**Approach:**
- Add `--alarm` (bool): when set and `coverage.meets_target` is False, exit 6 after
  emitting the normal JSONL (data still goes to stdout; alarm is the exit code).
- Optional `--coverage-fail-under FLOAT` to override the target threshold for the
  alarm (default = the report's `target_pct`). Keep the computation in
  `recheck_coverage`; the CLI only compares + sets the exit code.
- Never alarm when `total_links == 0` (no data → `coverage_pct is None` → not a
  regression, exit 0) to avoid false alarms on an empty ledger.

**Test scenarios:**
- Happy path: coverage ≥ target + `--alarm` → exit 0.
- Alarm: coverage < target + `--alarm` → exit 6; JSONL still emitted on stdout.
- Default: coverage < target, NO `--alarm` → exit 0 (advisory unchanged).
- Edge: empty ledger (no links) + `--alarm` → exit 0 (no false alarm).
- Edge: `--coverage-fail-under 0.8` with coverage 0.6 → exit 6 even if default target is 0.5.

**Verification:** A scheduled job can detect coverage regression via the exit code;
default behavior and stdout JSONL are unchanged.

- [x] **Unit 2: daily recheck cadence + selector-drift schedule + runbook**

**Goal:** Raise recheck to daily, schedule the static selector-drift check, and
wire the coverage alarm into the periodic run; document the cadence math.

**Requirements:** R8b, R9

**Files:**
- Modify: `scripts/com.dex.bp-recheck.plist` (weekly → daily `StartCalendarInterval`)
- Modify: `scripts/run-recheck-periodic.sh` (run `publish-metrics --alarm` after the
  recheck; surface a non-zero alarm in the log)
- Create: `scripts/com.dex.bp-selector-drift.plist` (daily `make selector-drift`)
- Modify: `scripts/install-recheck-launchd.sh` (also install the selector-drift plist)
- Create/Modify: `docs/runbooks/2026-06-15-reliability-enforce-rollout.md` (append a
  "signal freshness" section: cadence math, alarm, selector-drift static-vs-attended)

**Approach:**
- Daily cadence: `StartCalendarInterval` Hour=4 Minute=30 (drop `Weekday`). Document
  the math: ~1726 links / `stale_days=30` → must re-probe ≥ (links/2)/30 ≈ 29
  links/day to hold ≥50%; the existing 600s/run budget comfortably covers a daily
  run, whereas weekly cannot.
- `run-recheck-periodic.sh`: after the recheck, run `publish-metrics --alarm` and
  log a WARN line if it exits 6 (the operator's existing log/TG-bot surfaces it).
- selector-drift plist: daily `make selector-drift` (static, no browser) — safe to
  run unattended; the attended live smoke stays manual.

**Execution note:** plist/script changes are config artifacts — no unit tests;
validate by `plutil -lint` on the plists and `bash -n` on the scripts.

**Test scenarios:** Test expectation: none — operator-machine config artifacts
(launchd plists + shell). Validate with `plutil -lint` / `bash -n` instead.

**Verification:** `plutil -lint` passes on both plists; `bash -n` passes on the
scripts; the runbook documents cadence + alarm + selector-drift scheduling.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `--alarm` false-positives on empty/small ledger | Skip alarm when total_links==0 / coverage_pct is None |
| Daily recheck raises probe volume → IP-reputation risk | recheck stays passive/ledger-derived; Medium active probe stays OFF (unchanged); budget cap unchanged |
| plist edits don't apply until operator re-installs | Documented in runbook; install is an explicit operator step |
| selector-drift static check ≠ live login verification | Runbook states static-vs-attended distinction explicitly |

## Sources & References

- Origin: `docs/brainstorms/2026-06-15-reliability-observe-to-enforce-hardening-requirements.md` (R8/R9 deferred)
- Builds on: PR #8 (merged) + `docs/plans/2026-06-15-001-...` B1 (coverage/prioritization)
