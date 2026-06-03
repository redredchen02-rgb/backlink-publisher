---
date: 2026-06-03
topic: live-verify-reliability-policy
---

# Live Verification of the Reliability Policy Layer

## Problem Frame

The coordinated publish policy layer (health gate + circuit breaker + observability
events, plan `2026-05-28-001`) is fully shipped and wired into the real publish path
(`cli/publish_backlinks/_engine.py:237`, `cli/_resume.py:325`). It is gated behind
`BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1` (default off) — the PR #279
"observe → enforce" rollout posture, by design, not a defect.

The 20 unit tests in `tests/test_reliability_policy.py` all monkeypatch the env var
and call `publish_with_policy` **directly**. The `policy_enabled() == True` branch in
the real CLI pipeline has therefore never executed end-to-end with the flag actually
flipped. This is the one residual confidence gap: prove the enforce path fires through
the real `seeds.jsonl → publish-backlinks` chain — not the function in isolation.

Scope decision (confirmed): **full-chain run against a controlled stub adapter** — no
external network, no credentials, no footprint. A real outbound publish is explicitly
out of scope for this verification.

## Requirements

**Activation path**
- R1. A `publish-backlinks` run with `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`
  must route dispatch through `publish_with_policy` (not the direct `adapter_publish`
  branch). The same run with the flag unset must remain a transparent passthrough.

**Policy behaviors observed end-to-end (flag on)**
- R2. **Health gate** — a target whose `channel_status` is not `bound` yields a
  `skipped_policy` result and never reaches the adapter.
- R3. **Circuit breaker trip → OPEN** — a stub adapter returning a trip-worthy error
  (e.g. 503 / 429) trips the per-platform circuit; a subsequent attempt on the same
  platform yields `skipped_circuit_open` without dispatching.
- R4. **HALF_OPEN** — after a tripped circuit, the HALF_OPEN trial path is exercised:
  one trial is allowed; trials beyond the limit yield `skipped_circuit_open`.
- R5. **Observability events** — `publish_attempt` events are emitted for each outcome
  (at minimum `success` and one error outcome) with the expected fields
  (`platform`, `outcome`, `duration_ms`).

**Uniform coverage**
- R6. At least one verified behavior (R2–R5) must run on a **non-browser-tier**
  platform, confirming the Stage 1 "all adapters" extension is live, not browser-only.

## Success Criteria
- A single reproducible run (or a thin verification harness/test under the existing
  `real_*` marker convention) demonstrates R1–R6 with captured evidence
  (result statuses + emitted event log lines).
- The gate verdict for this probe is recorded as `GO` (probes are exempt from the
  R16 falsification gate, but a verdict line keeps the audit trail consistent).
- No change to default behavior: flag-off passthrough is unaffected.

## Scope Boundaries
- No real outbound publish to any external platform (no credentials, no footprint).
- No new policy behavior, no changes to `policy.py` logic — this is verification only.
  If verification surfaces a genuine bug, that becomes a separate fix, not part of this.
- Not a load/throttle/timing test — correctness of the enforce path only.
- Does not flip the default. The flag stays default-off after verification.

## Key Decisions
- **Stub adapter, full CLI chain**: chosen over real outbound publish because the
  owned target universe is tiny and footprint/credential risk is unjustified for a
  wiring-confidence check. The risk being retired is "does the enforce branch wire up
  correctly," which a stub fully exercises.
- **Treat as a probe, not a feature**: per gate-first (R16), pure verification is
  exempt from the GO gate; no brainstorm→plan→gate ceremony required to execute.

## Dependencies / Assumptions
- Assumes the existing test-isolation conftest (`real_*` markers, sandboxed config dir)
  is the right home for a harness if one is written, rather than a live operator run.
- Assumes circuit state persistence (flock-based, `circuit.py`) works in the test
  sandbox — verification must use a real (temp) config dir so circuit state round-trips.

## Outstanding Questions

### Deferred to Planning
- [Affects R1][Technical] Reproducible operator CLI invocation vs. a committed
  `real_*`-marked verification test — which is the durable artifact? (Lean: a test, so
  the enforce path stays covered against regression.)
- [Affects R3/R4][Technical] Cleanest way to inject a stub adapter that returns
  scripted outcomes through the real `adapter_publish` registry without touching
  `cli/*.py` (the R9 extension-readiness constraint forbids editing CLI/schema).
- [Affects R6][Technical] Which non-browser-tier platform is simplest to stub for the
  uniform-coverage check.

## Next Steps
→ `/ce:plan` for structured implementation planning (small; the deferred questions are
all answerable from repo context during planning).
