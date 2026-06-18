# Active planning docs (post-convergence keep-set)

Single canonical list of the **live / in-flight** planning docs after the
2026-06-18 v0.5.0 convergence (R9). Everything not listed here was archived under
`docs/_archive/{plans,brainstorms}/` and is recoverable via git history.

This is a flat roster, not a navigation tool: filename · status · one line. When a
doc ships/parks, update its status here so "what's still in flight" stays legible.

## Plans (`docs/plans/`)

| File | Status | What |
|---|---|---|
| `2026-06-16-004-feat-v050-convergence-throughput-trust-plan.md` | active | v0.5.0 throughput mainline (enforce / catalog / runs-resume) |
| `2026-06-17-001-feat-webui-console-redesign-plan.md` | active | dark-console WebUI redesign |
| `2026-06-18-001-feat-v050-core-convergence-plan.md` | active | this convergence (Track A U2/U3/U4 shipped; lands via PR #40) |
| `2026-06-15-003-feat-referral-attribution-loop-plan.md` | parked · **tombstone** | short-link 302 — do-not-revive (destroys dofollow; see PR #6) |

## Brainstorms / requirements (`docs/brainstorms/`)

| File | Status | What |
|---|---|---|
| `2026-06-18-v050-core-convergence-requirements.md` | active | this convergence requirements (lands via PR #40) |
| `2026-06-17-webui-console-redesign-requirements.md` | active | console redesign requirements |
| `2026-06-05-config-driven-lightweight-adapters-requirements.md` | reference | R1 catalog/config-driven adapter mechanism |
| `2026-06-01-seo-outcome-indexability-loop-requirements.md` | deferred (R5) | indexability→ledger bridge; resume trigger: blocked ≥5 or a dofollow channel ≥10% |
| `2026-06-15-referral-attribution-loop-requirements.md` | parked · **tombstone** | superseded by channel-level GA4 referral MVP (PR #6) |

> Note: the two `2026-06-18` convergence docs land via PR #40 (branch
> `feat/v050-ui-consistency`); they are listed here for the post-merge surface.
