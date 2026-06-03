---
title: "feat: Live-verify the reliability policy enforce path"
type: feat
status: active
date: 2026-06-03
origin: docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md
---

# feat: Live-verify the reliability policy enforce path

## Overview

The coordinated publish policy layer (health gate + circuit breaker + observability,
plan 2026-05-28-001) is fully shipped and wired into the real publish path, but gated
behind `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1` (default off). The existing 20
unit tests already set the flag and exercise `publish_with_policy` **directly**,
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
The risk being retired is narrow and specific: **does the enforce branch wire up
correctly when the flag is on, through the real CLI loop body** — not the policy
internals (already unit-covered). A direct call to `publish_with_policy` does NOT retire
this risk; the test must drive `run_publish_loop` so the real `policy_enabled()` branch
and the module-level import seams execute.

## Requirements Trace

- R1. **(Primary)** A `run_publish_loop` execution with the flag set routes dispatch
  through `publish_with_policy`, not the `else: adapter_publish` branch; flag-unset stays
  a transparent passthrough. Asserted with a discriminating spy on both seams.
- R2. Health gate (**browser-tier only**: `velog`/`medium`/`mastodon`): non-`bound`
  `channel_status` yields `skipped_policy`, adapter never reached.
- R3. Circuit trip → OPEN: a stub raising `ExternalServiceError` enough times (or with
  the consecutive-errors threshold lowered) trips the per-platform circuit; the next
  attempt yields `skipped_circuit_open` without dispatching.
- R4. HALF_OPEN: after a trip, one trial is allowed; trials beyond the limit yield
  `skipped_circuit_open`.
- R5. Observability: `publish_attempt` events emitted per outcome (≥ `success` + one
  error) with `platform`, `outcome`, `duration_ms`.
- R6. At least one of R3/R4/R5 runs on a **non-browser-tier** platform (the `fake`
  registry slug qualifies — it is not in `_BROWSER_TIER`). R2 is excluded by design.

## Scope Boundaries

- No real outbound publish; no credentials; no footprint. Stub adapter only.
- No changes to `policy.py` / `circuit.py` / `_engine.py` / `_resume.py` logic — this is
  test-only. If verification surfaces a real bug, it becomes a **separate fix plan**.
- Does not flip the default flag. No CLI/schema edits (R9 contract preserved).
- Does NOT retire real-platform error-mapping fidelity (real 429/503/ban/session-expiry
  → typed exception vs generic `Exception`→`TRANSIENT`-no-trip). Deferred — needs a bound
  channel + credentials.

## Context & Research

### Relevant Code and Patterns

- **Branch seam (R1):** `src/backlink_publisher/cli/publish_backlinks/_engine.py`
  — `_publish_one_row` (line ~89) late-imports `policy_enabled`, `publish_with_policy`,
  `adapter_publish` from `backlink_publisher.cli.publish_backlinks` at call time
  (explicit comment: "Tests patch these at ...publish_backlinks.X"). Spy target for the
  engine path = `backlink_publisher.cli.publish_backlinks.{publish_with_policy,adapter_publish}`.
- **Resume seam (R1):** `src/backlink_publisher/cli/_resume.py:29` imports
  `policy_enabled, publish_with_policy` at **module top** from
  `...reliability.policy`. Spy target for the resume path =
  `backlink_publisher.cli._resume.{publish_with_policy,adapter_publish}` (different
  location than the engine seam — do not assume one patch covers both).
- **Full-chain entry:** `run_publish_loop` (`_engine.py:62`) drives rows through
  `_publish_one_row`.
- **Stub adapter:** `tests/conftest.py:544` `FakeAdapter` + `fake_platform_registered`
  fixture registers slug `"fake"` (non-browser-tier, dofollow). Its `publish()` returns
  `status="drafted"` and never raises — so R3/R4 need a **raising variant** (subclass or
  a configurable `publish` that raises `ExternalServiceError`).
- **Circuit knobs (correct env names — origin doc had this wrong):**
  `circuit.py` reads `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS` (trip threshold,
  default in `_DEFAULT_CONSECUTIVE_ERRORS`), `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES`,
  `BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S`. There is **no** `..._ERROR_THRESHOLD` var.
- **Events sink (R5):** `reliability/events.py` `emit_attempt` → `_log.info(payload)`.
  Verify via captured log records (caplog), not a file.
- **Test isolation:** four autouse conftest fixtures sandbox config, pass URL/content
  checks, block sockets. Circuit state is flock-based on a real path → the test must use
  a real temp config dir so state round-trips (HALF_OPEN/OPEN persistence).
