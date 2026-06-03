---
title: "refactor: Remove unwired HALF_OPEN trial limiter (keep cooldown-only recovery)"
type: refactor
status: active
date: 2026-06-03
origin: docs/brainstorms/2026-06-03-circuit-half-open-limiter-cleanup-requirements.md
---

# refactor: Remove the unwired HALF_OPEN trial limiter

## Overview

The circuit breaker (`publishing/reliability/circuit.py`) ships a HALF_OPEN
**trial-count limiter** that is never wired: `_increment_half_open_try` has zero
callers in `src/` and `tests/`, and the `half_open_tries` state counter is written but
never incremented. The `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` env var and the
module docstring advertise a feature that does not exist. This removes that dead
scaffolding, keeping the **cooldown-only recovery** the code actually performs (and that
the original plan `2026-05-28-001` intended — "cooldown-only v1; half-open deferred").

Pure dead-code removal: no **functional** change to trip, cooldown, or recovery-path
behavior. The only observable difference is that written circuit-state objects no longer
include the orphan `half_open_tries` key (no reader depends on it).

## Problem Frame

See origin: `docs/brainstorms/2026-06-03-circuit-half-open-limiter-cleanup-requirements.md`.
Not a bug, not intentional design — an **incomplete feature**. Phase 3 added HALF_OPEN
scaffolding but only connected the state *transition* (`is_tripped` transitions
OPEN→HALF_OPEN after cooldown and returns `False`, allowing the next attempt through),
never the trial cap. Discovered during the document-review of plan `2026-06-03-007`.

## Requirements Trace

- R1. Remove the dead limiter surface: `_increment_half_open_try`, `_half_open_tries`,
  `_DEFAULT_HALF_OPEN_TRIES`, and the `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` env var.
- R2/R5. Fix **all** misleading "limited traffic / trial count" doc claims in
  circuit.py — there are **four**, not two (review-confirmed): module docstring "Half-open
  trial count … (default 1)" (~line 32) and "half-open: test mode, limited traffic
  allowed" (~line 29); the `is_tripped` docstring "allows limited traffic after cooldown"
  (~line 220); and the `is_tripped` HALF_OPEN inline comment "limited number of requests
  through" (~line 241). Reword each to "allows traffic through to test recovery — no trial
  cap". (circuit.py is the only *live* doc of the knob; AGENTS.md/gate-verdicts do not
  mention it; historical plan docs left as-is.)
- R3. Preserve recovery behavior unchanged — recovery depends only on `is_tripped` /
  the HALF_OPEN transition, **not** on `half_open_tries`, so removing the field cannot
  affect it. `test_half_open_allows_test_traffic` and the R4 recovery case in
  `test_reliability_policy_live.py` pass with no edits to their behavioral assertions.
- R4. Stop writing the `half_open_tries` field: drop the `"half_open_tries": 0`
  write-sites (circuit.py ~186/205/280/325/387/437) **and** the carry-through copy
  `entry.get("half_open_tries", 0)` at ~196 (it only propagated the orphan field forward).
  Backward-safe: the only *logic* read of the field lived inside the deleted
  `_increment_half_open_try`; nothing else reads it, so older on-disk state carrying the
  key is simply ignored. Lazy "stop writing it" — no migration path needed.

## Scope Boundaries

- **Not** building real trial-cap semantics (the deferred feature). Separate effort if ever wanted.
- **Not** removing `CircuitState.HALF_OPEN` or `_transition_to_half_open` — that path is
  wired, tested, and is the actual cooldown recovery mechanism.
- **Not** changing trip thresholds, cooldown, or the default-off policy flag.
- **Not** editing historical plan docs (`2026-06-03-007`, `2026-05-28-001`).

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/publishing/reliability/circuit.py`:
  - Dead to delete: `_DEFAULT_HALF_OPEN_TRIES` (~line 57), `_half_open_tries()`
    (~152–160), `_increment_half_open_try()` (~396–423, which also contains the only
    reads of `half_open_tries` at 408/409/417).
  - `half_open_tries: 0` write-sites to drop: ~186, 205, 280, 325, 387, 437; plus the
    carry-through read `entry.get("half_open_tries", 0)` at ~196.
  - Module docstring lines ~31–32 (the trial-count claim).
  - **Keep:** `CircuitState.HALF_OPEN` (~70), `_transition_to_half_open`, and the
    `is_tripped` HALF_OPEN branch returning `False` (the recovery path).
- Tests (must stay green, no behavioral edits): `tests/test_reliability_policy.py`
  (`test_half_open_allows_test_traffic` ~261), `tests/test_reliability_circuit.py`,
  `tests/test_reliability_policy_live.py` (`test_r4_recovery_after_cooldown`).

### Institutional Learnings

- circuit.py is **not** tracked by `monolith_budget.toml`, `complexity_budget.toml`, or
  `tests/fixtures/sloc_canary.py` — removal needs no budget/canary update (verified in review).
- Trip thresholds live in `policy.py` (`_ERROR_THRESHOLD_ENV`), untouched here. See
  memory `[[reliability-policy-circuit-facts]]`.

## Key Technical Decisions

- **Remove, don't complete:** cooldown-only recovery already matches v1 intent and runs
  today; the layer is unused/default-off, so trial-cap semantics are speculative (YAGNI).
- **Keep the HALF_OPEN label:** ripping out the enum/transition would be a larger, riskier
  change to a tested state machine for zero behavioral gain.
- **Lazy state-field removal:** stop writing `half_open_tries`; rely on `.get(..., 0)`
  readers for backward compatibility — no migration code.

## Open Questions

### Resolved During Planning
- Migration for the state field → lazy stop-writing (review-confirmed safe).
- Test impact → no behavioral-assertion edits needed (review-confirmed no test asserts the cap).
- Budget/canary → none required (circuit.py untracked).

### Deferred to Implementation
- Exact line numbers will shift as deletions land — locate symbols by name, not line.

## Implementation Units

- [ ] **Unit 1: Delete the dead limiter surface + state field (circuit.py)**

**Goal:** Remove `_increment_half_open_try`, `_half_open_tries`, `_DEFAULT_HALF_OPEN_TRIES`,
the `…CIRCUIT_HALF_OPEN_TRIES` env var, and every `half_open_tries` state write/read.

**Requirements:** R1, R4

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/publishing/reliability/circuit.py`

