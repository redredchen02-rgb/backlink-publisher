---
title: "feat: Live-verify the reliability policy enforce path"
type: feat
status: completed
date: 2026-06-03
origin: docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md
deepened: 2026-06-03
---

# feat: Live-verify the reliability policy enforce path

## Overview

The coordinated publish policy layer (health gate + circuit breaker + observability,
plan 2026-05-28-001, Phase 3) is fully shipped and wired into the real publish path, but
gated behind `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1` (default off). The
existing unit tests already set the flag and exercise `publish_with_policy` **directly**,
including non-browser platforms. The one genuinely untested surface is the **CLI
call-site branch selection** — `if policy_enabled(): publish_with_policy(...) else:
adapter_publish(...)` — at `_engine.py:237` (`_publish_one_row`) and `_resume.py:324`.
This plan adds a committed test artifact that exercises that branch through the real
`run_publish_loop` chain with the flag flipped, plus a thin regression layer over the
policy behaviors observed end-to-end.

This is a **verification probe**, not a feature change. Per gate-first (R16), pure
verification is exempt from the falsification gate; a `GO` verdict line is recorded for
audit continuity only.

## Problem Frame

See origin: `docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md`.
The risk being retired is narrow and specific: **does the engine/resume call-site branch
select the policy path when the flag is on, through the real CLI loop body** — not the
policy internals (already unit-covered). A direct call to `publish_with_policy` does NOT
retire this risk; the test must drive `run_publish_loop` so the real `_engine.py:237`
`policy_enabled()` branch and the module-level import seams execute.

> **Coverage-claim precision:** stubbing `publish_with_policy` proves the *engine/resume
> branch selection* only. The second `policy_enabled()` re-check **inside**
> `publish_with_policy` (`policy.py:146`) is bypassed by the stub — but Unit 2 exercises
> the real `publish_with_policy` unstubbed, so that inner gate is covered there.

## Requirements Trace

- R1. **(Primary)** A `run_publish_loop` execution with the flag set routes dispatch
  through `publish_with_policy`, not the `else: adapter_publish` branch; flag-unset stays
  a transparent passthrough. Asserted with a discriminating spy on both call-site seams.
- R2. Health gate (**browser-tier only**: `medium`/`velog`/`devto`/`mastodon`): a
  browser-tier target whose `channel_status` ≠ `bound` yields `skipped_policy`, adapter
  never reached.
- R3. Circuit trip → OPEN: after the configured number of `ExternalServiceError` raises
  the per-platform circuit trips; the next attempt (cooldown not elapsed) yields
  `skipped_circuit_open` without dispatching.
- R4. Circuit **recovery**: after the OPEN cooldown elapses, `is_tripped` transitions the
  circuit to HALF_OPEN and the next dispatch is **allowed through** the chain. (See
  Key Decisions — the original "trials beyond the limit → skipped" framing is NOT
  reachable through `publish_with_policy`; that behavior is re-scoped here.)
- R5. Observability: `publish_attempt` events emitted per outcome (≥ `success` +
  `external_error`) with `platform`, `outcome`, `duration_ms`.
- R6. At least one of R3/R4/R5 runs on a **non-browser-tier** platform (the `fake`
  registry slug qualifies — it is not in `_BROWSER_TIER`). R2 is excluded by design
  (health gate is browser-tier-only, so it is vacuous on `fake`).

## Scope Boundaries

- No real outbound publish; no credentials; no footprint. Stub adapter only.
- No **production-logic** changes to `policy.py` / `circuit.py` / `_engine.py` /
  `_resume.py`. **Test-infrastructure changes are in scope** — adding a raising
  `FakeAdapter` variant / fixtures in `tests/conftest.py` is expected and allowed.
- R2 (health gate) is browser-tier-only by platform design; it is verified on a
  browser-tier slug, never on the non-browser `fake` slug (would pass vacuously). R3–R6
  run on `fake`.
- Does not flip the default flag. No CLI/schema edits (R9 contract preserved).
- Does NOT retire real-platform error-mapping fidelity (real 429/503/ban/session-expiry
  → typed exception vs generic `Exception`→`TRANSIENT`-no-trip). Deferred — needs a bound
  channel + credentials.
- Does NOT verify HALF_OPEN **trial-count limiting** end-to-end — that limiter
  (`circuit._increment_half_open_try`) has no caller on the publish path (see Risks). If
  that is a real gap, it is a **separate fix plan**, not this probe.

## Context & Research

### Relevant Code and Patterns

- **Branch seam (R1):** `src/backlink_publisher/cli/publish_backlinks/_engine.py`
  — `_publish_one_row` (~line 89) late-imports `policy_enabled`, `publish_with_policy`,
  `adapter_publish` from `backlink_publisher.cli.publish_backlinks` at call time (explicit
  comment: "Tests patch these at ...publish_backlinks.X"). Engine spy target =
  `backlink_publisher.cli.publish_backlinks.{publish_with_policy,adapter_publish}`.
- **Resume seam (R1):** `src/backlink_publisher/cli/_resume.py:29` imports
  `policy_enabled, publish_with_policy` at **module top** from `...reliability.policy`,
  and `adapter_publish` from `...adapters` (line 27). Resume spy target =
  `backlink_publisher.cli._resume.{publish_with_policy,adapter_publish}` (different
  location than the engine seam — patching one does not cover the other).
- **Pre-policy short-circuits (R1 hazard):** `_publish_one_row` runs collaborators
  *before* the policy branch at line 237 — notably an **unconditional dry-run
  `adapter_publish(..., dry_run=True)`** branch (`_engine.py:~182`), plus dedup
  (`gate_with_force` must return `publish`), reachability, canary, and token-drift gates.
  The R1 harness must set `args.dry_run = False` and get the row past these gates, or the
  "adapter_publish not called" negative assertion fails for an unrelated reason.
- **Full-chain entry:** `run_publish_loop` (`_engine.py:62`) — ~11-arg signature
  (`rows, args, config, state: PublishRunState, ts, banner_emit, forced_keys,
  throttle_min, throttle_max, initial_token_revs`) driving rows through `_publish_one_row`.
