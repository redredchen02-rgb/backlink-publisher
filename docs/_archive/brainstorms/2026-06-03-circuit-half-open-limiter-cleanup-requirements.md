---
date: 2026-06-03
topic: circuit-half-open-limiter-cleanup
---

# Remove the Unwired HALF_OPEN Trial Limiter (keep cooldown-only recovery)

## Problem Frame

The circuit breaker (`publishing/reliability/circuit.py`) advertises a HALF_OPEN
**trial-count limiter** — `_increment_half_open_try`, the `half_open_tries` state
counter, the `_half_open_tries()` reader, `_DEFAULT_HALF_OPEN_TRIES`, the
`BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` env var, and a module docstring claiming
"Half-open trial count … (default 1)". **None of it is wired**: `_increment_half_open_try`
has zero callers in `src/` and `tests/`, and `half_open_tries` is initialized but never
incremented. So the env knob does nothing and the docstring describes a feature that
does not exist.

This is not a clean bug nor clean intentional design — it is an **incomplete feature**.
The original plan `2026-05-28-001` explicitly deferred half-open ("cooldown-only v1;
half-open deferred", "no half-open state"). A later Phase-3 change added HALF_OPEN
scaffolding but only connected the **state transition** (`is_tripped` transitions
OPEN→HALF_OPEN after cooldown and returns `False`, allowing traffic through), never the
trial cap.

Decision (confirmed): **remove the dead limiter scaffolding and keep cooldown-only
recovery** — which is what the code actually does today and what v1 intended. The whole
reliability layer is still default-off (`RELIABILITY_POLICY_ENABLED`) and has only just
been live-verified at the wiring level (plan `2026-06-03-007`); building full trial-cap
semantics for an unused layer is premature (YAGNI).

Discovered during the document-review of plan `2026-06-03-007`.

## What is dead vs. what works (do not confuse them)

| Element | Status | Action |
|---|---|---|
| `_increment_half_open_try` (circuit.py:396) | dead — zero callers | **remove** |
| `_half_open_tries()` (circuit.py:152) | dead — only read by the above | **remove** |
| `_DEFAULT_HALF_OPEN_TRIES` + `…CIRCUIT_HALF_OPEN_TRIES` env | dead — advertises a no-op knob | **remove** |
| `half_open_tries` state field (init/copy at 186/196/205) | dead — never incremented | **remove (planning: confirm on-disk-state safety)** |
| module docstring "Half-open trial count …" (circuit.py:32) | misleading | **fix** |
| `CircuitState.HALF_OPEN` enum + `_transition_to_half_open` + `is_tripped` HALF_OPEN→`False` | **WORKING + TESTED** (`test_half_open_allows_test_traffic`) — this IS the recovery mechanism | **keep, clarify comment** |

## Requirements

- R1. Remove the unwired trial-limiter surface: `_increment_half_open_try`,
  `_half_open_tries()`, `_DEFAULT_HALF_OPEN_TRIES`, and the
  `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` env var.
- R2. Remove the misleading "Half-open trial count … (default 1)" claim from the
  `circuit.py` module docstring; replace with an accurate description of cooldown-only
  recovery (OPEN → after cooldown → HALF_OPEN allows traffic through to test recovery,
  no trial cap).
- R3. Preserve the **observable recovery behavior** unchanged: a tripped circuit, after
  its cooldown, allows the next attempt through. `test_half_open_allows_test_traffic`
  (and the circuit-recovery assertions in `test_reliability_policy_live.py`) must still
  pass without modification to their behavioral expectations.
- R4. Remove the `half_open_tries` state field from circuit state construction once
  nothing reads it, confirming this does not break reading older on-disk state files.
  Note (from review): this touches **more than the limiter functions** — `'half_open_tries': 0`
  is written at ~7 sites (`trip`, `trip_on_error`, `_transition_to_half_open`,
  `reset_circuit`, and both `_get_state` branches: circuit.py ~186/196/205/280/325/387/437).
  Backward-compat is safe: `_get_state` reads via `entry.get('half_open_tries', 0)`, so
  older state files with the key are ignored and newer readers default missing keys → the
  lazy "stop writing it" option is correct and low-risk.
- R5. Fix the only **live** documentation of the removed knob: the `circuit.py` module
  docstring (line 32). Verified during review — neither `AGENTS.md` nor
  `gate-verdicts.md` mentions `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES`. The historical
  plan docs (`2026-06-03-007`, `2026-05-28-001`) are left as-is as historical record.

## Success Criteria

- `grep -r "_increment_half_open_try\|HALF_OPEN_TRIES\|_half_open_tries\|half_open_tries"`
  returns nothing in `src/` (the dead surface is gone).
- The full reliability suite (`test_reliability_circuit.py`, `test_reliability_policy.py`,
  `test_reliability_policy_live.py`) passes with no change to recovery-behavior assertions.
- No env var is documented that has no effect.
- Net negative SLOC on `circuit.py`. (Verified during review: `circuit.py` is **not**
  tracked by `monolith_budget.toml`, `complexity_budget.toml`, or
  `tests/fixtures/sloc_canary.py` — so no budget/canary update is required.)

## Scope Boundaries

- **Not** building full half-open trial-cap semantics (the deferred feature). If real
  trial-limiting is ever wanted, that is a separate, deliberately-designed effort.
- **Not** removing the `CircuitState.HALF_OPEN` enum or the `_transition_to_half_open`
  transition — that path is wired, tested, and is the actual cooldown recovery mechanism.
- **Not** changing trip thresholds, cooldown behavior, or the default-off policy flag.
- **Not** enabling the reliability policy layer.

## Key Decisions

- **Remove, don't complete**: cooldown-only recovery already matches the original v1
  intent and is what runs today; the layer is unused and default-off, so trial-cap
  semantics are speculative complexity (YAGNI on carrying cost).
- **Keep the HALF_OPEN state label**: ripping out the enum/transition would be a larger,
  riskier change to a tested state machine for no behavioral gain. Cooldown-only recovery
  is allowed to route through a HALF_OPEN label internally.

## Dependencies / Assumptions

- Assumes removing the `half_open_tries` key from newly-written state is backward-safe
  (older state files with the key are simply ignored; newer readers default missing keys).
  Planning should confirm the state read/merge path tolerates both.

## Outstanding Questions

Both prior questions were resolved during document-review and folded into the
requirements above:
- R4 migration → use the lazy "stop writing it" option (readers already default missing
  keys via `entry.get('half_open_tries', 0)`); no migration path needed.
- R3 → `test_half_open_allows_test_traffic` asserts **only** `is_tripped(...) is False`
  after `_transition_to_half_open`; no trial-cap assertion exists in any reliability test,
  so removing the limiter requires no test-expectation changes.

No blocking questions remain.

## Next Steps
→ `/ce:plan` for structured implementation planning (small, well-bounded refactor).
