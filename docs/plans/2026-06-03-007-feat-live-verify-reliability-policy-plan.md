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