- **Stub adapter:** `tests/conftest.py:544` `FakeAdapter` + `fake_platform_registered`
  fixture registers slug `"fake"` (non-browser-tier, dofollow). Its `publish()` returns
  `status="drafted"` and never raises — R3 needs a **raising variant** that raises
  `ExternalServiceError`.
- **Circuit trip path (corrected — supersedes origin doc AND the first draft):**
  `publish_with_policy` does **not** call `circuit.trip_on_error`. On
  `ExternalServiceError` it calls `policy._record_failure_and_maybe_trip(..., threshold =
  _threshold(BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD, default 5))`, which increments a
  `consecutive_failures` counter in `health.persistence.locked_store` and calls
  `circuit.trip()` once the count ≥ threshold. So:
  - The trip threshold env on the policy path is **`BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD`**
    (auth path: `BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD`, default 3).
    `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS` is read ONLY by
    `circuit.trip_on_error`, which the policy path never calls — do not use it here.
  - `is_tripped()` is the only gate consulted: OPEN + cooldown-not-elapsed → `True`
    (`skipped_circuit_open`); HALF_OPEN → `False` (dispatch allowed, no trial counting);
    OPEN + cooldown-elapsed → transition to HALF_OPEN, `False`.
  - Cooldown default is `BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S` = 300; HALF_OPEN-tries
    env = `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` (default 1) — but unused on the
    publish path.
- **Events sink (R5):** `reliability/events.py` `emit_attempt` → `_log.info(payload)` on
  the **`opencli` logger** (not `publish_logger`). `caplog` must target that logger (or
  root with propagation enabled), else it captures nothing.
- **Test isolation:** the autouse `_isolate_user_dirs` fixture already points
  `BACKLINK_PUBLISHER_CONFIG_DIR` at a **real on-disk temp dir** (`tmp_path_factory`), so
  `circuit.py` flock + `atomic_write_json` state round-trips with no special action. A
  function-scoped `_reassert_config_isolation` fixture FAILS the test if config resolves
  to the real `~/.config`. Therefore: do NOT pop/re-point the config-dir env var. For
  per-test circuit isolation, monkeypatch a fresh tmp `config.config_dir` per test.
- **Pattern references:** `tests/test_reliability_policy.py` (sentinel/event assertions);
  `tests/test_reliability_circuit.py` (HALF_OPEN via patching `circuit.time` to advance
  past cooldown). NOTE: `test_publish_backlinks_characterization.py` drives `main()` and
  patches `adapter_publish` (no `run_publish_loop` ref); `tests/integration/` uses
  subprocess spawns (can't spy in-process seams). Neither is a drop-in template for an
  in-process `run_publish_loop` call — the harness must be built (see Deferred).

### Institutional Learnings

- `_BROWSER_TIER = frozenset({"medium","velog","devto","mastodon"})` (`policy.py:55`) —
  **4 members**. The health gate (R2) is browser-tier-scoped; verifying R2 on `fake` is
  vacuous (origin Key Decision).
- The consecutive-failure counter lives in `locked_store` (`health.persistence`) inside a
  **swallowed try/except** — if the store errors under the sandbox, the count never
  advances and the circuit never trips. For deterministic R3, prefer pre-seeding the
  circuit OPEN via `circuit.trip()` over relying on counter accumulation.
- `PYTHONHASHSEED=0` is the standard harness env; run the suite normally.

## Key Technical Decisions

- **Committed test as the durable artifact** (not a one-off operator CLI run): keeps the
  enforce seam covered against regression. Resolves origin deferred Q1.
- **Two separate R1 assertions** (engine + resume) because the import seams live in
  different modules — one patch location would silently miss a path.
- **Reuse `fake` slug for non-browser coverage (R6)**; add a raising variant for R3.
  Resolves origin Q2/Q3.
- **Deterministic R3 trip:** set `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD=1` AND/OR
  pre-seed via `circuit.trip(platform, config)` (robust against `locked_store` faults),
  then assert `is_tripped` is True before asserting the next attempt is
  `skipped_circuit_open`.
- **R4 re-scoped to recovery, not trial-limiting:** the original "one trial then
  skipped beyond the limit" is unreachable through `publish_with_policy` (HALF_OPEN
  always allows dispatch; `_increment_half_open_try` is never called on the publish
  path). R4 instead verifies the **observable recovery**: trip → cooldown elapses
  (advance via `BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S` small value or patch `circuit.time`
  per the existing circuit test) → next dispatch allowed through. The unwired trial
  limiter is surfaced as a potential bug (Risks), not silently dropped.

## Open Questions

### Resolved During Planning

- Durable artifact form → committed test.
- Stub injection without touching `cli/*.py` → reuse `fake_platform_registered` + raising
  variant; registry resolves dynamically (R9 contract holds).
- Which non-browser platform → `fake`.
- Trip threshold env on the policy path → `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD`
  (NOT `..._CONSECUTIVE_ERRORS`, which the policy path never reads).
- R4 reachability → re-scoped to recovery behavior (above).

### Deferred to Implementation

- **R1/R2/R3 harness construction:** the exact way to feed a single `fake` row through
  `run_publish_loop` (build an `args` stub with `dry_run=False`, a `PublishRunState`, and
  satisfy/patch the dedup + reachability + canary gates so the row reaches line 237).
  No existing in-process template — sketch at implementation; confirm one row reaches the
  policy branch.
- Whether R3 trips deterministically via `locked_store` accumulation in the sandbox or
  must pre-seed `circuit.trip()` — pick the deterministic path at implementation.
- Exact `caplog` logger target for R5 (`opencli` logger name + propagation).
- How to set a `bound`/non-`bound` `channel_status` for the browser-tier R2 case (channel
  status store fixture vs. patching `get_status`) — pick the lightest the sandbox supports.
- Real-platform error-mapping fidelity — out of scope; separate future effort.

## Implementation Units

- [x] **Unit 1: R1 discriminating seam tests (engine + resume) — the primary risk**

**Goal:** Prove the flag switches the CLI dispatch branch, end-to-end through
`run_publish_loop` / the resume path, on both publish paths.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `tests/test_reliability_policy_live.py`

**Approach:**
- Register `fake` via `fake_platform_registered`. Rely on the autouse sandbox config dir
  (already a real flock-capable temp dir) — do NOT re-point the config-dir env var.
