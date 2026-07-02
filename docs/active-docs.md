# Active planning docs (post-convergence keep-set)

> **Refreshed 2026-07-02 (E1).** This roster was stale — it still described the
> 2026-06-18 v0.5.0 convergence as the current frontier, missing 13 plans that
> landed since (2026-06-22 through 2026-07-01). Numbers/status on this page go
> stale fast; treat `status:` frontmatter in the actual files under
> `docs/plans/` and `docs/brainstorms/` as ground truth, and this file as a
> cached index. To regenerate the plan table yourself:
>
> ```bash
> for f in docs/plans/*.md; do grep -H "^status:" "$f"; done
> ```

Single canonical list of the **live / in-flight** planning docs. Everything not
listed here was archived under `docs/_archive/{plans,brainstorms}/` and is
recoverable via git history.

This is a flat roster, not a navigation tool: filename · status · one line. When a
doc ships/parks, update its status here so "what's still in flight" stays legible.
Status vocabulary is `active` / `completed` / `shipped` / `parked` only.

## Plans (`docs/plans/`)

| File | Status | What |
|---|---|---|
| `2026-06-30-001-opt-phase3-post-v050-iteration-plan.md` | **active** | Phase 3 post-v0.5.0 optimization iteration (Sprints A-E; this file's own E1 unit did this refresh) |
| `2026-06-15-003-feat-referral-attribution-loop-plan.md` | parked · **tombstone** | short-link 302 — do-not-revive (destroys dofollow; see PR #6) |
| `2026-06-16-004-feat-v050-convergence-throughput-trust-plan.md` | shipped | v0.5.0 throughput mainline (enforce / catalog / runs-resume) |
| `2026-06-17-001-feat-webui-console-redesign-plan.md` | shipped | dark-console WebUI redesign |
| `2026-06-18-001-feat-v050-core-convergence-plan.md` | shipped | v0.5.0 core convergence (Track A + governance closeout) |
| `2026-06-18-002-refactor-webui-frontend-backend-separation-plan.md` | completed | WebUI split into pure JSON API + Vue 3 SPA (single source, single deploy) |
| `2026-06-22-001-refactor-embeddable-sdk-extraction-plan.md` | completed | Embeddable SDK extraction — `import backlink_publisher` in-process pipeline |
| `2026-06-22-002-refactor-spa-design-system-refinement-plan.md` | completed | Vue SPA design-system token/UX refinement |
| `2026-06-22-003-refactor-parallel-safe-optimization-lanes-plan.md` | completed | Parallel-safe optimization lanes |
| `2026-06-23-001-feat-history-published-url-column-plan.md` | completed | Clickable published-URL column on History page |
| `2026-06-23-002-release-v0.5.0-prep-plan.md` | completed | v0.5.0 release prep |
| `2026-06-23-003-feat-preview-edit-before-publish-plan.md` | completed | Preview & edit step before publish |
| `2026-06-23-004-ops-staging-smoke-test-runbook-plan.md` | completed | Staging smoke-test runbook |
| `2026-06-23-005-opt-phase2-mypy-spray-tests-plan.md` | completed | Phase 2 optimization: mypy strict, spray budget, test splits, exception audit |
| `2026-06-24-001-fix-empty-url-false-green-sdk-u8-plan.md` | completed | Empty-URL false-green fix + SDK Unit 8 completion |
| `2026-06-24-002-refactor-codebase-decoupling-plan.md` | completed | Codebase decoupling — complexity, boundary & CLI structure |
| `2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md` | completed | WebUI dark/light theme + homepage nav + layout consistency cleanup |

> Not present in this worktree at refresh time but known to exist on a sibling
> branch/worktree: `2026-07-01-002-feat-frontend-error-reporting-plan.md`
> (active, deepened 2026-07-01 — see the "Concurrent Plan Coordination"
> section of `2026-06-30-001-...-plan.md`). Re-check `docs/plans/` for it (and
> for any other concurrent plan) before starting new Phase 1-N work — this
> note is a snapshot, not a guarantee.

## Brainstorms / requirements (`docs/brainstorms/`)

| File | Status | What |
|---|---|---|
| `2026-07-01-phase3-signal-integrity-hardening-requirements.md` | active | Requirements feeding the active `2026-06-30-001` Phase 3 plan (R1-R7 deepening notes) |
| `2026-06-24-001-codebase-decoupling-requirements.md` | reference (shipped) | Requirements behind the shipped `2026-06-24-002` codebase-decoupling plan |
| `2026-06-22-embeddable-sdk-extraction-requirements.md` | reference (shipped) | Requirements behind the shipped `2026-06-22-001` SDK-extraction plan |
| `2026-06-18-v050-core-convergence-requirements.md` | reference (v0.5.0 shipped) | convergence requirements; still holds R5 + R1/U1→v0.5.1 deferral details |
| `2026-06-17-webui-console-redesign-requirements.md` | reference (shipped) | console redesign requirements |
| `2026-06-05-config-driven-lightweight-adapters-requirements.md` | reference | R1 catalog/config-driven adapter mechanism |
| `2026-06-01-seo-outcome-indexability-loop-requirements.md` | deferred (R5) | indexability→ledger bridge; resume trigger: blocked ≥5 or a dofollow channel ≥10% |
| `2026-06-15-referral-attribution-loop-requirements.md` | parked · **tombstone** | superseded by channel-level GA4 referral MVP (PR #6) |

> Note: the v0.5.0 convergence shipped via PR #40-#44 (UI consistency, drafts +
> monitor_hub fixes, doc archival, release cut + tag `v0.5.0`). Since then,
> 13 further plans (2026-06-22 through 2026-07-01) shipped/completed in
> sequence, and Phase 3 (`2026-06-30-001`) is the current active mainline.
