# WebUI refresh-source inventory (2026-07-06)

Plan: `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md`, unit W1
(D15: "QueryClient defaultOptions is the shared foundation for W2/W3/W5/W6").

**Method:** `grep -rn "useQuery\|refetchInterval\|staleTime\|refetchOnWindowFocus" frontend/src`
plus manual reading of every page under `frontend/src/pages/` and
`frontend/src/router/index.ts` (17 routes, matching the plan's verification
target). Snapshot taken 2026-07-06 against `feat/w1-refresh-defaults` @
f43dda73 — re-verify before relying on these numbers later.

## Baseline before this unit

`frontend/src/main.ts` constructed `QueryClient` with **no `defaultOptions`
key at all**. Every page therefore silently inherited the TanStack Query v5
library defaults:

- `staleTime: 0` — every mount/focus/refetch-trigger considered the cached
  data instantly stale, so it always re-fetched.
- `refetchOnWindowFocus: true` — switching back to a browser tab always
  triggered a background refetch for every active query, with no way to tell
  from reading a page's file alone whether that page relied on the default or
  had ever considered the question.

This is what R1/D15 mean by "隐性预设": nothing in `main.ts` documented the
decision, and no single page was the source of truth for "does this query
refetch on focus" — you had to already know the library default to answer
that question for any page that didn't set the option explicitly.

## Change made in this unit

`main.ts` now sets, explicitly:

```ts
defaultOptions: {
  queries: {
    refetchOnWindowFocus: true, // kept ON, but now a documented decision
    staleTime: 30_000,          // was implicit 0
  },
},
```