- Build a minimal `run_publish_loop` harness: `args` stub with **`dry_run = False`**, a
  fresh `PublishRunState`, a single `fake` row, and dedup/reachability/canary either
  satisfied or patched so the row reaches `_engine.py:237`.
- **Flag on:** set `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`; spy
  `backlink_publisher.cli.publish_backlinks.publish_with_policy` and `.adapter_publish`;
  assert `publish_with_policy` called once, the direct `adapter_publish` branch **not**
  taken (the dry-run `adapter_publish` is excluded by `dry_run=False`).
- **Flag off:** assert the inverse (direct `adapter_publish`, `publish_with_policy` not
  called).
- Repeat the on/off pair for the resume path, spying at `backlink_publisher.cli._resume.*`.

**Patterns to follow:** the late-import-seam patch convention in `_engine.py`; sentinel
assertions in `tests/test_reliability_policy.py`.

**Test scenarios:**
- Happy path: flag=`"1"` → engine routes via `publish_with_policy` (spy hit); direct `adapter_publish` not called.
- Happy path: flag unset → engine routes via direct `adapter_publish`; `publish_with_policy` not called.
- Integration: flag=`"1"` → resume path routes via `publish_with_policy` at its own module seam.
- Edge case: flag=`"0"` / empty → treated as off (passthrough), matching `policy_enabled()`.
- Edge case (guard): with `dry_run=True`, `adapter_publish` fires via the dry-run branch regardless of flag — confirm the harness pins `dry_run=False` so this does not corrupt the negative assertion.

**Verification:** Both seams select the policy path only when the flag is `"1"`; a wrong
patch location or a stray dry-run would fail the assertion (discriminating).

- [x] **Unit 2: End-to-end regression layer for policy behaviors (R2–R6)**
  *(Impl note: the raising stub was kept inline in the test file via a local
  `_RaisingAdapter` + `raising_fake_registered` fixture — no `conftest.py` change
  needed. R3 uses pre-seeded `circuit.trip()` for determinism; R4 uses
  `COOLDOWN_S=0`; R5 events captured via stderr JSON, the `opencli` PipelineLogger
  not being a stdlib logger.)*

**Goal:** With the flag on, observe each policy behavior firing through the real chain, as
regression coverage layered on the Unit 1 seam proof.

**Requirements:** R2, R3, R4, R5, R6

**Dependencies:** Unit 1 test module exists (`tests/test_reliability_policy_live.py`);
independently runnable test functions (does not require Unit 1 assertions to pass).

**Files:**
- Modify: `tests/test_reliability_policy_live.py`
- Modify: `tests/conftest.py` (raising `FakeAdapter` variant, if not inlined in the test)

**Approach:**
- **R2 (browser-tier):** stub a browser-tier slug (e.g. `velog`) with `channel_status` ≠
  `bound`; assert `run_publish_loop` yields `skipped_policy`, adapter never invoked.
- **R3 (non-browser `fake`):** raising stub + `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD=1`
  (or pre-seed `circuit.trip("fake", config)`); assert `is_tripped` True after the
  configured raises, then the next attempt yields `skipped_circuit_open` (no dispatch).
- **R4 (recovery, non-browser `fake`):** from the tripped state, advance past cooldown
  (small `BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S` or patch `circuit.time` per
  `tests/test_reliability_circuit.py`); assert the next dispatch is allowed through
  (`is_tripped` → False via HALF_OPEN transition).
- **R5 (non-browser `fake`):** capture the `opencli` logger via `caplog`; assert a
  `publish_attempt` record for `success` (closed-circuit dispatch) and one for
  `external_error`, each carrying `platform`/`outcome`/`duration_ms`. Assert on the log
  record, not on `state.outputs[...]['status']` (which `_do_verify` may post-mutate).
- **R6:** R3/R4/R5 run on `fake` (non-browser) — satisfies uniform coverage; explicitly do
  not assert R2 on `fake`.

**Patterns to follow:** `tests/test_reliability_policy.py` (status sentinels, event
shape); `tests/test_reliability_circuit.py` (cooldown/time patching).

**Test scenarios:**
- Happy path (R5): closed-circuit `fake` dispatch emits a `success` `publish_attempt` with required fields.
- Error path (R3): raising stub + threshold=1 (or pre-seeded trip) → `is_tripped` True, next attempt returns `skipped_circuit_open`, adapter not re-invoked.
- Recovery (R4): tripped circuit + cooldown advanced → next dispatch allowed through (HALF_OPEN).
- Error path (R2): browser-tier slug, status ≠ `bound` → `skipped_policy`, adapter never reached.
- Integration (R6): R3/R4/R5 execute on the non-browser `fake` platform via the real loop.

**Verification:** Each sentinel/event observed through `run_publish_loop` with the flag
on; circuit state persists across attempts via the sandbox temp config dir.

- [x] **Unit 3: Record a scoped GO verdict for audit continuity**

**Goal:** Log the probe outcome in the gate ledger so the audit trail is consistent,
without overclaiming.

**Requirements:** R16 gate-first governance (audit-trail bookkeeping — does not block
Units 1–2 functionally).

**Dependencies:** Unit 1 + Unit 2 demonstrably passing, including an actual observed trip
(`is_tripped` True) and a `skipped_circuit_open` — so a vacuous green suite cannot mint a GO.

**Files:**
- Modify: `docs/ideation/gate-verdicts.md`

**Approach:**
- Append a `GO` entry scoped to exactly what was retired: "CLI enforce-branch selection
  (engine + resume) and stub-level health-gate / circuit-trip / recovery / observability
  behaviors verified through `run_publish_loop`; real-platform error mapping and HALF_OPEN
  trial-limiting explicitly NOT covered." Reference this plan + the new test file. No
  `gate-probe` run required (R16-exempt pure verification).

**Test expectation:** none — documentation-only entry.

**Verification:** A dated, scoped `GO` line referencing the plan + test exists in
`docs/ideation/gate-verdicts.md`.

## System-Wide Impact

- **Interaction graph:** Test-only. Exercises `run_publish_loop` → `_publish_one_row` →
  `publish_with_policy`/`adapter_publish`, and the `_resume` dispatch. No production code
  changes.
