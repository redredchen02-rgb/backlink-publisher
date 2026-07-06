---
title: "LITE Accepted Deferrals — Trigger-Condition Check (R7/R8/R10)"
date: 2026-07-06
category: audits
component: release_readiness
severity: high
read_only: true
applies_when:
  - Deciding whether R7 (cross-process rehydrate), R8 (Pydantic non-authoritative
    validation), or R10 (no per-probe timeout) need a follow-up plan
tags:
  - lite-release
  - accepted-deferral
  - scheduler
  - keepalive
  - recheck
  - audit
---

# LITE Accepted Deferrals — Trigger-Condition Check (R7/R8/R10)

**Unit:** E3 of `docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md`
**Type:** Read-only verification. No code or test files were modified.
**Source doc audited:** `docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md` (dated 2026-06-05).
**Repo state at time of audit:** worktree `bp-hidden-debt-hardening-sweep`, branch `opt/hidden-debt-hardening-sweep`, HEAD `45b4512a` (git history shared with all sibling worktrees via the single `.git`).

## Summary Table

| Deferral | Trigger condition | Verdict | Follow-up recommended? |
|---|---|---|---|
| **R7** — G5b cross-process restart-durable rehydrate | "An unattended/scheduled recheck is introduced" | **TRIGGERED** (literally met), but with an important nuance — see below | Yes — verification-scoped follow-up, not necessarily the original heavyweight fix |
| **R10** — no per-probe timeout | "Unattended/scheduled recheck is introduced, or a probe is observed hanging in production longer than the launchd window" | **TRIGGERED** | Yes — this one is unambiguous and higher-severity than R7 |
| **R8** — Pydantic non-authoritative validation | "(a) 3rd observed Pydantic/schema.py drift; (b) new SSRF/injection-relevant publish-payload field; (c) new read-path surfaces a payload field without a schema.py write-time gate" | **NOT TRIGGERED** | No — re-check at the next event listed below |

---

## R7 — G5b: cross-process restart-durable rehydrate

**Original trigger text:** "An unattended/scheduled recheck is introduced (e.g., the launchd job from R4 is extended to multi-hour runs without operator presence). At that point, G5b becomes a reliability requirement."

