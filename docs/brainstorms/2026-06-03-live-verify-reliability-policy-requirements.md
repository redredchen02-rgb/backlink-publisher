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

The 20 unit tests in `tests/test_reliability_policy.py` already set the flag to `1`
and exercise the policy-active path of `publish_with_policy` directly — **including
non-browser-tier platforms** (`test_policy_applies_to_all_platforms`,
`test_non_browser_tier_dispatches_through_closed_circuit`). So the policy *behaviors*
(R2–R5) are already covered at the unit level. What is genuinely untested is narrower:
the **call-site branch selection** in the real CLI pipeline —
`if policy_enabled(): publish_with_policy(...) else: adapter_publish(...)` at
`_engine.py:237` / `_resume.py:325` — plus the late re-import seam that resolves these
symbols from the `publish_backlinks` namespace. That branch has never executed with the
flag flipped through the real `seeds.jsonl → publish-backlinks` chain. **That seam, not
the policy internals, is the residual gap.**

Scope decision (confirmed): **full-chain run against a controlled stub adapter** — no
external network, no credentials, no footprint. A real outbound publish is explicitly
out of scope for this verification.

## Requirements

**Activation path (primary risk — the only genuinely untested surface)**
- R1. A `publish-backlinks` run with `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`
  must route dispatch through `publish_with_policy` (not the direct `adapter_publish`
  branch). The same run with the flag unset must remain a transparent passthrough.

**Policy behaviors observed end-to-end (flag on)**
- R2. **Health gate (browser-tier only)** — for a browser-tier platform (`velog`,
  `medium`, `mastodon`) whose `channel_status` is not `bound`, dispatch yields a
  `skipped_policy` result and never reaches the adapter. The gate is intentionally
  scoped to browser-tier in `policy.py`; non-browser platforms skip it and fall through
  to the circuit check (this is why R6 below excludes R2).
- R3. **Circuit breaker trip → OPEN** — the circuit trips on **raised typed exceptions**
  (`ExternalServiceError` / `AuthExpiredError`), not on a returned HTTP status. Most
  paths trip only after a consecutive-failure threshold (default 5 errors / 3 auth;
  immediate trip only on a ban signal). The harness must therefore raise the typed
  exception enough times, or lower the threshold env
  (`BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD`), to drive the circuit OPEN — after
  which a subsequent attempt on the same platform yields `skipped_circuit_open` without
  dispatching.
- R4. **HALF_OPEN** — after a tripped circuit, the HALF_OPEN trial path is exercised:
  one trial is allowed; trials beyond the limit yield `skipped_circuit_open`.
- R5. **Observability events** — `publish_attempt` events are emitted for each outcome
  (at minimum `success` and one error outcome) with the expected fields
  (`platform`, `outcome`, `duration_ms`).

**Uniform coverage**
- R6. At least one of **R3 / R4 / R5** (the genuinely all-adapter behaviors) must run
  on a **non-browser-tier** platform, confirming the Stage 1 extension is live, not
  browser-only. R2 is **excluded** here: the health gate is browser-tier-only by
  design, so it is unobservable — and would be vacuously "passing" — on a non-browser
  platform.

## Success Criteria
- The artifact must include a **discriminating assertion for R1**: a spy/probe that
  fails if dispatch took the `else: adapter_publish` branch instead of
  `publish_with_policy`. It must exercise the real `_engine.py` / `_resume.py` call-site
  seam — calling `publish_with_policy` directly (the existing unit-test pattern)
  collapses the probe back into a unit test and does **not** satisfy R1.
- R2–R5 are demonstrated with captured evidence (result statuses + emitted event log
  lines) as regression checks layered on top of the R1 seam assertion — not as the
  primary risk being retired.
- The gate verdict for this probe is recorded as `GO` (probes are exempt from the
  R16 falsification gate, but a verdict line keeps the audit trail consistent).
- No change to default behavior: flag-off passthrough is unaffected.

## Scope Boundaries
- No real outbound publish to any external platform (no credentials, no footprint).
- No new policy behavior, no changes to `policy.py` logic — this is verification only.
  If verification surfaces a genuine bug, that becomes a separate fix, not part of this.
- Not a load/throttle/timing test — correctness of the enforce path only.
- Does not flip the default. The flag stays default-off after verification.
- This probe retires only the **wiring / branch-selection risk**. It does NOT retire
  real-platform error-mapping fidelity — e.g. whether a real platform's 429 / 503 / ban
  or session-expiry surfaces as the typed exceptions the circuit expects, vs a generic
  `Exception` that the code routes to `Outcome.TRANSIENT` and does **not** trip. A stub
  cannot reach that path; it remains an open risk (see Deferred to Planning).

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
  uniform-coverage check (verifying R3/R4/R5 there — not R2).
- [Affects Scope][Needs research] Real-platform error-mapping fidelity: do real
  429/503/ban/session-expiry responses actually surface as `ExternalServiceError` /
  `AuthExpiredError` (which trip the circuit), or as a generic `Exception` (routed to
  `Outcome.TRANSIENT`, no trip)? Out of scope for this stub probe; worth a follow-up
  when a bound channel + credentials exist.

## Next Steps
→ `/ce:plan` for structured implementation planning (small; the deferred questions are
all answerable from repo context during planning).