- **State lifecycle risks:** Circuit flock state must be isolated per test (fresh tmp
  `config.config_dir`) so OPEN/HALF_OPEN persistence is real but does not leak across
  tests; restore the registry via the existing fixture teardown.
- **Unchanged invariants:** `policy.py`/`circuit.py`/`_engine.py`/`_resume.py` behavior,
  the default-off flag, the R9 CLI/schema contract, and the existing reliability unit
  tests all remain untouched.
- **Integration coverage:** the cross-layer (CLI loop → policy) coverage that the existing
  direct-call unit tests do not prove — the whole point of this plan.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Test calls `publish_with_policy` directly → re-creates a unit test (vacuous R1) | Unit 1 drives `run_publish_loop` and spies the module seams; a direct call would not hit the spied import path. |
| Dry-run `adapter_publish` (before line 237) pollutes R1's negative assertion | Pin `args.dry_run = False`; add an explicit guard scenario. |
| Wrong trip-threshold env (`CONSECUTIVE_ERRORS`) → circuit never trips on policy path | Use `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD`; assert `is_tripped` True before asserting `skipped_circuit_open`; prefer pre-seeding `circuit.trip()`. |
| `locked_store` faults swallowed → counter never advances → R3 flaky | Pre-seed the circuit OPEN via `circuit.trip()` rather than relying on counter accumulation. |
| R4 as originally framed (trial-limit) is unreachable on the publish path | Re-scoped R4 to recovery behavior; cooldown advanced via env/time-patch. |
| **HALF_OPEN trial limiter (`_increment_half_open_try`) has no caller on the publish path** | Surfaced as a potential production gap → **separate fix plan** (out of this probe's scope); not silently dropped. |
| `caplog` targets the wrong logger → R5 sees no events | Target the `opencli` logger (events.py `_log`) with propagation, not `publish_logger`. |
| Re-pointing config-dir env trips `_reassert_config_isolation` | Use the autouse sandbox dir; monkeypatch a fresh `config.config_dir` per test for isolation. |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md](docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md)
- Related code: `publishing/reliability/policy.py` (Phase 3 U9–U11, 230 lines),
  `publishing/reliability/circuit.py` (`is_tripped`, `trip`, `_increment_half_open_try`),
  `publishing/reliability/events.py`, `cli/publish_backlinks/_engine.py`,
  `cli/_resume.py`, `tests/conftest.py` (`FakeAdapter`), `tests/test_reliability_policy.py`,
  `tests/test_reliability_circuit.py`
- Related plan: `docs/plans/2026-05-28-001-feat-publish-reliability-policy-plan.md` (completed)

---

<!-- /autoplan restore point: /Users/dex/.gstack/projects/redredchen01-backlink-publisher/feat-live-verify-reliability-policy-autoplan-restore-20260603-164619.md -->

## /autoplan Review — 2026-06-03

**Branch:** feat/live-verify-reliability-policy | **Commit:** f5be626 | **Phases run:** CEO + Eng (Design skipped — no UI scope)

---

### Phase 1: CEO Review

#### 0A. Premise Challenge

**P1 (PARTIALLY OUTDATED):** The plan presents Unit 1 as uncreated, but `tests/test_reliability_policy_live.py` exists on disk as an **untracked (uncommitted) file** with 185 lines covering both `TestR1EngineSeam` (4 tests) and `TestR1ResumeSeam` (2 tests). Unit 1 is functionally complete pending commit. The actual remaining work is: (a) add a `assert state.outputs` guard in every R1 test to prevent vacuous negative assertions, (b) Unit 2 (R2–R6 behaviors), (c) Unit 3 (gate-verdicts entry).