- **Pattern references:** `tests/test_publish_backlinks_characterization.py`,
  `tests/integration/`, `tests/test_r9_extension_readiness.py` (registry fixture usage).

### Institutional Learnings

- `_BROWSER_TIER = frozenset({"velog","medium","mastodon"})` in `policy.py`; the health
  gate (R2) is browser-tier-scoped by design — verifying R2 on a non-browser platform is
  vacuous (origin doc Key Decision).
- `PYTHONHASHSEED=0` required for footprint tests; not expected to matter here but run
  the suite with the standard harness.

## Key Technical Decisions

- **Committed `real_*`-style test as the durable artifact** (not a one-off operator CLI
  run): keeps the enforce seam covered against regression. Resolves origin deferred Q1.
- **Two separate R1 assertions** (engine + resume) because the import seams live in
  different modules — a single patch location would silently miss one path.
- **Reuse `fake` slug for the non-browser coverage (R6)** rather than stubbing a real
  platform; add a raising variant for circuit behaviors. Resolves origin deferred Q2/Q3.
- **Drive circuit trip deterministically** by setting
  `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS=1` (or raising N times), so a single
  scripted error opens the circuit — avoids depending on the default threshold.

## Open Questions

### Resolved During Planning

- Durable artifact form → committed test (above).
- Stub injection without touching `cli/*.py` → reuse `fake_platform_registered` +
  raising variant; registry resolves dynamically (R9 contract holds).
- Which non-browser platform → `fake`.
- Circuit threshold env name → `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS`.

### Deferred to Implementation

- Exact mechanism to feed a minimal seeds row into `run_publish_loop` (its real
  signature/iterator shape) — read at implementation time; mirror `tests/integration/`.
- Whether a `bound` `channel_status` for the browser-tier R2 case is set via the
  `channel_status` store fixture or a direct `get_status` patch — pick the lightest that
  the conftest sandbox already supports.
- Real-platform error-mapping fidelity verification — out of scope; separate future
  effort when a bound channel + credentials exist.

## Implementation Units

- [ ] **Unit 1: R1 discriminating seam tests (engine + resume) — the primary risk**

**Goal:** Prove the flag actually switches the CLI dispatch branch, end-to-end through
`run_publish_loop`, on both publish paths.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `tests/test_reliability_policy_live.py`

**Approach:**
- Register the `fake` platform via `fake_platform_registered`. Use a real temp config dir.
- **Flag on:** set `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`, spy on
  `backlink_publisher.cli.publish_backlinks.publish_with_policy` and `.adapter_publish`,
  run `run_publish_loop` with a single `fake` row, assert `publish_with_policy` was called
  and the direct `adapter_publish` branch was **not**.
- **Flag off:** assert the inverse (direct `adapter_publish`, `publish_with_policy` not
  called) — transparent passthrough.
- Repeat the on/off discriminating assertion for the resume path, spying at
  `backlink_publisher.cli._resume.*` and driving the resume entry.

**Patterns to follow:** `tests/test_publish_backlinks_characterization.py` for loop
setup; the late-import-seam patch convention noted in `_engine.py`.

**Test scenarios:**
- Happy path: flag=1 → engine routes via `publish_with_policy` (spy hit), `adapter_publish` direct branch not taken.
- Happy path: flag unset → engine routes via direct `adapter_publish`, `publish_with_policy` not called.
- Integration: flag=1 → resume path (`_resume`) routes via `publish_with_policy` at its own seam.
- Edge case: flag set to `"0"` / empty → treated as off (passthrough), matching `policy_enabled()`.

**Verification:** Both seams demonstrably select the policy path only when the flag is
`"1"`; a deliberately wrong patch location would fail the assertion (discriminating).

- [ ] **Unit 2: End-to-end regression layer for policy behaviors (R2–R6)**

**Goal:** With the flag on, observe each policy behavior firing through the real chain —
as regression coverage layered on the Unit 1 seam proof, not as the primary risk.

**Requirements:** R2, R3, R4, R5, R6

**Dependencies:** Unit 1 (shared fixtures/harness)

**Files:**
- Modify: `tests/test_reliability_policy_live.py`

**Approach:**
- Add a raising stub variant (subclass of `FakeAdapter` or a configurable `publish`)
  that raises `ExternalServiceError` to drive circuit behaviors.
