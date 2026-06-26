# Vue 3 SPA Migration Roadmap

> Last updated: 2026-06-26

## Current State

| Frontend | Technology | JS/Vue Files | Status |
|---|---|---|---|
| **Old static JS** | Native ES modules + Jinja2 | 22 `.js` files | Active |
| **Vue 3 SPA** | Vue 3 + Pinia + Vue Router + TanStack Query | 26 `.vue` + 49 `.ts` | Active, incremental |

The two frontends coexist — the old Jinja-rendered pages serve routes like `/`, `/sites`, etc., while the SPA serves routes under `/app/*`.

## Migration Strategy

### Phase 1: Feature parity audit (current)
- [ ] Map every Jinja route to its SPA equivalent
- [ ] Identify gaps: features in old JS that lack SPA coverage

### Phase 2: Route-by-route migration
Priority order (impact + effort):

1. **`/settings`** → SPA primary (90% done — `SettingsPage.vue` exists)
2. **`/sites`** → SPA (`SitesPage.vue` exists, verify parity)
3. **`/monitor`** → SPA (`MonitorDashboard.vue` exists)
4. **`/drafts`** → SPA (`DraftsPage.vue` exists)
5. **`/schedule`** → SPA (`SchedulePage.vue` exists)
6. **`/history`** → SPA (`HistoryPage.vue` exists)
7. **`/` (publish workbench)** — existing SPA `PublishWorkbench.vue`
8. **Legacy Jinja-only pages** — migrate last

### Phase 3: Deprecate old static JS
- [ ] Once all Jinja routes redirect to SPA equivalents, remove `webui_app/static/js/` files
- [ ] Remove `window.__indexBootstrap` patterns from Jinja templates
- [ ] Remove unused Jinja templates

## Technical Notes

- **No build step for old JS**: served as native ES modules. SPA uses Vite build → `spa_dist/`.
- **Same CSS tokens**: both frontends share `tokens.css` for visual consistency.
- **API layer**: old frontend uses `lib/api.js` (`fetchJson`/`postJson`); SPA uses typed API clients in `frontend/src/api/`.
- **Auth/CSRF**: both read `<meta name="csrf-token">` via `readCsrf()`.