**Approach:**
- Delete the three dead symbols wholesale (the only reads of `half_open_tries` live inside
  `_increment_half_open_try`, so they go with it).
- Drop `"half_open_tries": 0` from all state-construction dicts and the
  `entry.get("half_open_tries", 0)` carry-through. Leave every other state key intact.
- Do not touch `is_tripped`, `_transition_to_half_open`, `CircuitState`, `trip`,
  `trip_on_error`, cooldown logic, or threshold logic beyond removing the dead field.

**Patterns to follow:** existing state-dict shape in circuit.py (just minus one key).

**Test scenarios:**
- Test expectation: none (pure dead-code removal, no behavioral change). Safety net is the
  unchanged reliability suite — see Verification.

**Verification:**
- `grep -rn "_increment_half_open_try\|_half_open_tries\|HALF_OPEN_TRIES\|half_open_tries"`
  over the **repo root** (not just `src/` — confirms tests/webui are clean too) returns nothing.
- `pytest tests/test_reliability_circuit.py tests/test_reliability_policy.py
  tests/test_reliability_policy_live.py` passes with no edits to behavioral assertions.
  (`test_half_open_allows_test_traffic` exercises the kept recovery path — it stays green
  because `is_tripped` returning `False` in HALF_OPEN is unchanged.)

- [ ] **Unit 2: Correct the docstring + recovery comment (circuit.py)**

**Goal:** Make the documentation match reality — cooldown-only recovery, no trial cap.

**Requirements:** R2/R5

**Dependencies:** Unit 1 (so the docs describe the post-removal state)

**Files:**
- Modify: `src/backlink_publisher/publishing/reliability/circuit.py`

**Approach:**
- Reword **all four** "limited traffic / trial count" claims (circuit.py ~29, ~32, ~220,
  ~241) to state: after cooldown the circuit enters HALF_OPEN and allows traffic through
  to test recovery, with **no trial-count limiting**. Remove the
  `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` mention entirely.

**Patterns to follow:** existing docstring tone in circuit.py.

**Test scenarios:**
- Test expectation: none (documentation/comment only).

**Verification:**
- `grep -in "trial\|limited traffic\|HALF_OPEN_TRIES"` on circuit.py shows no claim of a
  half-open trial count or the removed env var.
- `python -m py_compile` clean.

## System-Wide Impact

- **Interaction graph:** internal to circuit.py; `is_tripped`/`trip` call sites in
  `policy.py` are unaffected (they never referenced the limiter).
- **State lifecycle:** dropping `half_open_tries` from written state is backward-safe via
  `.get(..., 0)` readers; no migration. Existing on-disk state files with the key are
  simply ignored.
- **Unchanged invariants:** trip thresholds, cooldown duration, HALF_OPEN transition +
  allow-through recovery, fail-CLOSED on corrupt state, and the default-off policy flag
  all remain exactly as-is.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Accidentally removing the wired HALF_OPEN transition (recovery) | Scope explicitly keeps `is_tripped`/`_transition_to_half_open`; verification re-runs `test_half_open_allows_test_traffic` + the R4 recovery test unchanged. |
| Missing a `half_open_tries` write-site | Final grep success criterion catches any leftover reference. |
| Hidden reader of the state field elsewhere | Review confirmed zero readers outside the deleted limiter (no webui/status/serializer use). |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-03-circuit-half-open-limiter-cleanup-requirements.md](docs/brainstorms/2026-06-03-circuit-half-open-limiter-cleanup-requirements.md)
- Related code: `publishing/reliability/circuit.py`, `tests/test_reliability_policy.py::test_half_open_allows_test_traffic`
- Related: plan `2026-06-03-007` (where this was discovered), plan `2026-05-28-001` (v1 "half-open deferred")
