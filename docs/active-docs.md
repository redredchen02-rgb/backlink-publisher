# Active planning docs (post-convergence keep-set)

Single canonical list of the **live / in-flight** planning docs after the
2026-06-18 v0.5.0 convergence (R9). Everything not listed here was archived under
`docs/_archive/{plans,brainstorms}/` and is recoverable via git history.

This is a flat roster, not a navigation tool: filename · status · one line. When a
doc ships/parks, update its status here so "what's still in flight" stays legible.

## Plans (`docs/plans/`)

| File | Status | What |
|---|---|---|
| `2026-06-16-004-feat-v050-convergence-throughput-trust-plan.md` | shipped (v0.5.0) | v0.5.0 throughput mainline (enforce / catalog / runs-resume); Unit 6 R1 dofollow expansion → v0.5.1 |
| `2026-06-17-001-feat-webui-console-redesign-plan.md` | shipped (v0.5.0) | dark-console WebUI redesign (7/7 units) |
| `2026-06-18-001-feat-v050-core-convergence-plan.md` | shipped (v0.5.0) | this convergence (Track A + governance); U1 dofollow flip → v0.5.1 |
| `2026-06-15-003-feat-referral-attribution-loop-plan.md` | parked · **tombstone** | short-link 302 — do-not-revive (destroys dofollow; see PR #6) |

## Brainstorms / requirements (`docs/brainstorms/`)

| File | Status | What |
|---|---|---|
| `2026-06-18-v050-core-convergence-requirements.md` | reference (v0.5.0 shipped) | convergence requirements; still holds R5 + R1/U1→v0.5.1 deferral details |
| `2026-06-17-webui-console-redesign-requirements.md` | shipped (v0.5.0) | console redesign requirements |
| `2026-06-05-config-driven-lightweight-adapters-requirements.md` | reference | R1 catalog/config-driven adapter mechanism |
| `2026-06-01-seo-outcome-indexability-loop-requirements.md` | deferred (R5) | indexability→ledger bridge; resume trigger: blocked ≥5 or a dofollow channel ≥10% |
| `2026-06-15-referral-attribution-loop-requirements.md` | parked · **tombstone** | superseded by channel-level GA4 referral MVP (PR #6) |

> Note: the v0.5.0 convergence shipped via PR #40–#44 (UI consistency, drafts +
> monitor_hub fixes, doc archival, release cut + tag `v0.5.0`). The only carried
> remainder is R1/U1 (dofollow canary flip → v0.5.1, operator-gated).