`refetchOnWindowFocus` stays `true` at the global level — most pages here are
read-mostly dashboards that benefit from a focus-triggered refresh, and
flipping it off site-wide would be a silent behavior change bundled into a
"make it explicit" unit, which is out of scope. `staleTime` moves from
implicit `0` to an explicit `30_000` (same order of magnitude as
MonitorDashboard's own 30s poll), cutting redundant refetch traffic for
pages that don't override it, without materially staling any page's data.

Six edit-surface Settings queries (the ones whose `useQuery` data feeds a
`watch()` that hydrates a live editable form/textarea — see table below) now
set `refetchOnWindowFocus: false` explicitly at the query site. This makes
"closed" a real, checkable declaration — the guard test in
`frontend/src/__tests__/query-defaults.spec.ts` asserts it. **This does not
fix the Settings hydration-overwrite bug itself**: a refetch triggered by
something other than window focus (e.g. a cache invalidation from a sibling
mutation) still rewrites the editable field via the existing `watch()`. That
dirty-aware fix (per-card dirty tracking, route-leave guard) is W2's scope,
not this unit's — this unit only builds the foundation W2 stands on.

## Per-route inventory (17 routes)

| Route | Page | Query keys | Refetch behavior | Notes |
|---|---|---|---|---|
| `/` | `Publish/PublishWorkbench.vue` | — (no `useQuery`) | manual `setTimeout` poll chain for soft-publish progress (`softTimer`), not TanStack-driven | not an edit surface for settings data |
| `/monitor` | `Monitor/MonitorDashboard.vue` | `['monitor-summary']` | `refetchInterval: 30_000` (explicit, `keepPreviousData` so ticks don't flash loading) | poll, not focus-driven; already fully explicit before this unit |
| `/history` | `History/HistoryPage.vue` | `QKEY` (history list) | inherits site default (30s staleTime, focus refetch on) | read + bulk-delete surface, not an edit-hydration surface (W4/W5 territory) |
| `/drafts` | `Drafts/DraftsPage.vue` | `QKEY` (drafts list) | inherits site default | same shape as History |
| `/sites` | `Sites/SitesPage.vue` | `SITES_KEY`, `WIDGETS_KEY` | inherit site default | two independent queries, neither feeds an edit-hydration watcher |
| `/schedule` | `Schedule/SchedulePage.vue` | `['schedule']` | `refetchOnWindowFocus: true` (already explicit pre-unit, with a code comment about resilience to a future global-default change) | read-only calendar view; explicit override kept as-is |
| `/batch-campaign` | `BatchCampaign/BatchCampaignPage.vue` | `['campaigns', 'form']` | inherits site default | form *options* (choices), not a user-typed edit surface |
| `/settings` | `Settings/SettingsPage.vue` + 8 card components | see table below | **6 queries now `refetchOnWindowFocus: false`**, rest inherit site default | primary edit surface; see breakdown below |
| `/pr-queue` | `PrQueue/PrQueuePage.vue` | — (no `useQuery`) | plain `onMounted(load)` + manual `fetchPrQueue()`, no auto-refresh of any kind | never refetches on its own; out of TanStack's refresh model entirely |
| `/survival` | `SurvivalDashboard/SurvivalDashboardPage.vue` | — (no `useQuery`) | plain `onMounted(load)`, no auto-refresh | same shape as PrQueue |
| `/optimization-status` | `OptimizationStatus/OptimizationStatusPage.vue` | — (no `useQuery`) | plain `onMounted(load)`, no auto-refresh | same shape as PrQueue |
| `/equity-ledger` | `EquityLedger/EquityLedgerPage.vue` | — (no `useQuery`) | plain `onMounted(load)`, no auto-refresh | same shape as PrQueue |
| `/keep-alive` | `KeepAlive/KeepAlivePage.vue` | — (no `useQuery`) | manual `setTimeout(poll, 2000)` job pollers (`recheckTimer`, `republishTimer`), not TanStack-driven | 2s job-poll pattern named in the plan's Approach step |
| `/campaign/:campaignId` | `CampaignProgress/CampaignProgressPage.vue` | — (no `useQuery`) | manual `setTimeout(doPoll, 2000)` job poller (`pollTimer`) | same 2s job-poll pattern as KeepAlive |
| `/error-reports` | `ErrorReports/ErrorReportsPage.vue` | inline key inside `useQuery({...})` | inherits site default | read-only list |
| `/error-reports/:id` | `ErrorReports/ErrorReportDetailPage.vue` | inline key inside `useQuery({...})` | inherits site default | read-only detail |
| `/:pathMatch(.*)*` | `NotFound.vue` | — | n/a | static page |

**Job-poll observation:** the plan's Approach step names "CampaignProgress /
KeepAlive 2s job pollers" — confirmed both use hand-rolled
`setTimeout(fn, 2000)` chains, entirely outside TanStack Query's refetch
model (no `useQuery`/`refetchInterval` involved). Unifying these three
poll idioms (TanStack `refetchInterval` for Monitor, manual 2s `setTimeout`
chains for job progress, and legacy Jinja's own polling) is explicitly
deferred to a separate task per the plan ("job-poll 三套模式統一抽象",
Deferred to Separate Tasks) — **not touched in this unit**.

**Four pages have no `useQuery` at all** (PrQueue, SurvivalDashboard,
OptimizationStatus, EquityLedger): they fetch once via `onMounted(load)` and
never refresh themselves — no focus refetch, no poll, no staleTime concept
applies. This is worth flagging for future units (e.g. W9's command-palette
work or a future consistency pass) since it means these four pages can go
stale indefinitely with zero background refresh, but changing that is out of
scope for W1 (which only makes existing refresh behavior explicit, not adds
new refresh behavior).

## Settings page breakdown (the primary edit surface)

| Component | Query key | Hydrates | `refetchOnWindowFocus` after this unit | Edit surface? |
|---|---|---|---|---|
| `SettingsPage.vue` | `['settings', 'keywords']` | `keywordEdits` (textarea per domain) | **`false`** (was: inherits implicit `true`) | yes |
| `SettingsPage.vue` | `['settings', 'schedule']` | `scheduleForm` (cadence fields) | **`false`** | yes |
| `BlogIdsCard.vue` | `['settings', 'blog-ids']` | `rows` (domain/blog_id pairs) | **`false`** | yes |
| `BloggerCard.vue` | `['settings', 'blogger-status']` | `form.client_id` | **`false`** | yes |
| `ChannelBindingCard.vue` | `['settings', 'channel-forms']` | `edits` (per-slug field map) | **`false`** | yes |
| `ChannelBindingCard.vue` | `['settings', 'channels']` | (bound/identity badges only — read display) | inherits site default (`true`) | no |
| `LlmSettingsCard.vue` | `['settings', 'llm']` | `form` (endpoint/api_key/model/prompts/…) | **`false`** | yes |
| `NotionCard.vue` | `['settings', 'notion-status']` | `form.database_id` | **`false`** | yes |
| `MediumCard.vue` | `['settings', 'medium-status']` | (browser/oauth status only — actions, no editable field) | inherits site default | no |
| `VelogCard.vue` | `['settings', 'velog-status']` | (status display only) | inherits site default | no |
| `ChannelsCard.vue` | `['settings', 'channels']` | (status display only) | inherits site default | no |
| `SettingsSidebar.vue` | `['settings', 'channels']` | (nav badges only) | inherits site default | no |

Six queries (across 5 files) qualify as "edit surfaces" — a `useQuery` whose
data is consumed by a `watch()` that writes into a `reactive`/`ref` bound to a
user-facing input — and all six now carry `refetchOnWindowFocus: false`
explicitly. This list, and the guard test that enforces it
(`frontend/src/__tests__/query-defaults.spec.ts`), is the "地基" W2 builds its
dirty-aware hydration fix on: W2 does not need to re-derive which queries are
edit surfaces, it can read this table.

## Verification performed

- `refetchOnWindowFocus` was **not** silently turned off site-wide — it
  remains `true` at the global level and is only `false` where explicitly
  named above.
- All 17 routes accounted for above.
- Guard-test red path verified by hand: temporarily removing the
  `defaultOptions` block from `main.ts` turns the first
  `query-defaults.spec.ts` test red (confirmed locally, then reverted — see
  that file's test description for the exact assertion). The
  `refetchOnWindowFocus: false` presence check was verified the same way for
  the edit-surface file list.
- **Not yet done** (left for whoever does an interactive pass, e.g. during W2
  code review): a live manual blur/focus check against the dev server
  confirming no network tab activity for the keyword-pool query on window
  refocus. The source-level guarantee (`refetchOnWindowFocus: false` at the
  six query sites, enforced by the guard test) is what this unit actually
  verified; a live browser confirmation would be corroborating, not load-bearing.
