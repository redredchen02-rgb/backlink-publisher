# Vue 3 SPA Migration Roadmap

> Last updated: 2026-06-26 (R12 audit)

## Current State

| Frontend | Technology | JS/Vue Files | Status |
|---|---|---|---|
| **Old static JS** | Native ES modules + Jinja2 | 22 `.js` files | Active |
| **Vue 3 SPA** | Vue 3 + Pinia + Vue Router + TanStack Query | 26 `.vue` + 49 `.ts` | Active, incremental |

The two frontends coexist — the old Jinja-rendered pages serve routes like `/`, `/sites`, etc., while the SPA serves routes under `/app/*`. The SPA has **29 spec files** covering every page component and most stores/composables.

## Migration Strategy

### Phase 1: Feature parity audit ✅
- [x] Map every Jinja route to its SPA equivalent
- [x] Identify gaps: features in old JS that lack SPA coverage

### Phase 2: Route-by-route migration ✅
All priority routes now have SPA coverage with `.spec.ts` test files:

| Route | SPA Page | Tests |
|---|---|---|
| `/settings` | `SettingsPage.vue` (+ 8 sub-cards) | 9 spec files |
| `/sites` | `SitesPage.vue` | 1 spec file |
| `/monitor` | `MonitorDashboard.vue` | 1 spec file |
| `/drafts` | `DraftsPage.vue` | 1 spec file |
| `/schedule` | `SchedulePage.vue` | 1 spec file |
| `/history` | `HistoryPage.vue` | 1 spec file |
| `/` (publish) | `PublishWorkbench.vue` | 1 spec file |
| `/batch` | `BatchCampaignPage.vue` | 1 spec file |

**Remaining Jinja-only pages** (not yet migrated to SPA, served via legacy routes):
`health.html`, `equity_ledger.html`, `survival_dashboard.html`, `keep_alive.html`,
`pr_queue.html`, `optimization_status.html`, `pipeline_dashboard.html`,
`command_center.html`, `campaign_progress.html`, `result.html`,
`batch_campaign.html`.

### Phase 3: Deprecate old static JS (not started)
- [ ] Once all Jinja routes redirect to SPA equivalents, remove `webui_app/static/js/` files
- [ ] Remove `window.__indexBootstrap` patterns from Jinja templates
- [ ] Remove unused Jinja templates

## Technical Notes

- **No build step for old JS**: served as native ES modules. SPA uses Vite build → `spa_dist/`.
- **Same CSS tokens**: both frontends share `tokens.css` for visual consistency.
- **API layer**: old frontend uses `lib/api.js` (`fetchJson`/`postJson`); SPA uses typed API clients in `frontend/src/api/`.
- **Auth/CSRF**: both read `<meta name="csrf-token">` via `readCsrf()`.