**P2 (VALID):** Pure verification probe. No production-logic changes. R9 contract (no cli/*.py edits) confirmed not at risk.

**P3 (VALID):** `fake` is non-browser-tier — confirmed against `policy.py:55` `_BROWSER_TIER = frozenset({"medium","velog","devto","mastodon"})`.

**P4 (VALID):** `_increment_half_open_try` has no caller on the publish path — confirmed. `is_tripped()` returns `False` for HALF_OPEN (dispatch allowed, no trial counting). R4 scoped to recovery is correct.

#### 0B. Existing Code Leverage

| Sub-problem | Existing code | Plan reuses? |
|---|---|---|
| Engine seam spy | `tests/test_reliability_policy.py` (sentinel pattern) | Yes (follows pattern) |
| Resume seam spy | `tests/test_reliability_circuit.py` | Yes (same pattern) |
| Circuit trip/recovery | `circuit.time` mock in `test_reliability_circuit.py:95` | Yes (reuse pattern) |
| FakeAdapter raising | `tests/conftest.py:544` (`FakeAdapter`) | Partial — raising variant not yet added |
| Events capture | `events.py` uses `opencli_logger as _log` | Plan correctly identifies logger target |

**Unit 1 is already written (untracked).** Plan incorrectly presents it as uncreated.

#### 0C. Dream State Delta

```
CURRENT STATE                  THIS PLAN                  12-MONTH IDEAL
Policy ships behind flag  →  CLI branch selection    →  Policy default-on with real
Untested in CI via           tested via run_publish       adapter error mapping and
run_publish_loop             _loop. R2–R6 behaviors       HALF_OPEN trial limiting
                             regression-covered.           wired end-to-end.
                             Gate verdict recorded.
```

This plan moves toward the ideal but explicitly excludes real-platform error mapping and HALF_OPEN trial limiting — both needed before default-on.

#### 0C-bis. Implementation Alternatives

```
APPROACH A: Committed tests (current plan)
  Summary: committed pytest file exercising CLI loop, policy behaviors, gate verdict
  Effort:  S (human: ~4h / CC: ~20min)
  Risk:    Low
  Pros:    Durable regression artifact; exercises real seams; matches project's testing philosophy
  Cons:    Stub-only (no real adapter coverage)
  Reuses:  FakeAdapter, existing circuit/policy test patterns

APPROACH B: Minimal seam test only (skip R2-R6)
  Summary: only the R1 branch-selection tests (engine + resume)
  Effort:  XS (human: ~1h / CC: ~5min)
  Risk:    Low
  Pros:    Smallest possible artifact
  Cons:    Misses R2–R6 behavioral regression; already substantially written anyway
  Reuses:  Same as A

APPROACH C: Expand to HALF_OPEN fix + real adapter error mapping
  Summary: fix the unwired trial limiter AND add characterization tests for real adapters
  Effort:  L (human: ~2d / CC: ~2h)
  Risk:    Medium (requires credentials/bound channels for real adapters)
  Pros:    Closes the larger reliability gap Codex identified
  Cons:    Out of scope for a pure verification probe; credential dependency
  Reuses:  All of A plus circuit.py changes
```

**RECOMMENDATION: Approach A** (current plan) — already mostly written, right level of completeness for a verification probe.
**AUTO-DECIDED: HOLD SCOPE** (Principle P3: pragmatic; this is a verification probe on a completed feature, not a feature build).

#### 0D. HOLD SCOPE Analysis

- Plan touches 3 files (1 new test + conftest modification + gate-verdicts). Well under 8-file complexity smell.
- Minimum change that achieves the goal: exactly what the plan describes.
- No work to defer from the plan's stated scope.

#### 0E. Temporal Interrogation

```
HOUR 1 (foundations):   Stage + verify the existing Unit 1 file; confirm tests pass.
                         Add assert state.outputs guard before committing.
HOUR 2 (core logic):    Add RaisingFakeAdapter to conftest.py.
                         Wire R3 (circuit trip), R4 (recovery via time mock), R5 (caplog opencli).
HOUR 4 (integration):   R2 (browser-tier health gate stub — lightest fixture approach).
                         Confirm caplog logger name is "opencli" (not root).
HOUR 6+ (polish):        Unit 3 gate-verdicts entry. Commit everything.
```

#### CEO Dual Voices

**CLAUDE SUBAGENT (CEO — strategic independence):**
- B1: Resume seam tests already written; plan says they're not → HIGH
- B2: Vacuous negative assertion risk if row never reaches line 237 → HIGH (add `assert state.outputs`)
- R3: HALF_OPEN dead-code gap has no tracking artifact → MEDIUM
- S1: Plan presents Unit 1 as unstarted → MEDIUM

**CODEX SAYS (CEO — strategy challenge):**
> The probe is partially justified, but solves the smallest possible risk while walking past the bigger business risk: the reliability policy is still default-off, and the plan does not define what evidence would make it safe or worthwhile to enable.
> Strategic gaps: (1) branch-selection ≠ reliability; (2) HALF_OPEN limiter unwired undermines circuit premise; (3) GO verdict risks false management confidence; (4) stub-only misses adapter error mapping; (5) double env check is awkward architecture; (6) Unit 1 already partially drafted.
> Recommends: split into seam artifact + HALF_OPEN fix plan + scoped GO (not full GO).

```
CEO DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                           Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ─────── ─────────
  1. Premises valid?                   Mostly  Mostly  CONFIRMED
  2. Right problem to solve?           Yes     Partial DISAGREE → TASTE DECISION
  3. Scope calibration correct?        Yes     No      DISAGREE → TASTE DECISION
  4. Alternatives sufficiently explored? Yes   No      DISAGREE
  5. Competitive/market risks          N/A     N/A     N/A
  6. 6-month trajectory sound?        Yes*    No      DISAGREE → TASTE DECISION
═══════════════════════════════════════════════════════════════
* with HALF_OPEN tracking artifact and scoped GO
```

**Cross-phase theme (surfaced by both voices):** The HALF_OPEN trial limiter is dead code on the publish path. Both reviewers flagged it independently. High-confidence signal that the plan needs to explicitly disclaim this in the GO verdict AND create a tracking artifact.

#### CEO Review Sections

**Section 1 — Architecture:** Test-only. No new production components.
```
run_publish_loop() ──▶ _publish_one_row():237 ──▶ policy_enabled()? ──▶ publish_with_policy()
                                                        └──▶ adapter_publish() (else)

_publish_one_resume_item():324 ──▶ policy_enabled()? ──▶ publish_with_policy()
                                          └──▶ adapter_publish() (else)

Tests spy at module-namespace boundaries (late-import for engine, module-top for resume).
```
No architectural concerns. The two different import seams (late-import engine vs module-top resume) are correctly handled by different spy targets.

**Section 2 — Error & Rescue Map:**
| Codepath | What can go wrong | Exception | Rescued? |
|---|---|---|---|
| RaisingFakeAdapter.publish() | raises ExternalServiceError | ExternalServiceError | Y — in publish_with_policy |
| circuit.trip() via locked_store | locked_store faults | swallowed try/except | Y — fail-soft design |
| caplog missing opencli logger | logs to wrong logger | No exception | N (silent miss) — test-design gap |

The `caplog` silent-miss risk is the most important — see Section 6 (Tests).

**Section 3 — Security:** No new attack surface. Test infrastructure only.

**Section 4 — Data Flow:** No new data flows. Existing publish_with_policy path exercised via test stubs.

**Section 5 — Code Quality:**
- R1 tests lack `assert state.outputs` guard — vacuous negative assertions possible if dedup gate skips before line 237. **Fix: add `assert len(state.outputs) == 1` before spy assertions in every R1 test.**
- Plan Unit 1 checklist shows `[ ]` but the file exists on disk. **Fix: note untracked file in plan; update to `[x]` after adding guard assertion and committing.**

**Section 6 — Test Review (CRITICAL — do not skip):**
```
NEW CODEPATHS (via tests):
  R1a: engine seam flag=1 → publish_with_policy
  R1b: engine seam flag=0/unset → adapter_publish
  R1c: resume seam flag=1 → publish_with_policy
  R1d: resume seam flag=0/unset → adapter_publish
  R2: browser-tier health gate → skipped_policy (flag=1)
  R3: circuit trip → skipped_circuit_open (flag=1, non-browser)
  R4: circuit recovery HALF_OPEN → dispatch allowed (flag=1, non-browser)
  R5: opencli logger events (success + external_error) (flag=1, non-browser)
  R6: R3/R4/R5 on fake (non-browser) — implicit in the above

STATUS:
  R1a–R1d: EXISTS on disk (untracked, needs guard assertion) ✓ pending commit
  R2: NOT YET WRITTEN
  R3: NOT YET WRITTEN (needs RaisingFakeAdapter in conftest)
  R4: NOT YET WRITTEN (needs circuit.time mock pattern)
  R5: NOT YET WRITTEN (needs caplog targeting opencli_logger)
  R6: NOT YET WRITTEN (implicit in R3-R5 using fake slug)
```

Implementation notes for Unit 2:
- `caplog` must target logger named `"opencli"` — `events.py:19` uses `from backlink_publisher._util.logger import opencli_logger as _log`. The logger propagates to root, so `caplog` with `propagate=True` or direct capture on the `opencli` logger name both work. Verify the logger name matches what `opencli_logger` is registered as.
- RaisingFakeAdapter: add to `tests/conftest.py` near `FakeAdapter:544` — a variant whose `publish()` raises `ExternalServiceError`. Use `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD=1` AND pre-seed `circuit.trip(platform, config)` for deterministic trip.
- Circuit recovery (R4): use `mock.patch("backlink_publisher.publishing.reliability.circuit.time")` — pattern confirmed at `tests/test_reliability_circuit.py:95`.
- R2 (health gate): stub `channel_status_store.get_status("velog")` to return non-"bound" — check `webui_store/channel_status.py` for the correct import target.

**Section 7 — Performance:** Test-only. `throttle_min=0, throttle_max=0` in test harness ensures no real sleep.

**Section 8 — Observability:** R5 verifies the observability path directly. No new observability gaps.

**Section 9 — Deployment:** Test-only. No deployment considerations.

**Section 10 — Long-Term Trajectory:**
- **HALF_OPEN trial limiter dead code** — `circuit.py:396` `_increment_half_open_try` has no caller on the publish path. This is a latent bug: the circuit never limits HALF_OPEN trials in practice, which may allow more traffic through recovery than intended. The GO verdict **must** explicitly disclaim this. A TODO should be filed — not deferred to "a separate fix plan" with no tracking artifact.
- **The GO verdict scope** — Codex correctly identifies the risk of a broad GO creating false confidence. The verdict should read: "CLI enforce-branch selection (engine + resume) and stub-level health-gate / circuit-trip / recovery / observability verified through run_publish_loop. **NOT covered:** real-platform error mapping, HALF_OPEN trial-count limiting, default-on readiness."
- **Reversibility:** 5/5 — tests only, easy to delete/modify.
- **Knowledge concentration:** The plan documents the key traps (caplog target, BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD env, dry-run guard, dedup gate) thoroughly. New contributor could follow it.

#### CEO Required Outputs

**NOT in scope:**
- Real-platform error-mapping fidelity (needs bound channels + credentials)
- HALF_OPEN trial-limiting end-to-end (separate fix plan needed)
- Flipping the default flag to on (no evidence threshold defined)
- Any production-logic changes

**What already exists:**
- `TestR1EngineSeam` + `TestR1ResumeSeam` in `tests/test_reliability_policy_live.py` (untracked, 185 lines)
- `FakeAdapter` in `tests/conftest.py:544`
- Circuit time-mock pattern in `tests/test_reliability_circuit.py:95`
- `circuit.trip()` + `is_tripped()` API in `circuit.py`
- Events `opencli_logger` pattern in `events.py:19`

**Dream state delta:** This plan leaves us at "branch selection and stub-level policy behaviors are CI-verified." The 12-month ideal (policy default-on, real error mapping, HALF_OPEN limiting) requires at least two more follow-up plans.

**Error & Rescue Registry:**
| Codepath | What can go wrong | Exception | Rescued? | User sees |
|---|---|---|---|---|
| RaisingFakeAdapter.publish() | ExternalServiceError raised | ExternalServiceError | Y in publish_with_policy | skipped_circuit_open after trip |
| circuit locked_store in test | faults silently swallowed | (swallowed) | Y — fail-soft | counter never advances → R3 flaky |
| caplog missing logger name | no events captured | (none) | N — silent miss | R5 test false-pass |

**Failure Modes Registry:**
| Codepath | Failure mode | Rescued? | Tested? | User sees | Logged? |
|---|---|---|---|---|---|
| dedup gate before line 237 | skip/hold → row never reaches policy branch | Y (by dedup) | NOT YET (guard assertion missing) | Silent false-pass on negative spy assertions | Y (dedup_skip_count) |
| caplog wrong logger | R5 events not captured | N | NOT YET | False-pass | N |
| RaisingFakeAdapter missing | R3 can't trip deterministically | N | NOT YET | Flaky test | N |

---

### Phase 3: Eng Review

#### Scope Challenge

Branch diff: 1 new test file + conftest modification + gate-verdicts. 3 files total. Well under complexity threshold.

**Existing code mapped to sub-problems:**

| Sub-problem | Existing code | Status |
|---|---|---|
| R1 engine seam | `tests/test_reliability_policy_live.py` (untracked) | EXISTS — needs guard assertion |
| R1 resume seam | same file, `TestR1ResumeSeam` | EXISTS — needs guard assertion |
| R2 health gate | `webui_store/channel_status.py` (get_status target) | NOT YET (requires fixture/patch) |
| R3 circuit trip | `circuit.trip()` + RaisingFakeAdapter | NOT YET (FakeAdapter variant needed) |
| R4 recovery | `circuit.time` mock pattern | NOT YET (pattern exists, not applied) |
| R5 events | `opencli_logger` in events.py | NOT YET (caplog wiring needed) |
| Unit 3 gate verdict | `docs/ideation/gate-verdicts.md` | NOT YET |

#### Eng Dual Voices

**CLAUDE SUBAGENT (eng — independent review):**
Findings from CEO phase (same subagent session, independent perspective):
- Architecture sound: test infrastructure follows established project patterns ✓
- Test coverage: R1 engine/resume seam covered; R2-R6 gap real and well-scoped
- Security: no new attack surface ✓
- Hidden complexity: dedup gate vacuous-assertion trap is the main one
- Error paths: caplog logger name is the silent-failure risk

**CODEX SAYS (eng — architecture challenge):**
> The double `policy_enabled()` check (engine calls it before calling `publish_with_policy`, which calls it again at line 146) is awkward split ownership. Testing both paths is correct, but architecturally someone will patch one seam and believe they changed rollout behavior. This is not a test plan issue — it's a future refactor target.
> The `assert state.outputs` guard is non-negotiable for R1 test correctness.
> For R5: confirm the logger name returned by `opencli_logger` — it's not guaranteed to be `"opencli"` unless explicitly registered with that name.

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                           Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ─────── ─────────
  1. Architecture sound?               Yes     Yes*    CONFIRMED
  2. Test coverage sufficient?         Unit1✓  Unit1✓  CONFIRMED (Unit 2 needed)
  3. Performance risks addressed?      N/A     N/A     N/A
  4. Security threats covered?         Yes     Yes     CONFIRMED
  5. Error paths handled?              Mostly  Mostly  CONFIRMED (caplog gap noted)
  6. Deployment risk manageable?       None    None    CONFIRMED
═══════════════════════════════════════════════════════════════
* Codex flags double policy_enabled() check as future refactor target
```

#### Architecture ASCII Diagram

```
TEST FILE: tests/test_reliability_policy_live.py
────────────────────────────────────────────────
TestR1EngineSeam
  monkeypatch env ──▶ run_publish_loop() ──▶ _publish_one_row():237
                                                    │
                          spy: _ENGINE_NS.publish_with_policy ◀── flag=1
                          spy: _ENGINE_NS.adapter_publish     ◀── flag=0/unset

TestR1ResumeSeam
  monkeypatch env ──▶ _publish_one_resume_item() ──▶ :324
                                                    │
                          spy: _RESUME_NS.publish_with_policy ◀── flag=1
                          spy: _RESUME_NS.adapter_publish     ◀── flag=0/unset

TestR2HealthGate (to be written)
  stub channel_status(velog) ≠ bound ──▶ run_publish_loop()
  assert out.status == "skipped_policy"

TestR3CircuitTrip (to be written)
  RaisingFakeAdapter + THRESHOLD=1 OR circuit.trip(fake, config)
  ──▶ run_publish_loop() ──▶ assert is_tripped(fake) == True
  ──▶ run_publish_loop() again ──▶ assert out.status == "skipped_circuit_open"

TestR4Recovery (to be written)
  From tripped state ──▶ advance time via circuit.time mock
  ──▶ run_publish_loop() ──▶ assert dispatch allowed (HALF_OPEN, is_tripped False)

TestR5Observability (to be written)
  caplog(logger_name="opencli") ──▶ run_publish_loop()
  assert "publish_attempt" in records with platform/outcome/duration_ms

CONFTEST:
  FakeAdapter (existing) ──▶ add RaisingFakeAdapter variant raising ExternalServiceError
```

#### Test Diagram (Section 3 — never skip)

| Codepath/requirement | Test type | Exists? | Gap |
|---|---|---|---|
| Engine seam flag=1 | Unit | ✓ (untracked) | Missing `assert state.outputs` guard |
| Engine seam flag=0/unset | Unit | ✓ (untracked) | Missing `assert state.outputs` guard |
| Engine seam flag="0" | Unit | ✓ (untracked) | Missing `assert state.outputs` guard |
| Engine seam dry_run guard | Unit | ✓ (untracked) | No guard needed here (dry_run True is the case) |
| Resume seam flag=1 | Unit | ✓ (untracked) | Missing `assert state.outputs` guard |
| Resume seam flag=0/unset | Unit | ✓ (untracked) | Missing `assert state.outputs` guard |
| R2 browser-tier health gate | Unit | NOT WRITTEN | Need `velog` channel_status stub |
| R3 circuit trip OPEN | Unit | NOT WRITTEN | Need RaisingFakeAdapter + threshold=1 |
| R3 skipped_circuit_open | Unit | NOT WRITTEN | Assert after trip |
| R4 HALF_OPEN recovery | Unit | NOT WRITTEN | Need circuit.time mock |
| R5 opencli events success | Unit | NOT WRITTEN | Need caplog("opencli") |
| R5 opencli events external_error | Unit | NOT WRITTEN | Need caplog("opencli") + raising adapter |
| R6 non-browser fake coverage | Implicit | Via R3-R5 | Satisficed when R3-R5 run on `fake` |
| Unit 3 gate-verdicts entry | Doc | NOT WRITTEN | Append scoped GO |

**Gaps requiring action before merge:**
1. `assert state.outputs` (or `assert len(state.outputs) >= 1`) in every R1 test that asserts a spy was NOT called — prevents vacuous pass if dedup gate skips before line 237
2. RaisingFakeAdapter variant in conftest.py
3. R2, R3, R4, R5 test classes (Unit 2)
4. Gate-verdicts GO entry with explicit HALF_OPEN disclaimer (Unit 3)

**Test ambition checks:**
- 2am Friday confidence: dedup gate guard assertion (R1) and is_tripped pre-assertion (R3) are the load-bearing correctness tests
- Hostile QA: would add `assert state.outputs` absence causes test to pass vacuously — already identified
- Chaos: circuit locked_store faults — plan correctly notes pre-seeding `circuit.trip()` beats relying on counter accumulation

**Flakiness risks:**
- R3 via counter accumulation: FLAKY (locked_store faults swallow count) → mitigate with `circuit.trip()` pre-seed
- R4 via real time: FLAKY → mitigate with `circuit.time` mock (pattern exists)
- caplog: NOT flaky if logger name is correct; SILENT MISS if logger name is wrong

#### Implementation Tasks

- [ ] **T1 (P1, human: ~15min / CC: ~2min)** — `tests/test_reliability_policy_live.py` — Add `assert state.outputs` guard to all 6 R1 tests
  - Surfaced by: CEO/Eng dual voices — vacuous negative assertion risk when dedup gate skips before line 237
  - Files: `tests/test_reliability_policy_live.py`
  - Verify: `assert len(state.outputs) == 1` in each R1 test before spy assertions; test fails if row is dedup-skipped

- [ ] **T2 (P1, human: ~30min / CC: ~5min)** — `tests/conftest.py` — Add `RaisingFakeAdapter` variant
  - Surfaced by: Eng review Section 3 — R3 needs a raising adapter for circuit trip
  - Files: `tests/conftest.py` (near FakeAdapter:544)
  - Verify: `RaisingFakeAdapter.publish()` raises `ExternalServiceError`; fixture registered alongside `FakeAdapter`

- [ ] **T3 (P1, human: ~2h / CC: ~15min)** — `tests/test_reliability_policy_live.py` — Write Unit 2 (R2–R6)
  - Surfaced by: Plan Unit 2; Eng review Section 3 gap table
  - Files: `tests/test_reliability_policy_live.py`
  - Key implementation notes:
    - R2: stub `channel_status_store` for `velog` to return non-"bound"; assert `skipped_policy`
    - R3: `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD=1` + pre-seed `circuit.trip("fake", config)`; assert `is_tripped` True before asserting `skipped_circuit_open`
    - R4: `mock.patch("backlink_publisher.publishing.reliability.circuit.time")` (pattern: `test_reliability_circuit.py:95`); advance past cooldown; assert dispatch allowed
    - R5: `caplog` on `"opencli"` logger; assert `publish_attempt` records with `platform`/`outcome`/`duration_ms` fields
  - Verify: `PYTHONHASHSEED=0 pytest tests/test_reliability_policy_live.py -v`

- [ ] **T4 (P1, human: ~5min / CC: ~2min)** — `docs/ideation/gate-verdicts.md` — Add scoped GO entry (Unit 3)
  - Surfaced by: CEO dual voices — GO verdict must disclaim HALF_OPEN and real error mapping
  - Files: `docs/ideation/gate-verdicts.md`
  - Required disclaimer: "CLI enforce-branch selection (engine + resume) and stub-level health-gate / circuit-trip / recovery / observability verified through run_publish_loop. NOT covered: real-platform error mapping, HALF_OPEN trial-count limiting, default-on readiness."
  - Verify: entry is dated, references this plan file + test file

- [ ] **T5 (P2, human: ~5min / CC: ~1min)** — `docs/plans/2026-06-03-007-*.md` — Update Unit 1 checkbox from `[ ]` to `[x]` (after T1 guard assertion is added and file is committed)
  - Surfaced by: CEO review — plan presents Unit 1 as unstarted; it's functionally complete
  - Files: this plan file
  - Verify: `[ ] **Unit 1:` → `[x] **Unit 1:`

- [ ] **T6 (P3, TODOS.md)** — `HALF_OPEN trial limiter (`_increment_half_open_try`) has no caller on the publish path` — file as a tracked TODO/fix plan
  - Surfaced by: CEO dual voices (both Claude + Codex) — dead code limiter means circuit-recovery is unlimited in HALF_OPEN; this is a latent production gap
  - Not blocking this plan; must not be silently dropped
  - Verify: a tracking artifact exists (TODOS.md entry or separate fix plan stub)

#### Completion Checklist

- [x] Scope challenge with actual code analysis
- [x] Architecture ASCII diagram produced
- [x] Test diagram mapping codepaths to coverage
- [x] "NOT in scope" section written
- [x] "What already exists" section written
- [x] Failure modes registry with critical gap assessment
- [x] Dual voices ran (Codex + Claude subagent)
- [x] Eng consensus table produced

---

### Decision Audit Trail

<!-- AUTONOMOUS DECISION LOG -->
| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | Mode: HOLD SCOPE | P3 (pragmatic), P5 (explicit) | Verification probe on completed feature; no expansion justified | EXPANSION, SELECTIVE EXPANSION |
| 2 | CEO | Approach A (committed test artifact) | P1 (completeness) | Only durable form; one-off CLI run doesn't prevent regression | One-off operator run (Approach B) |
| 3 | CEO | Acknowledge untracked file (Unit 1 ~done) | P6 (bias toward action) | Prevents implementer from rewriting existing tests | Silently ignoring |
| 4 | CEO/Eng | Add `assert state.outputs` guard | P1 (completeness) | Vacuous negative assertion risk is real; guard costs 1 line | Skip guard |
| 5 | CEO | Flag HALF_OPEN dead code as P3 TODO | P1 (completeness), P6 (action) | Both Claude + Codex flagged; high-confidence; must not be silently dropped | Defer with no tracking artifact |
| 6 | CEO | Scope GO verdict precisely | P5 (explicit) | "GO" without disclaimer creates false management confidence | Broad GO |
| 7 | Eng | Reuse circuit.time mock for R4 | P3 (pragmatic) | Pattern already exists at test_reliability_circuit.py:95 | New time mechanism |
| 8 | Eng | Pre-seed circuit.trip() for R3 (not counter accumulation) | P5 (explicit) | locked_store fault swallows count; pre-seed is deterministic | Counter accumulation only |

**TASTE DECISIONS (surfaced at gate):**

| # | Topic | Claude position | Codex position | Impact if Codex wins |
|---|-------|----------------|----------------|---------------------|
| TD1 | Probe scope: stay narrow vs expand to HALF_OPEN fix | HOLD SCOPE | Expand | ~L effort spike; out of scope for verification probe |
| TD2 | Real adapter error mapping | Defer (out of scope) | Include at least 1-2 adapters | Credential dependency; blocks fast ship |
| TD3 | GO verdict approach | Scoped GO with explicit disclaimer | Don't record a gate verdict (or label "seam-only") | Either is fine; scoped GO is more consistent with gate ledger conventions |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/autoplan` Phase 1 | Scope & strategy | 1 | issues_open | 6 findings (2 HIGH, 2 MEDIUM, 2 LOW); Unit 1 untracked, vacuous assertion risk, HALF_OPEN gap |
| Codex CEO Voice | `/autoplan` dual voice | Independent 2nd opinion | 1 | issues_open | 6 strategic blind spots; expand scope suggestion → TASTE DECISION |
| Eng Review | `/autoplan` Phase 3 | Architecture & tests | 1 | issues_open | 6 implementation tasks (4 P1, 1 P2, 1 P3); Unit 2 + Unit 3 not written |
| Design Review | `/autoplan` Phase 2 | UI/UX gaps | 0 | skipped | No UI scope detected |

**VERDICT:** 6 auto-decided findings written to plan + 3 taste decisions surfaced at gate. See Final Approval Gate below.
