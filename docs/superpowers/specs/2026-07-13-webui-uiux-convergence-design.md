# WebUI UI/UX Convergence — Design Spec

- Date: 2026-07-13
- Status: approved (user-approved in session, pending implementation plan)
- Scope: Phase A (SPA consistency convergence) → Phase B (legacy migration finish)
- Out of scope: visual redesign of the token language ("Phase C") — explicitly deferred.

## Background / Problem

An audit of both frontend surfaces (2026-07-13) found the design foundation is healthy —
shared `webui_app/static/css/tokens.css` consumed by both Jinja and the Vue SPA, dark/light
themes, strong a11y (StateBlock four-state matrix, DataTable keyboard nav, aria-live toasts) —
but consistency has not converged and the strangler-fig migration has not been finished:

1. `DataTable` is used by only 2 pages; 10 pages hand-roll `<table>`
   (Operations, PrQueue, EquityLedger, Health, KeepAlive, CampaignProgress, Sites,
   OptimizationStatus, ErrorReports, Schedule). A guard test
   (`frontend/src/__tests__/data-table-adoption.spec.ts`) exists but tolerates the gap.
2. `StatusBadge` has 1 consumer; 13 pages hand-roll badge/pill/status markup.
3. Error/loading feedback has no single rule: StateBlock panels vs `useErrorToast` toasts
   are used ad hoc; `PublishWorkbench.vue` hand-rolls a spinner.
4. Breakpoint literals (e.g. `max-width: 960px`) are copy-pasted into per-page
   `<style>` blocks (`frontend/src/styles/app.css:113-123` documents the lack of a shared
   mechanism).
5. ~11 pages exist live in BOTH surfaces (Jinja twin + SPA page) with redirects
   documented-as-deferred (`/sites`, `/batch-campaign`, `/ce:history`, `/ce:health`, …),
   doubling maintenance and letting UX drift. Legacy assets still shipped: 22 static JS
   files, ~2,600 lines of CSS (`index.css` alone is 1,043 lines).

## Design

### Phase A — SPA consistency convergence (SPA side only: `frontend/` source, docs, and build config; no Python/Flask changes)

**A1. DataTable adoption.** Replace hand-rolled `<table>` in the 10 pages listed above with
the shared `DataTable` (selection, pagination, keyboard nav, a11y caption built in).
Afterwards flip `data-table-adoption.spec.ts` from a tolerance list to full enforcement so
regressions fail CI.

**A2. StatusBadge adoption.** Replace hand-rolled badge/pill/status markup in the 13
offending pages with `StatusBadge`. Where a needed variant is missing, extend
`StatusBadge` variants rather than letting pages write one-off classes. Add an adoption
guard test mirroring A1's.

**A3. Feedback rule.** Codify one rule and apply it everywhere:
- Data-fetch lifecycle (loading / empty / fetch error) → `StateBlock`.
- User-action outcomes (submit / save / publish success or failure) → toast via
  `useErrorToast`.
Replace the hand-rolled spinner in `PublishWorkbench.vue`. Document the rule in the
frontend AGENTS/README so future pages follow it.

**A4. Breakpoint convergence.** Extract copy-pasted breakpoint literals into one shared
mechanism. Two candidate implementations — shared utility class + commented anchor, or
`postcss-custom-media` — the implementation plan picks one after checking build-chain
impact. Success criterion: no page-level `<style>` re-declares the split-screen breakpoint
literal.

### Phase B — Migration finish (kill the twins)

**B1. Complete the redirects.** Wire the still-deferred Flask routes (`/sites`,
`/batch-campaign`, `/ce:history`, `/ce:health`, and any others found during planning) to
302 to their SPA pages, **porting the flash-message query-string contracts** that caused
the original deferral. Each route gets tests for the flash contract before the route is
changed (test-first).

**B2. Retire legacy assets.** Execute the existing roadmap Phase 3
(`docs/spa-migration-roadmap.md`): remove Jinja templates that have SPA twins, the 22
legacy static JS files, and ~2,600 lines of legacy CSS (all of `index.css` retires with
its page). The fate of LITE mode (`BACKLINK_PUBLISHER_SPA=0`) follows the roadmap
document; the implementation plan confirms it before deleting any fallback — no fallback
is removed on this spec's authority alone.

## Acceptance criteria

- All vitest + pytest suites green; `npm run build` output healthy; ruff/mypy clean.
- Both adoption guard tests (DataTable, StatusBadge) fully enforcing and green.
- After Phase B: retired routes respond 302 → SPA with flash-message behavior covered by
  tests.
- `tokens.css` visual language untouched (no redesign smuggled in).

## Risk management

- Each page swap is an independent small step; a broken swap affects one page and the
  effort can pause at any page boundary.
- B1's flash contract is the highest-risk item → tests written before route changes.
- This workspace may host concurrent sessions on the same directory/branch: verify
  `git status` before every commit and commit only files owned by this effort.