- **R2 (browser-tier):** register/stub a browser-tier slug (e.g. `velog`) with
  `channel_status` ≠ `bound`; assert `run_publish_loop` yields `skipped_policy` and the
  adapter is never invoked.
- **R3:** set `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS=1`; raising stub on `fake`;
  first attempt raises/records, second attempt yields `skipped_circuit_open` (no dispatch).
- **R4:** with a tripped circuit + `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` set,
  assert one trial allowed then `skipped_circuit_open` beyond the limit.
- **R5:** with `caplog`, assert `publish_attempt` records for a `success` (closed-circuit
  `fake` dispatch) and one error outcome, each carrying `platform`/`outcome`/`duration_ms`.
- **R6:** R3/R4/R5 above run on `fake` (non-browser-tier) — satisfies the uniform-coverage
  requirement; explicitly do not assert R2 on `fake`.

**Patterns to follow:** existing assertions in `tests/test_reliability_policy.py` for
expected `AdapterResult.status` sentinels and event shape; `tests/integration/` for
chain wiring.

**Test scenarios:**
- Happy path (R5): closed-circuit `fake` dispatch emits a `success` `publish_attempt` with required fields.
- Error path (R3): raising stub + threshold=1 → second attempt returns `skipped_circuit_open`, adapter not called again.
- Edge case (R4): HALF_OPEN allows exactly the configured trial count, then `skipped_circuit_open`.
- Error path (R2): browser-tier slug, status≠`bound` → `skipped_policy`, adapter never reached.
- Integration (R6): the R3/R4/R5 cases execute on the non-browser `fake` platform via the real loop.

**Verification:** Each sentinel/event observed through `run_publish_loop` with the flag
on; circuit state persists across attempts via the temp config dir.

- [ ] **Unit 3: Record the GO verdict for audit continuity**

**Goal:** Log the probe outcome in the gate ledger so the audit trail is consistent,
without implying the probe was gate-blocked.

**Requirements:** Success Criteria (verdict line)

**Dependencies:** Unit 1, Unit 2 (verdict reflects passing tests)

**Files:**
- Modify: `docs/ideation/gate-verdicts.md`

**Approach:**
- Append a `GO` entry noting this is a pure-verification probe (R16-exempt), referencing
  this plan and the new test file. No `gate-probe` run required.

**Test expectation:** none — documentation-only entry.

**Verification:** A dated `GO` line referencing the plan + test exists in
`docs/ideation/gate-verdicts.md`.

## System-Wide Impact

- **Interaction graph:** Test-only. Exercises `run_publish_loop` → `_publish_one_row`
  → `publish_with_policy`/`adapter_publish`, and `_resume` dispatch. No production code
  changes.
- **State lifecycle risks:** Circuit flock state must be isolated per test (temp config
  dir) so OPEN/HALF_OPEN persistence is real but does not leak across tests; restore the
  registry via the existing fixture teardown.
- **Unchanged invariants:** `policy.py`/`circuit.py`/`_engine.py`/`_resume.py` behavior,
  the default-off flag, the R9 CLI/schema contract, and the existing 20 unit tests all
  remain untouched.
- **Integration coverage:** This plan's whole point is the cross-layer (CLI loop →
  policy) coverage that the existing direct-call unit tests do not prove.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Test calls `publish_with_policy` directly and re-creates a unit test (vacuous R1) | Unit 1 drives `run_publish_loop` and spies the module seams; a direct call would not hit the spied import path. |
| Circuit state doesn't round-trip in the sandbox → R3/R4 flaky | Use a real temp config dir (not the in-memory sandbox) so flock state persists across attempts. |
| Wrong threshold env name (origin doc error) → circuit never trips | Use `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS`; assert the trip actually occurred before asserting `skipped_circuit_open`. |
| Patching one seam location misses the other path | Separate engine vs resume assertions at their respective module namespaces. |
| Asserting R2 on `fake` (non-browser) silently passes vacuously | R6 scope explicitly excludes R2 on non-browser; R2 tested only on a browser-tier slug. |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md](docs/brainstorms/2026-06-03-live-verify-reliability-policy-requirements.md)
- Related code: `publishing/reliability/policy.py`, `publishing/reliability/circuit.py`,
  `publishing/reliability/events.py`, `cli/publish_backlinks/_engine.py`,
  `cli/_resume.py`, `tests/conftest.py` (`FakeAdapter`), `tests/test_reliability_policy.py`
- Related plan: `docs/plans/2026-05-28-001-feat-publish-reliability-policy-plan.md` (completed)