**Finding: the literal condition is now met.** The **autopilot** feature — `webui_app/scheduler.py::_register_autopilot_job` / `_keepalive_cycle_job`, backed by `webui_app/services/_keepalive_engine.py::run_keepalive_for_site` — was introduced in commit `43855c6f` ("feat(U7): autopilot per-site keepalive scheduler backend", **2026-06-09**, four days after the deferral doc's 2026-06-05 date). It is a per-site `APScheduler` `BackgroundScheduler` interval job that runs a keep-alive/recheck cycle **fully unattended**, indefinitely, for as long as `webui.py` is running, at an operator-configured interval between 1 hour and 30 days (`webui_app/routes/sites.py:341-342`, default 86400s/24h). This is precisely the class of thing the deferral's rationale said didn't exist yet: "the operator is in the room when rechecks run."

**Nuance — why this isn't a clean 1:1 match to the original G5b concern:** G5b (as scoped in `webui_app/services/keepalive_job.py`'s own docstring) is about resuming a **tracked job** (`KeepaliveJobRegistry`'s in-memory `KeepaliveJob`/`GapClosureJob`/`RepublishJob`, exposed via `start_recheck()` / `start_gap_closure()` / `start_republish()`) after a full process restart. Those three entry points remain **operator-triggered only**, via explicit HTTP routes (`webui_app/routes/keep_alive.py:65,108,122`, `webui_app/routes/command_center.py:242`) — autopilot never calls them. Autopilot instead uses a separate, simpler, structurally-idempotent path (`run_keepalive_for_site`): each tick re-derives candidates fresh from `EventStore`, writes each probe result durably and immediately (`emit_recheck` / `write_verified_at`, not batched), and on process restart `_restore_scheduled_jobs()` just re-registers the recurring job from persisted `schedule_store` config (`webui_app/scheduler.py:291-298`). A crash mid-cycle therefore does not orphan unrecoverable state — it loses at most one tick's un-probed remainder, which the next tick picks up again. By design this sidesteps the original G5b risk (an abandoned job with no oversight and no persisted progress).

**Conclusion:** Flag as **triggered** per the literal trigger wording (an unattended/scheduled recheck now exists), but the follow-up should **verify** the restart-safety property claimed above with an explicit test (none currently exists — `tests/test_autopilot_scheduler.py` has no restart/crash-recovery test), rather than assume the deferral's original proposed fix ("persist job state to the DB or a coordinator service") is what's needed. The job-registry-tracked jobs (recheck/gap_closure/republish) that G5b's docstring is actually about remain operator-initiated and therefore lower priority for a durability fix.

---

## R10 — recheck timeout

**Original trigger text:** "Unattended/scheduled recheck is introduced, or a probe is observed hanging in production longer than the launchd `StartCalendarInterval` window. At that point, add a per-probe `socket.settimeout` or `signal.alarm` and an overall run-wall-clock cap."

**Finding: TRIGGERED, and the mitigation gap is real.**

1. The `recheck-backlinks` CLI (the literal subject of the deferral text) already had both a per-probe timeout **and** a batch wall-clock cap when the deferral was written — `src/backlink_publisher/cli/ops/recheck_backlinks.py:45-46,203-223`: `_PER_TARGET_TIMEOUT = 10.0`, `_BATCH_BUDGET_S = 600.0`, enforced in `_probe_batch()` ("Stops at the batch wall-clock budget so a tarpitting host can't stall the cron run indefinitely (SEC1)"), plus a non-blocking `fcntl` single-run lock (`_single_run_lock`). This was added in commit `d1ac28ef` on **2026-05-29**, a week *before* the 2026-06-05 deferral doc — so the deferral's characterization of the CLI itself was already stale the day it was written.
2. However, the **new unattended surface introduced after the deferral** — the autopilot scheduler (2026-06-09) driving `run_keepalive_for_site` / `KeepaliveJobRegistry._run_recheck` — has **no equivalent batch wall-clock ceiling**. Each cycle loops over every matching candidate for a site with only the per-probe default (`recheck_link`'s `timeout: float = 10.0` default, inherited implicitly, not an explicit hardened constant) and no `_BATCH_BUDGET_S`-style deadline. A site with many candidates, or one hung probe, can run unbounded.
3. This gap is materially worse than the original CLI-only version of the risk because of the executor topology: `webui_app/scheduler.py:25-28` runs **all** APScheduler jobs — `queue_processor`, `batch_ops_drain`, `error_reports_purge`, and every per-site autopilot job — on a single shared `ThreadPoolExecutor(max_workers=1)`. A single hung probe anywhere therefore stalls the entire background-job subsystem, not just one operator-cancellable CLI invocation. `misfire_grace_time: 3600` only governs whether a late *trigger* still fires — it does not recover a worker thread that is stuck executing.
4. The underlying "hang beyond nominal timeout" scenario is realistic, not theoretical: the probe's fetch (`src/backlink_publisher/content/_preflight_fetch.py:287-315`, `_PREFLIGHT_OPENER.open(req, timeout=...)`) is a `urllib`-based open where the `timeout` kwarg bounds connect/read but not always DNS resolution on all platforms — exactly the class of stuck-probe scenario the deferral's own resume trigger anticipated ("a probe is observed hanging... longer than the ... window").
5. No test currently exercises this: `tests/test_autopilot_scheduler.py` has zero timeout/deadline/hang coverage (grepped for `timeout|hang|deadline|budget` — the only hit is an unrelated mocked error string).

**Conclusion:** Trigger condition is unambiguously met. Recommend a follow-up plan to extend the CLI's existing `_BATCH_BUDGET_S`/`_PER_TARGET_TIMEOUT`/lock pattern (already proven in `recheck_backlinks.py`) to the autopilot/`run_keepalive_for_site` path, and consider whether the single-worker `ThreadPoolExecutor` should be sized >1 or otherwise isolated so one stuck probe can't block unrelated jobs (queue processing, batch ops, purge).

---

## R8 — Pydantic opt-in / schema.py as sole authoritative gate

**Original trigger text:** "(a) Third observed drift between Pydantic annotations and `schema.py` validators; (b) any new field that carries SSRF-relevant or injection-relevant content is added to a publish payload; (c) any new read-path surfaces a payload field to the UI without a `schema.py` write-time gate."

**Finding: NOT TRIGGERED.**

- `src/backlink_publisher/schema.py` (the authoritative dict-validator gate: `INPUT_SCHEMA_FIELDS`, `INPUT_OPTIONAL_FIELDS`, `OUTPUT_REQUIRED_FIELDS`, `OUTPUT_OPTIONAL_FIELDS`) has had **no substantive changes since 2026-06-05** — the only commit touching it since is `0138fdc9` (2026-06-26, a repo-wide ruff/isort/pyupgrade lint pass with no field-level changes).
- `src/backlink_publisher/_payload_types.py` (the Pydantic v2 models — `SeedPayload`, `PlannedPayload`, `LinkModel`, `SeoModel`, `ValidationBlock`) likewise has no field additions since 2026-06-05 — only a lint pass (2026-06-26) and a mypy type-annotation pass (2026-06-24). The Pydantic models were themselves introduced on **2026-06-04** (`112830b3`), the day before the deferral doc, so this predates and is already accounted for by the doc.
- No git history evidence of any "observed drift" incident being logged anywhere in `docs/solutions/` or `docs/plans/` that would count toward "the 3rd occurrence" — the one doc found referencing "schema drift" (`docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md`) is about unrelated hand-written-copy-snippet idiom drift between two emitters, not Pydantic-vs-`schema.py` drift, so it doesn't count as an occurrence toward this trigger either way.
- No new publish-payload field carrying SSRF/injection-relevant content was found added since 2026-06-05.
- Spot-checked the one new read-path in the area the deferral explicitly calls out by name (the "R2c.a strip aggregation" security-boundary example, and the new `/api/v1` surface from the v0.6.0 SPA, commit `1afc014b`, 2026-06-23): the only `content_markdown`/`content_html` exposure found in `webui_app/api/v1/pipeline.py` + `webui_app/api/v1/schemas.py` is an LLM body-**regeneration preview** endpoint (`RegenBodyResponseSchema`, a Marshmallow API-shape schema for OpenAPI, unrelated to the domain `schema.py` gate) that returns freshly-rendered draft content for in-place editing, before it is folded back into an actual publish payload — it does not bypass the write-time `schema.py` gate for the eventual publish path, which is unchanged. This is a best-effort spot-check, not an exhaustive audit of every route added since 2026-06-05 (the volume of work in that window — v0.6.0 SPA, autopilot, GSC feedback loop, Full Automation Upgrade — is large); see recommendation below for narrowing a future check.

**Conclusion:** No evidence any of the three (a)/(b)/(c) sub-conditions have fired. Recommend keeping this deferred.

**Recommended next re-check trigger:** re-run this check (a) the next time `schema.py` or `_payload_types.py` gets a substantive field-level diff (not a lint-only pass), or (b) the next time a new `/api/v1` route is added that renders a `content_markdown`/`content_html`/`seo`/`links` field sourced from a stored plan/draft — at that point, explicitly confirm the value was validated by `schema.py`'s write-time path (`validate_and_convert_output` / `validate_publish_payload`) before being persisted, per the deferral's Security boundary note.

---

## Methodology

For each deferral, compared the literal trigger text against:
1. `git log --since=2026-06-05` on the relevant module(s): `webui_app/scheduler.py`, `webui_app/services/keepalive_job.py`, `webui_app/services/_keepalive_engine.py`, `src/backlink_publisher/cli/ops/recheck_backlinks.py`, `src/backlink_publisher/recheck/probe.py`, `src/backlink_publisher/schema.py`, `src/backlink_publisher/_payload_types.py`, `src/backlink_publisher/_schema_input.py`, `src/backlink_publisher/_schema_output.py`.
2. `git log --all` (all branches share one `.git`) for feature-introduction commits (`autopilot`, `keepalive`, `recheck`, `SEC1`, `_BATCH_BUDGET_S`) to pin exact introduction dates relative to 2026-06-05.
3. Direct reading of the current implementation (`webui_app/scheduler.py`, `webui_app/services/_keepalive_engine.py`, `webui_app/services/keepalive_job.py`, `src/backlink_publisher/recheck/probe.py`, `src/backlink_publisher/cli/ops/recheck_backlinks.py`, `src/backlink_publisher/content/_preflight_fetch.py`, `src/backlink_publisher/schema.py`, `src/backlink_publisher/_payload_types.py`, `webui_app/api/v1/pipeline.py`, `webui_app/api/v1/schemas.py`) to confirm behavior, not just intent from commit messages.
4. `tests/test_autopilot_scheduler.py`, `tests/test_recheck_periodic_schedule.py`, `tests/test_keepalive_plist.py` for existing coverage of the risk areas.

No code, test, or config file was modified as part of this audit. No follow-up plan was opened — per the parent plan's Scope Boundaries, opening/implementing the R7/R10 follow-up is explicitly out of scope for this unit and is left to the user to commission separately.
