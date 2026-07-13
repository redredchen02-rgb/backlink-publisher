# frontend/ — SPA contributor guide

Conventions enforced by guard tests in `src/__tests__/` (component-adoption,
breakpoint-convention). Read alongside the repo-root AGENTS.md.

## Tables

Every list view renders through `src/components/DataTable.vue` (generic over
`T extends { id: string }` — map a stable string `id` onto rows if the API
lacks one). It embeds StateBlock (loading/empty/error), optional selection
(`selectable`), pagination (`total`/`limit`/`offset`), and row activation
(`rowActivate`) via two independent opt-in props: `rowKeyboardNav` for the
keyboard path (Enter on a focused row) and `rowClickActivate` for the mouse
path (click on a non-interactive cell). A page must set both to get both
interaction modes. Exemption: Health/HealthPage.vue (expandable drill-down +
dynamic panels) keeps the `.data-table` CSS convention with sr-only captions.

## Status pills vs info chips

- Status (has semantics: success/failure/progress) → `<StatusBadge :status>`
  or `<StatusBadge :tone :label>` for derived/boolean states. Never hand-roll
  `class="badge"` / `class="status" :data-status` / STATUS_COLORS maps.
- Non-status info pill (platform name, count) → global `.chip` class
  (app.css). Never declare page-local `.badge` styles.

## Feedback rule (spec 2026-07-13 A3)

- Data-fetch lifecycle (loading / empty / fetch error) → StateBlock
  (usually via DataTable).
- User-action outcomes (submit/save/publish success or failure) → toast via
  `useErrorToast` or an inline `role="alert"` element next to the control.
- Never hand-roll spinners; StateBlock owns loading treatment.

## Breakpoint

The only sanctioned max-width media query for page/style CSS is
`@media (max-width: 960px)` (desktop split-screen; mobile out of scope —
app.css block comment). The breakpoint-convention guard scans `src/pages` and
`src/styles` and fails any other literal there.

`src/layout/*` (AppShell.vue, SideNav.vue, TopBar.vue) is exempt from this
guard: the app shell's drawer/hamburger breakpoint is deliberately `1024px`,
mirroring the legacy drawer breakpoint at
`webui_app/static/css/global_nav.css:268`. Do not "fix" it to 960px — that
would change sidebar collapse behaviour in the 960-1024px range and break
legacy parity. This is temporary until Phase B retires the legacy shell, at
which point `src/layout/*` can be reconciled with the 960px convention.

## Copy

UI copy is Simplified Chinese (zh-CN). No Bootstrap classes — style with
tokens from `webui_app/static/css/tokens.css` via `var(--…)`.
