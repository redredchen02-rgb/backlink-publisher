---
date: 2026-06-15
topic: publish-reliability-iteration
---

# Publish Reliability Iteration

## Problem Frame

The execution layer (40 adapters, circuit breaker, retry, liveness loop) is mature but has
two classes of reliability gap that compound on each other:

- **Success-rate killers** — transient platform errors (429/5xx) fail the publish outright
  instead of degrading to a same-platform fallback adapter or being safely retried. This
  silently loses backlinks that *could* have published.
- **Observability blind spots** — liveness recheck covers only ~5% of published links
  (88/1726), browser-tier selector drift has no CI/scheduled detection, and real-platform
  error→exception mapping has never been verified against a live target. We cannot prove
  whether a fix moved the success rate, because we cannot see the baseline.

These two run as **parallel tracks, staged** (operator decision): Track A raises the
success rate; Track B makes the success rate measurable so Track A's impact is provable.

## Tracks at a Glance

| Track | Goal | Why it matters | First stage |
|---|---|---|---|
| A — Success-rate lever | Stop losing publishable backlinks on transient errors | Direct lift to publish success | A1 transient fallback |
| B — Observability baseline | Make real success/strip rates visible & trustworthy | Without it, Track A's gain is unprovable | B1 liveness coverage |

## Requirements

**Track A — Transient-error resilience (success-rate lever)**

- R1. On a transient error (429, and 5xx where safe), the dispatch chain MUST attempt the
  next same-platform fallback adapter (e.g. Medium API → Brave → Browser) instead of
  propagating immediately. Today only `DependencyError` falls through;
  `ExternalServiceError` propagates (`_registry_dispatch.py:78–130`).
- R2. Fallback on transient errors MUST preserve the existing duplicate-publish safety: a
  fallback or retry must never create a second live link when the first attempt may have
  already succeeded. Where idempotency cannot be guaranteed, the safe choice is to NOT
  retry/fallback and surface the ambiguity.
- R3. Define per-error-class behavior explicitly: which errors retry-in-place, which fall
  back to the next adapter, which fail immediately. Replace today's implicit "429-only,
  5xx never" rule (`adapters/retry.py`) with a documented policy. **5xx defaults to
  fail-fast; a platform is only retried/fallen-back on 5xx after it is explicitly added to
  an idempotency-safe whitelist** (per-platform, evidence-based — no blanket relaxation).
- R4. Fallback/retry decisions MUST emit observability events (extend
  `reliability/events.py`) so operators can see how often a fallback saved or failed a
  publish.

**Track B — Observability baseline (make success measurable)**

- R5. Raise liveness recheck coverage to **≥50% of all published links** (from the current
  ~5%), prioritizing links that feed success-rate / strip-rate stats, so the scorecard
  reflects real data rather than a small sample.
- R6. Browser-tier selector drift (Medium, Velog, Devto, Mastodon) MUST be detectable
  automatically — via CI and/or a scheduled smoke run — instead of relying on manual
  operator smoke tests. The 4 `tests/test_browser_publish_*.py` are currently
  `@pytest.mark.skip`.
- R7. Verify that real-platform 429 / 503 / ban / session-expiry responses surface as the
  intended typed exceptions (`ExternalServiceError` / `AuthExpiredError`) that trip the
  circuit, not as generic exceptions routed to the wrong outcome. Add integration coverage
  for the policy-enable seam (`_engine.py:237`) exercised through a real CLI chain, not
  only direct unit calls.
- R8. Define and surface a single success-rate metric (per-channel publish success % over
  a window) that both tracks move, so improvement is provable end-to-end.

**Track C — Cleanup (opportunistic, low cost)**

- R9. Remove the unwired HALF_OPEN trial limiter dead code and its misleading
  `BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES` env var documentation
  (`reliability/circuit.py`), per the existing
  `2026-06-03-circuit-half-open-limiter-cleanup` requirements.

## Success Criteria

- A transient 429/5xx on an API adapter results in a successful publish via fallback (or a
  safe, documented no-retry) — demonstrated end-to-end, not just unit-tested.
- Publish success rate (R8 metric) is computed from liveness data with materially higher
  coverage than 5%, so the number is trustworthy.
- A deliberately broken browser selector is caught by automation before a real publish run,
  not by an operator noticing failures.
- Real-platform error responses are confirmed to trip the circuit as designed (R7).
- No duplicate live backlinks are ever created by the new fallback/retry behavior (R2).

## Scope Boundaries

- NOT adding new platforms/adapters or flipping `dofollow="uncertain"` channels — this is
  reliability of existing channels only.
- NOT building a unified pooled HTTP client (A4) — current ~1–10 backlinks/run volume does
  not justify it; revisit only if volume scales to 100+/run.
- NOT enabling the Medium liveness active probe by default — that remains gated on anti-bot
  impact validation; in scope only as a data source for R5 if/when safe.
- NOT relaxing the duplicate-publish safety stance to chase success rate (R2 is a hard
  constraint, not a tunable).

## Key Decisions

- Run Track A and Track B in parallel, staged (operator decision 2026-06-15): A lifts
  success rate, B proves it. Stage 1 = R1 (transient fallback) + R5 (liveness coverage).
- Liveness coverage target = **≥50% of all published links** (operator decision
  2026-06-15) — the success-rate metric is only reported as trustworthy once this is met.
- 5xx handling = **default fail-fast, opt-in per-platform idempotency-safe whitelist**
  (operator decision 2026-06-15) — preserves R2 duplicate-publish safety.
- Duplicate-publish safety outranks success rate: when idempotency is unprovable, fail
  safe rather than retry (R2).
- Treat the existing `2026-06-03-circuit-half-open-limiter-cleanup` work as a small
  opportunistic cleanup folded into this iteration (R9), not a separate effort.

## Dependencies / Assumptions

- Reliability policy layer exists but is gated behind
  `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED` (default off) and its CLI seam is
  integration-untested — R7 depends on exercising it for real.
- A real target + live credentials (or a faithful stub that reproduces real HTTP error
  bodies) is needed to verify R7 and to grow R5 coverage meaningfully.

## Outstanding Questions

### Resolve Before Planning
- _(none — both resolved 2026-06-15: liveness target ≥50% overall; 5xx default fail-fast
  with per-platform idempotency-safe whitelist.)_

### Deferred to Planning
- [Affects R3][Needs research] Build the initial idempotency-safe whitelist: per platform,
  determine whether a 5xx can leave a partially-created post, to decide eligibility.
- [Affects R1][Technical] Does same-platform fallback belong in `_registry_dispatch.py`
  (chain walk) or in the reliability policy layer? Which transient classes trigger it?
- [Affects R6][Technical] CI vs scheduled-run for selector detection — can browser smoke
  tests run headless in CI, or do they require an attached Chrome (current skip reason)?
- [Affects R7][Needs research] Capture real 429/503/ban/session-expiry response shapes from
  at least one live platform to confirm exception mapping before trusting circuit
  thresholds.
- [Affects R8][Technical] Reuse the existing scorecard `live_pct` plumbing for the
  success-rate metric, or add a distinct publish-attempt-success metric from
  `reliability/events.py`?

## Next Steps
→ `/ce:plan` for structured implementation planning (no blocking questions remain).
