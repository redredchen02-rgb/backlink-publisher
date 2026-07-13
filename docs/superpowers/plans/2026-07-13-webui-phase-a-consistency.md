# WebUI Phase A — SPA Consistency Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge all SPA list pages onto the shared `DataTable` + `StatusBadge` components, codify the loading/error feedback rule, and lock the breakpoint convention — per spec `docs/superpowers/specs/2026-07-13-webui-uiux-convergence-design.md` (Phase A only).

**Architecture:** Strengthen the two shared components first (`DataTable` gains an opt-in `selectable` prop + click-to-activate rows; `StatusBadge` becomes self-styled and reactive — it currently emits Bootstrap `bg-*` classes that **no stylesheet defines** since Bootstrap was removed from the SPA, i.e. it renders unstyled today). Then migrate pages one task each, ratcheting guard-test tolerance lists down to zero.

**Tech Stack:** Vue 3.5 `<script setup>` + TypeScript, Vitest 4 + @vue/test-utils (jsdom), Vite 8 (no PostCSS pipeline), TanStack vue-query, tokens from `webui_app/static/css/tokens.css`.

## Global Constraints

- All changes live under `backlink-publisher/frontend/` (plus the new `frontend/AGENTS.md`). **No Python/Flask changes. No `tokens.css` changes.**
- All commands run from `backlink-publisher/frontend/`: `npm run test` (vitest run), `npm run typecheck`, `npm run build`.
- UI copy is Simplified Chinese (zh-CN), matching existing pages (`暂无数据`, `上一页`…).
- Never introduce Bootstrap utility classes (`bg-*`, `btn btn-sm`, `table table-sm`…) — style via CSS custom properties from tokens.css (`var(--success)` etc.).
- `DataTable` is generic over `T extends { id: string }` — rows without a natural string `id` must be mapped to add one (each page task states the mapping).
- Split-screen breakpoint literal is exactly `@media (max-width: 960px)` (app.css convention, Plan 2026-07-06-005 D12). Mobile is out of scope.
- Workspace hazard: another session may share this directory. Before every commit run `git status --porcelain` and stage ONLY the files this task touched.
- One commit per task, message prefix `feat(webui-a):`, `test(webui-a):` or `docs(webui-a):`.

---

### Task 1: DataTable — opt-in `selectable` + click-to-activate rows

**Files:**
- Modify: `frontend/src/components/DataTable.vue`
- Modify: `frontend/src/pages/History/HistoryPage.vue` (~line 500, DataTable call site)
- Modify: `frontend/src/pages/Drafts/DraftsPage.vue` (~line 169, DataTable call site)
- Test: `frontend/src/__tests__/data-table-selectable.spec.ts` (create)

**Interfaces:**
- Consumes: existing `DataTable` contract (props `items/loading/error/emptyText/caption/selected/total/limit/offset/disabled/rowClass/rowKeyboardNav`; emits `retry`, `update:selected`, `update:offset`, `rowActivate`; slots `#head`, `#row="{ row }"`).
- Produces: new prop `selectable?: boolean` (default `false`) — the `.col-select` `<th>/<td>` checkbox column renders **only** when `selectable` is true. New behavior: when `rowKeyboardNav` is true and `disabled` is false, a mouse click on a row emits `rowActivate: [T]`, unless the click originated inside `a, button, input, select, textarea, label`. All later page tasks rely on exactly this contract.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/data-table-selectable.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from '../components/DataTable.vue'

const items = [
  { id: 'a', name: '甲' },
  { id: 'b', name: '乙' },
]

function make(props: Record<string, unknown> = {}) {
  return mount(DataTable, {
    props: { items, ...props },
    slots: {
      head: '<th>名称</th>',
      row: `<template #row="{ row }"><td>{{ row.name }}</td></template>`,
    },
  })
}

describe('DataTable selectable prop', () => {
  it('hides the select column by default', () => {
    const w = make()
    expect(w.find('.col-select').exists()).toBe(false)
  })

  it('renders the select column when selectable', () => {
    const w = make({ selectable: true })
    expect(w.findAll('th.col-select')).toHaveLength(1)
    expect(w.findAll('td.col-select')).toHaveLength(items.length)
  })
})

describe('DataTable click-to-activate', () => {
  it('emits rowActivate on row click when rowKeyboardNav', async () => {
    const w = make({ rowKeyboardNav: true })
    await w.findAll('tbody tr')[0].trigger('click')
    expect(w.emitted('rowActivate')?.[0]).toEqual([items[0]])
  })

  it('does not emit rowActivate without rowKeyboardNav', async () => {
    const w = make()
    await w.findAll('tbody tr')[0].trigger('click')
    expect(w.emitted('rowActivate')).toBeUndefined()
  })

  it('does not emit rowActivate for clicks on nested interactive controls', async () => {
    const w = mount(DataTable, {
      props: { items, rowKeyboardNav: true },
      slots: {
        head: '<th>操作</th>',
        row: `<template #row="{ row }"><td><button type="button">编辑</button></td></template>`,
      },
    })
    await w.find('tbody tr button').trigger('click')
    expect(w.emitted('rowActivate')).toBeUndefined()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- data-table-selectable`
Expected: FAIL — "hides the select column by default" fails (column renders unconditionally today); click tests fail (no click handler).

- [ ] **Step 3: Implement in DataTable.vue**

Add to the props type (inside the existing `defineProps<{…}>`):

```ts
    /** Opt-in row-selection checkbox column. Off by default: most list pages are read-only. */
    selectable?: boolean
```

and to the `withDefaults` defaults object: `selectable: false,`.

Add the click handler next to `onRowKeydown` (reuse its nested-control guard idea):

```ts
function onRowClick(event: MouseEvent, row: T) {
  if (!props.rowKeyboardNav || props.disabled) return
  const target = event.target as HTMLElement | null
  if (target?.closest('a, button, input, select, textarea, label')) return
  emit('rowActivate', row)
}
```

Template changes:
- `<th class="col-select" …>` → add `v-if="selectable"`
- `<td class="col-select">` → add `v-if="selectable"`
- the `<tr v-for …>` gains `@click="onRowClick($event, row)"`

Then keep History/Drafts behavior identical by opting them in — add `selectable` to the `<DataTable` call sites in `HistoryPage.vue` (~line 500) and `DraftsPage.vue` (~line 169).

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- data-table` (runs new spec + existing adoption guard) then `npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git status --porcelain   # stage ONLY the 4 files below
git add frontend/src/components/DataTable.vue frontend/src/__tests__/data-table-selectable.spec.ts frontend/src/pages/History/HistoryPage.vue frontend/src/pages/Drafts/DraftsPage.vue
git commit -m "feat(webui-a): DataTable opt-in selectable column + click-to-activate rows"
```

---

### Task 2: StatusBadge v2 — self-styled, reactive, tone override, full status map

**Files:**
- Modify: `frontend/src/components/StatusBadge.vue` (rewrite, ~90 lines)
- Test: `frontend/src/__tests__/status-badge.spec.ts` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: props `status?: string | null`, `label?: string`, `tone?: Tone` where `type Tone = 'neutral' | 'primary' | 'success' | 'danger' | 'warning' | 'info' | 'dark'`. Rendering: `<span class="badge badge--<tone>" data-testid="status-badge">{text}</span>`, styles scoped in the component (no global classes needed). Resolution: explicit `tone` prop wins; else `status` looked up in MAP (case-insensitive); else neutral fallback with text `label || status || '未知'`. Reactive to prop changes (computed). Later tasks use: `<StatusBadge :status="row.status" />` and `<StatusBadge tone="success" label="存活" />`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/status-badge.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBadge from '../components/StatusBadge.vue'

describe('StatusBadge v2', () => {
  it('maps known status to tone class and zh text', () => {
    const w = mount(StatusBadge, { props: { status: 'running' } })
    expect(w.classes()).toContain('badge--primary')
    expect(w.text()).toBe('进行中')
  })

  it('supports new statuses added for page migrations', () => {
    for (const [status, tone] of [
      ['won', 'success'], ['lost', 'danger'], ['sent', 'primary'], ['draft', 'info'],
      ['open', 'danger'], ['acknowledged', 'warning'], ['resolved', 'success'],
      ['scheduled', 'info'], ['deleted', 'dark'],
    ] as const) {
      const w = mount(StatusBadge, { props: { status } })
      expect(w.classes(), status).toContain(`badge--${tone}`)
    }
  })

  it('tone prop overrides status mapping', () => {
    const w = mount(StatusBadge, { props: { tone: 'success', label: '存活' } })
    expect(w.classes()).toContain('badge--success')
    expect(w.text()).toBe('存活')
  })

  it('falls back to neutral for unknown status', () => {
    const w = mount(StatusBadge, { props: { status: 'weird_thing' } })
    expect(w.classes()).toContain('badge--neutral')
    expect(w.text()).toBe('weird_thing')
  })

  it('is reactive to status changes after mount', async () => {
    const w = mount(StatusBadge, { props: { status: 'pending' } })
    expect(w.classes()).toContain('badge--neutral')
    await w.setProps({ status: 'success' })
    expect(w.classes()).toContain('badge--success')
    expect(w.text()).toBe('成功')
  })

  it('never emits legacy Bootstrap classes', () => {
    const w = mount(StatusBadge, { props: { status: 'success' } })
    expect(w.classes().join(' ')).not.toMatch(/\bbg-/)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- status-badge`
Expected: FAIL — current component emits `bg-*` classes, has no `tone` prop, and resolves `style()` once at setup (non-reactive).

- [ ] **Step 3: Rewrite StatusBadge.vue**

```vue
<script setup lang="ts">
import { computed } from 'vue'

export type Tone = 'neutral' | 'primary' | 'success' | 'danger' | 'warning' | 'info' | 'dark'

const props = defineProps<{
  status?: string | null
  label?: string
  /** Explicit tone override — for boolean/derived badges where no status string exists. */
  tone?: Tone
}>()

const MAP: Record<string, { tone: Tone; text: string }> = {
  // operation statuses
  pending: { tone: 'neutral', text: '排队中' },
  running: { tone: 'primary', text: '进行中' },
  success: { tone: 'success', text: '成功' },
  failed: { tone: 'danger', text: '失败' },
  canceled: { tone: 'dark', text: '已取消' },
  // campaign / queue / batch statuses
  completed: { tone: 'success', text: '已完成' },
  draft_review: { tone: 'info', text: '待审核' },
  processing: { tone: 'primary', text: '处理中' },
  idle: { tone: 'neutral', text: '待处理' },
  skipped: { tone: 'warning', text: '已跳过' },
  // publish-history statuses
  published: { tone: 'success', text: '已发布' },
  drafted: { tone: 'info', text: '已草稿' },
  verified: { tone: 'success', text: '已验证' },
  unverified: { tone: 'warning', text: '未验证' },
  // pr-queue statuses (Phase A)
  draft: { tone: 'info', text: '草稿' },
  sent: { tone: 'primary', text: '已发送' },
  won: { tone: 'success', text: '已赢得' },
  lost: { tone: 'danger', text: '已失去' },
  // error-report statuses (Phase A)
  open: { tone: 'danger', text: '待处理' },
  acknowledged: { tone: 'warning', text: '已确认' },
  resolved: { tone: 'success', text: '已解决' },
  // drafts/history statuses (Phase A)
  scheduled: { tone: 'info', text: '已排程' },
  deleted: { tone: 'dark', text: '已删除' },
}

const resolved = computed<{ tone: Tone; text: string }>(() => {
  const key = props.status?.toLowerCase()
  const hit = key ? MAP[key] : undefined
  if (props.tone) return { tone: props.tone, text: props.label ?? hit?.text ?? props.status ?? '未知' }
  if (hit) return { tone: hit.tone, text: props.label ?? hit.text }
  return { tone: 'neutral', text: props.label || props.status || '未知' }
})
</script>

<template>
  <span class="badge" :class="`badge--${resolved.tone}`" data-testid="status-badge">{{
    resolved.text
  }}</span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  line-height: var(--leading-tight);
  white-space: nowrap;
}
.badge--neutral { background: var(--surface-overlay); color: var(--text-secondary); }
.badge--primary { background: color-mix(in srgb, var(--primary) 18%, transparent); color: var(--primary); }
.badge--success { background: color-mix(in srgb, var(--success) 18%, transparent); color: var(--success); }
.badge--danger  { background: color-mix(in srgb, var(--danger) 18%, transparent);  color: var(--danger); }
.badge--warning { background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning); }
.badge--info    { background: color-mix(in srgb, var(--info, var(--primary)) 18%, transparent); color: var(--info, var(--primary)); }
.badge--dark    { background: var(--surface-overlay); color: var(--text-primary); }
</style>
```

Note: before finalizing, check `webui_app/static/css/tokens.css` for `--info`; the `var(--info, var(--primary))` fallback keeps this safe either way. Do NOT edit tokens.css.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm run test -- status-badge` then `npm run test -- Operations` (only existing consumer) then `npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StatusBadge.vue frontend/src/__tests__/status-badge.spec.ts
git commit -m "feat(webui-a): StatusBadge v2 — self-styled tokens, reactive, tone override, Phase A statuses"
```

---

### Task 3: Shared `.chip` class for non-status pills

**Files:**
- Modify: `frontend/src/styles/app.css` (append after the `.data-table` block)
- Modify: `frontend/src/pages/Schedule/SchedulePage.vue` (line ~48 markup, lines ~70–75 scoped style)
- Modify: `frontend/src/pages/Sites/SitesPage.vue` (lines ~342–344 markup, ~476–481 scoped style)
- Modify: `frontend/src/pages/ErrorReports/ErrorReportDetailPage.vue` (lines ~205–207 markup, ~323 scoped style)

**Interfaces:**
- Consumes: tokens `--surface-overlay`, `--radius-pill`, `--text-xs`, `--text-secondary`.
- Produces: global class `.chip` — the ONLY sanctioned way to render a non-status informational pill (platform names, counts, seed candidates). Status pills use `StatusBadge`; nothing else may declare a local `.badge` style.

- [ ] **Step 1: Add `.chip` to app.css**

```css
/* ── Non-status info chip ─────────────────────────────────────────────
   For informational pills (platform names, counts). NOT for statuses —
   status pills are <StatusBadge>. Do not re-declare .badge/.chip in
   page-scoped styles; guard: component-adoption.spec.ts. */
.chip {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: var(--radius-pill);
  background: var(--surface-overlay);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  white-space: nowrap;
}
```

- [ ] **Step 2: Replace page-local `.badge` chips**

In each of the three pages: change `class="badge"` → `class="chip"` on the listed lines and DELETE the page-scoped `.badge { … }` rule. Example (SchedulePage.vue line ~48):

```html
<td><span class="chip">{{ row.platform || '—' }}</span></td>
```

- [ ] **Step 3: Run tests**

Run: `npm run test && npm run typecheck`
Expected: PASS (no spec asserts `.badge` in these pages).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/app.css frontend/src/pages/Schedule/SchedulePage.vue frontend/src/pages/Sites/SitesPage.vue frontend/src/pages/ErrorReports/ErrorReportDetailPage.vue
git commit -m "feat(webui-a): shared .chip class replaces page-local .badge styles"
```

---

### Task 4: Guard tests with ratchet tolerance lists

**Files:**
- Test: `frontend/src/__tests__/component-adoption.spec.ts` (create)
- Test: `frontend/src/__tests__/breakpoint-convention.spec.ts` (create)

**Interfaces:**
- Consumes: page sources under `frontend/src/pages/` (regex over source text — same technique as `data-table-adoption.spec.ts`; keep that older CSS-class guard untouched).
- Produces: two ratcheting guards. Every page task from here on REMOVES its page from a tolerance list as its Step 1 (that IS the failing test), migrates the page, and re-runs. The final task asserts the lists are empty.

- [ ] **Step 1: Write component-adoption.spec.ts**

```ts
// frontend/src/__tests__/component-adoption.spec.ts
// Phase A ratchet guards — docs/superpowers/plans/2026-07-13-webui-phase-a-consistency.md
// Remove entries from the TOLERANCE sets as pages migrate; both must reach empty.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const PAGES = resolve(dirname(fileURLToPath(import.meta.url)), '../pages')
const read = (rel: string) => readFileSync(resolve(PAGES, rel), 'utf8')

/** List pages that must render tables via the shared <DataTable> component. */
const LIST_PAGES = [
  'CampaignProgress/CampaignProgressPage.vue',
  'Drafts/DraftsPage.vue',
  'EquityLedger/EquityLedgerPage.vue',
  'ErrorReports/ErrorReportsPage.vue',
  'History/HistoryPage.vue',
  'KeepAlive/KeepAlivePage.vue',
  'Operations/OperationsPage.vue',
  'OptimizationStatus/OptimizationStatusPage.vue',
  'PrQueue/PrQueuePage.vue',
  'Schedule/SchedulePage.vue',
  'Sites/SitesPage.vue',
]

/** EXEMPT: Health/HealthPage.vue — fail-open dashboard with expandable
 * drill-down rows and ~16 dynamic panels; DataTable's one-<tr>-per-item slot
 * model cannot express it. It keeps the .data-table CSS convention + sr-only
 * captions instead (see Task 13). Re-evaluate if DataTable grows row-details. */

// Ratchet: pages still hand-rolling <table>. Page tasks delete their entry.
const TABLE_TOLERANCE = new Set([
  'CampaignProgress/CampaignProgressPage.vue',
  'EquityLedger/EquityLedgerPage.vue',
  'ErrorReports/ErrorReportsPage.vue',
  'KeepAlive/KeepAlivePage.vue',
  'Operations/OperationsPage.vue',
  'OptimizationStatus/OptimizationStatusPage.vue',
  'PrQueue/PrQueuePage.vue',
  'Schedule/SchedulePage.vue',
  'Sites/SitesPage.vue',
])

// Ratchet: files still hand-rolling status badges/pills (class="badge",
// class="status" :data-status, or STATUS_COLORS-style class maps).
const BADGE_TOLERANCE = new Set([
  'CampaignProgress/CampaignProgressPage.vue',
  'Drafts/DraftsPage.vue',
  'EquityLedger/EquityLedgerPage.vue',
  'ErrorReports/ErrorReportsPage.vue',
  'ErrorReports/ErrorReportDetailPage.vue',
  'History/HistoryPage.vue',
  'KeepAlive/KeepAlivePage.vue',
  'OptimizationStatus/OptimizationStatusPage.vue',
  'PrQueue/PrQueuePage.vue',
])

describe('DataTable component adoption (Phase A ratchet)', () => {
  for (const rel of LIST_PAGES) {
    if (TABLE_TOLERANCE.has(rel)) continue
    it(`${rel} uses <DataTable> and no raw <table>`, () => {
      const text = read(rel)
      expect(text, 'must import DataTable').toMatch(/import DataTable from/)
      expect(text, 'must not hand-roll <table>').not.toMatch(/<table\b/)
    })
  }
})

describe('StatusBadge adoption (Phase A ratchet)', () => {
  const OFFENDER = /class="badge|class="status"|:data-status=|STATUS_COLORS/
  const ALL = [...LIST_PAGES, 'ErrorReports/ErrorReportDetailPage.vue']
  for (const rel of ALL) {
    if (BADGE_TOLERANCE.has(rel)) continue
    it(`${rel} has no hand-rolled badge/status markup`, () => {
      expect(read(rel)).not.toMatch(OFFENDER)
    })
  }
})
```

- [ ] **Step 2: Write breakpoint-convention.spec.ts**

```ts
// frontend/src/__tests__/breakpoint-convention.spec.ts
// Split-screen breakpoint lock (app.css convention, Plan 2026-07-06-005 D12):
// every max-width media query in the SPA must use the 960px literal.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (/\.(vue|css)$/.test(name)) yield p
  }
}

describe('breakpoint convention', () => {
  it('all max-width media queries use the 960px split-screen literal', () => {
    const violations: string[] = []
    for (const file of walk(SRC)) {
      const text = readFileSync(file, 'utf8')
      const queries = text.match(/@media[^{]*max-width:\s*(\d+)px/g) ?? []
      for (const q of queries) {
        const px = /max-width:\s*(\d+)px/.exec(q)?.[1]
        if (px !== '960') violations.push(`${file} — ${q.trim()}`)
      }
    }
    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })
})
```

- [ ] **Step 3: Run both, fix any pre-existing breakpoint violations found**

Run: `npm run test -- component-adoption && npm run test -- breakpoint-convention`
Expected: component-adoption PASS (tolerance covers current offenders; History/Drafts/Sites+Schedule non-tolerated table entries pass because Drafts/History already use DataTable — note Sites/Schedule ARE tolerated). If breakpoint-convention FAILS, change the offending literal to 960px in the cited file (expected: none or 1–2 stragglers; SettingsPage/MonitorDashboard already use 960).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/__tests__/component-adoption.spec.ts frontend/src/__tests__/breakpoint-convention.spec.ts
git commit -m "test(webui-a): ratchet guards for DataTable/StatusBadge adoption + breakpoint lock"
```

---

### Task 5: Migrate Operations page

**Files:**
- Modify: `frontend/src/pages/Operations/OperationsPage.vue` (table block lines ~59–116)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts` (remove tolerance entry)

**Interfaces:**
- Consumes: `DataTable` (Task 1 contract), `StatusBadge` (already used here). Row type `OperationList['operations'][number]` with `op_id/status/kind/stage/progress_pct/running/created_at`.
- Produces: none (leaf task).

- [ ] **Step 1: Remove `'Operations/OperationsPage.vue'` from `TABLE_TOLERANCE`; run `npm run test -- component-adoption` → FAIL (raw `<table>` present).**

- [ ] **Step 2: Migrate the template**

Rows need `id`: adapt the computed —

```ts
const list = computed(() =>
  (query.data.value?.operations ?? []).map((o) => ({ ...o, id: o.op_id })),
)
```

Replace the whole `StateBlock`+`<table class="table table-sm table-hover align-middle">` block with:

```html
<DataTable
  :items="list"
  :loading="query.isPending.value"
  :error="query.isError.value ? query.error.value : undefined"
  empty-text="还没有任务。"
  caption="后台任务列表"
  row-keyboard-nav
  @retry="query.refetch()"
  @row-activate="(op) => openDetail(op.op_id)"
>
  <template #head>
    <th>状态</th>
    <th>类型</th>
    <th>当前阶段</th>
    <th>进度</th>
    <th>创建时间</th>
    <th><span class="sr-only">操作</span></th>
  </template>
  <template #row="{ row: op }">
    <td><StatusBadge :status="op.status" /></td>
    <td>{{ kindLabel[op.kind] || op.kind }}</td>
    <td>{{ op.stage || '—' }}</td>
    <td><!-- keep the existing progress-bar markup for this cell unchanged --></td>
    <td class="col-date">{{ op.created_at }}</td>
    <td><RouterLink :to="`/operations/${op.op_id}`" @click.stop>详情 →</RouterLink></td>
  </template>
</DataTable>
```

Import `DataTable`; keep the existing progress-cell markup verbatim inside its `<td>` (progress-bar restyling is out of scope). The `详情` cell becomes a real `RouterLink` (mouse path; verify the route path against `openDetail`'s router push — use the same target). Row click/Enter still calls `openDetail` via `row-activate`. Delete the old `.op-row` cursor styles and the removed StateBlock wrapper (DataTable embeds StateBlock).

- [ ] **Step 3: Run tests**

Run: `npm run test -- component-adoption && npm run test -- Operations && npm run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Operations/OperationsPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): Operations page adopts DataTable"
```

---

### Task 6: Migrate Schedule page

**Files:**
- Modify: `frontend/src/pages/Schedule/SchedulePage.vue` (table lines ~35–60)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable`; `.chip` (Task 3, already applied to this page). Row type `ScheduledItem`.
- Produces: none.

- [ ] **Step 1: Remove `'Schedule/SchedulePage.vue'` from `TABLE_TOLERANCE`; run guard → FAIL.**

- [ ] **Step 2: Migrate**

If `ScheduledItem` lacks a string `id`, map one (stable): `items.map((r, i) => ({ ...r, id: r.id ?? \`${r.platform}|${r.scheduled_at}|${i}\` }))`. Replace StateBlock+table with:

```html
<DataTable
  :items="items"
  :loading="query.isPending.value"
  :error="query.isError.value ? query.error.value : undefined"
  empty-text="暂无计划发布"
  caption="计划发布列表"
  @retry="query.refetch()"
>
  <template #head>
    <th>平台</th><th>标题</th><th>目标链接</th><th>计划时间</th><th>创建时间</th>
  </template>
  <template #row="{ row }">
    <td><span class="chip">{{ row.platform || '—' }}</span></td>
    <td>{{ row.title || '无标题' }}</td>
    <td class="col-url">
      <a v-if="row.target_url" :href="row.target_url" target="_blank" rel="noopener">{{ row.target_url }}</a>
      <template v-else>—</template>
    </td>
    <td class="col-date">{{ fmt(row.scheduled_at) }}</td>
    <td class="col-date">{{ fmt(row.created_at) }}</td>
  </template>
</DataTable>
```

- [ ] **Step 3: Run tests** — `npm run test -- component-adoption && npm run test -- Schedule && npm run typecheck` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Schedule/SchedulePage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): Schedule page adopts DataTable"
```

---

### Task 7: Migrate CampaignProgress page

**Files:**
- Modify: `frontend/src/pages/CampaignProgress/CampaignProgressPage.vue` (badges lines ~67, ~111; table ~91–120)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable`, `StatusBadge` (`:status` for seed status; `tone` for the done/进行中 summary pill). Rows `CampaignStatus['seeds']` — `id` from `seed.idx`.
- Produces: none.

- [ ] **Step 1: Remove page from BOTH `TABLE_TOLERANCE` and `BADGE_TOLERANCE`; run guard → FAIL.**

- [ ] **Step 2: Migrate**

Summary pill (line ~67):

```html
<StatusBadge :tone="status.done ? 'success' : 'primary'" :label="status.done ? '已完成' : '进行中'" />
```

Seeds table → DataTable (map `id`):

```ts
const seedRows = computed(() =>
  (status.value?.seeds ?? []).map((s) => ({ ...s, id: String(s.idx) })),
)
```

```html
<DataTable
  :items="seedRows"
  :loading="query.isPending.value"
  :error="query.isError.value ? query.error.value : undefined"
  empty-text="任务未找到。"
  caption="种子进度列表"
  @retry="query.refetch()"
>
  <template #head>
    <th>#</th><th>内容</th><th>状态</th><th>草稿</th><th>已发布</th><th>错误</th>
  </template>
  <template #row="{ row: seed }">
    <td class="col-num">{{ seed.idx }}</td>
    <td class="col-text"><code>{{ seed.text_preview }}</code></td>
    <td><StatusBadge :status="seed.status" /></td>
    <td class="col-num">{{ seed.draft_count }}</td>
    <td class="col-num">{{ seed.published_count }}</td>
    <td class="col-text">{{ seed.error || '—' }}</td>
  </template>
</DataTable>
```

Note: the old markup treated any non-`success` seed as `bg-secondary`; StatusBadge's neutral fallback reproduces that for unknown values — no behavior loss. Keep the outer `v-if="status"` structure and the StateBlock that wraps the WHOLE page section if it also guards non-table content; only the table itself moves into DataTable (avoid double StateBlock around the table).

- [ ] **Step 3: Run** `npm run test -- component-adoption && npm run test -- Campaign && npm run typecheck` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/CampaignProgress/CampaignProgressPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): CampaignProgress adopts DataTable + StatusBadge"
```

---

### Task 8: Migrate EquityLedger page

**Files:**
- Modify: `frontend/src/pages/EquityLedger/EquityLedgerPage.vue` (table ~124–157, badges ~143–150)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable`, `StatusBadge` tone overrides. Rows `EquityRow` — synthetic id: `` `${r.target_url}|${r.platform}` ``.
- Produces: none.

- [ ] **Step 1: Remove page from both tolerance sets; run guard → FAIL.**

- [ ] **Step 2: Migrate**

```ts
const tableRows = computed(() =>
  filteredRows.value.map((r) => ({ ...r, id: `${r.target_url}|${r.platform}` })),
)
```

```html
<DataTable
  :items="tableRows"
  :loading="loading"
  :error="loadError"
  empty-text="暂无权益数据。"
  caption="外链权益台账"
  @retry="load()"
>
  <template #head>
    <th>目标 URL</th><th>主域</th><th>平台</th><th>Dofollow</th><th>存活</th>
    <th>相关度</th><th>首次发现</th><th>最后检查</th>
  </template>
  <template #row="{ row }">
    <td class="col-url"><code>{{ row.target_url }}</code></td>
    <td>{{ row.main_domain }}</td>
    <td>{{ row.platform }}</td>
    <td><StatusBadge :tone="row.dofollow ? 'success' : 'neutral'" :label="row.dofollow ? '是' : '否'" /></td>
    <td><StatusBadge :tone="row.live ? 'success' : 'danger'" :label="row.live ? '存活' : '失效'" /></td>
    <td class="col-num">{{ row.relevance_score.toFixed(2) }}</td>
    <td class="col-date">{{ row.first_seen }}</td>
    <td class="col-date">{{ row.last_checked }}</td>
  </template>
</DataTable>
```

Adapt `:loading`/`:error` to this page's actual manual-load state refs (it uses `load()` on mount — reuse whatever refs the existing StateBlock consumed). Above-table filter toolbar stays untouched.

- [ ] **Step 3: Run** `npm run test -- component-adoption && npm run test -- Equity && npm run typecheck` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EquityLedger/EquityLedgerPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): EquityLedger adopts DataTable + StatusBadge tones"
```

---

### Task 9: Migrate PrQueue page

**Files:**
- Modify: `frontend/src/pages/PrQueue/PrQueuePage.vue` (table ~137–189; `STATUS_COLORS` lines ~30–37)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable`, `StatusBadge` (statuses `pending/draft/sent/won/lost/skipped` — all in the Task 2 MAP), `.chip` for the source pill. Rows `PrItem` (has `id`; coerce to string if numeric: `String(item.id)`).
- Produces: none.

- [ ] **Step 1: Remove page from both tolerance sets; run guard → FAIL.**

- [ ] **Step 2: Migrate**

DELETE the `STATUS_COLORS` map entirely. Replace StateBlock+table with DataTable (keep the LITE-unavailable empty variant by passing the same conditional `empty-text` the page already computes):

```html
<DataTable
  :items="items"
  :loading="loading"
  :error="loadError"
  :empty-text="liteMode ? 'LITE 模式下不可用' : '队列为空'"
  caption="PR 机会队列"
  @retry="load()"
>
  <template #head>
    <th>状态</th><th>相关度</th><th>标题</th><th>摘要</th><th>来源</th><th>截止</th><th>操作</th>
  </template>
  <template #row="{ row: item }">
    <td><StatusBadge :status="item.status" /></td>
    <td class="col-num">{{ Math.round(item.relevance_score) }}</td>
    <td>{{ item.headline }}</td>
    <td class="col-text">{{ truncate(item.summary) }}</td>
    <td><span class="chip">{{ item.source }}</span></td>
    <td class="col-date">{{ item.deadline }}</td>
    <td>
      <button type="button" :disabled="updating.has(item.id)" @click="markStatus(item, 'won')">✓</button>
      <button type="button" :disabled="updating.has(item.id)" @click="markStatus(item, 'skipped')">✕</button>
    </td>
  </template>
</DataTable>
```

Reuse the page's existing state refs, empty-variant logic, `truncate`, and `markStatus` signatures exactly as they exist in the file (names above follow the current code; verify while editing). Preserve the disabled-while-updating behavior.

- [ ] **Step 3: Run** `npm run test -- component-adoption && npm run test -- PrQueue && npm run typecheck` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/PrQueue/PrQueuePage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): PrQueue adopts DataTable + StatusBadge, drops STATUS_COLORS"
```

---

### Task 10: Migrate ErrorReports page (+ real pagination)

**Files:**
- Modify: `frontend/src/pages/ErrorReports/ErrorReportsPage.vue` (table ~132–157, status span ~146)
- Read first: `frontend/src/api/` module for error reports (check whether the list endpoint accepts `limit`/`offset`)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable` (incl. pagination props `total/limit/offset` + `update:offset`), `StatusBadge` (`open/acknowledged/resolved`). Rows `ErrorReportItem`.
- Produces: none.

- [ ] **Step 1: Remove page from both tolerance sets; run guard → FAIL.**

- [ ] **Step 2: Migrate**

```html
<DataTable
  :items="items"
  :loading="query.isPending.value"
  :error="query.isError.value ? query.error.value : undefined"
  :empty-text="hasFilters ? '没有符合筛选条件的报告' : '暂无错误报告'"
  caption="错误报告列表"
  :total="total"
  :limit="PAGE_SIZE"
  :offset="offset"
  @retry="query.refetch()"
  @update:offset="offset = $event"
>
  <template #head>
    <th>状态</th><th>严重度</th><th>来源</th><th>消息</th><th>次数</th><th>最后发生</th>
    <th><span class="sr-only">详情</span></th>
  </template>
  <template #row="{ row }">
    <td><StatusBadge :status="row.status" /></td>
    <td>{{ row.severity }}</td>
    <td>{{ row.source }}</td>
    <td class="col-text">{{ preview(row.message) }}</td>
    <td class="col-num">{{ row.occurrences }}</td>
    <td class="col-date">{{ fmtTime(row.last_seen_at) }}</td>
    <td><RouterLink :to="`/error-reports/${row.id}`">查看详情</RouterLink></td>
  </template>
</DataTable>
```

Pagination wiring — ONLY if the API module exposes `limit`/`offset` params: add `const PAGE_SIZE = 50` (or the API's existing default — read it from the api module), `const offset = ref(0)`, include `offset` in the query key so page changes refetch, and reset `offset = 0` when filters change. If the API does not accept offset, omit `total/limit/offset/@update:offset` and leave the header count text as-is (do NOT fake client-side pagination). Delete the `.status[data-status]` scoped CSS (lines ~200–208) and preserve the `#empty-action` clear-filters slot by moving it into DataTable's StateBlock… DataTable does not forward `#empty-action`; instead keep the two-variant `empty-text` (above) and move the clear-filters button to the filter toolbar (always visible when filters set). Note this small UX change in the commit message.

- [ ] **Step 3: Run** `npm run test -- component-adoption && npm run test -- ErrorReports && npm run typecheck` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ErrorReports/ErrorReportsPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): ErrorReports adopts DataTable (+server pagination if supported) + StatusBadge"
```

---

### Task 11: Migrate OptimizationStatus page

**Files:**
- Modify: `frontend/src/pages/OptimizationStatus/OptimizationStatusPage.vue` (table ~123–196, badges ~141/~203–206)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable`, `StatusBadge`. Rows `PlatformWeight` — `id` = `p.platform`.
- Produces: none.

- [ ] **Step 1: Remove page from both tolerance sets; run guard → FAIL.**

- [ ] **Step 2: Migrate**

`const rows = computed(() => platforms.value.map((p) => ({ ...p, id: p.platform })))`. Keep ALL inline-edit machinery (`editingWeight`, `weightInput`, save/cancel buttons) — it lives inside `<td>` slots unchanged. Badge swaps:

- Locked marker (line ~141): `<StatusBadge v-if="p.locked" tone="warning" label="🔒 已锁定" />`
- All-platforms chip list (lines ~203–206): `<StatusBadge :tone="platforms.some((p) => p.platform === pl) ? 'success' : 'neutral'" :label="pl" />`

Table head/row structure mirrors the existing columns (平台/权重/基准/Delta%/调整/存活/总计/漂移/操作); per-row 设置/解锁 buttons stay in the 操作 `<td>`.

- [ ] **Step 3: Run** `npm run test -- component-adoption && npm run test -- Optimization && npm run typecheck` → PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/OptimizationStatus/OptimizationStatusPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): OptimizationStatus adopts DataTable + StatusBadge"
```

---

### Task 12: Migrate KeepAlive + Sites pages

**Files:**
- Modify: `frontend/src/pages/KeepAlive/KeepAlivePage.vue` (scorecard table ~332–359; count pills ~326–328, ~374, ~402)
- Modify: `frontend/src/pages/Sites/SitesPage.vue` (ap-table ~277–324)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `DataTable`, `StatusBadge`, `.chip`.
- Produces: none.

- [ ] **Step 1: Remove both pages from their tolerance sets; run guard → FAIL.**

- [ ] **Step 2: KeepAlive** — scorecard rows get `id: t.target_url`; keep `rowClass` for needs-attention: `:row-class="(t) => ({ 'needs-attention': t.needsAttention })"` (use the page's existing condition). Count pills become:

```html
<StatusBadge tone="success" :label="`存活 ${aliveCount}`" />
<StatusBadge tone="danger" :label="`失效 ${strippedCount}`" />
<StatusBadge tone="neutral" :label="`未知 ${unknownCount}`" />
```

(match the page's existing count variable names), the 运行中 pill → `<StatusBadge status="running" />`, gap platform pill (line ~402) → `<span class="chip">{{ g.platform }}</span>`. The gap-selection checkbox list below the table is NOT a table — leave it alone. The trend/strip-rate colored spans keep their existing classes (they are inline text semantics, not pills).

- [ ] **Step 3: Sites** — autopilot table rows get `id: site.main_url`. Per-row form controls (switch checkbox, interval select, number input, 编辑 button) live in `<td>` slots unchanged. `ap-status` tone span stays (it is a status TEXT with data-tone, page-specific styling — acceptable; do NOT convert to StatusBadge because it renders dynamic sentence-like text). Sites keeps its plan-gap `.chip`s from Task 3.

- [ ] **Step 4: Run** `npm run test -- component-adoption && npm run test -- KeepAlive && npm run test -- Sites && npm run typecheck` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/KeepAlive/KeepAlivePage.vue frontend/src/pages/Sites/SitesPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): KeepAlive + Sites adopt DataTable/StatusBadge/.chip"
```

---

### Task 13: History / Drafts / ErrorReportDetail status spans + Health captions

**Files:**
- Modify: `frontend/src/pages/History/HistoryPage.vue` (status spans ~528/537; scoped CSS ~651/654)
- Modify: `frontend/src/pages/Drafts/DraftsPage.vue` (status span ~192; scoped CSS ~248/251)
- Modify: `frontend/src/pages/ErrorReports/ErrorReportDetailPage.vue` (status span ~202; scoped CSS ~311–319)
- Modify: `frontend/src/pages/Health/HealthPage.vue` (5 tables, lines ~238–378)
- Modify: `frontend/src/__tests__/component-adoption.spec.ts`

**Interfaces:**
- Consumes: `StatusBadge` (statuses `published/failed/scheduled/open/acknowledged/resolved` — all mapped in Task 2).
- Produces: none.

- [ ] **Step 1: Remove `History/HistoryPage.vue`, `Drafts/DraftsPage.vue`, `ErrorReports/ErrorReportDetailPage.vue` from `BADGE_TOLERANCE`; run guard → FAIL.**

- [ ] **Step 2: Swap the spans** — each `<span class="status" :data-status="X">{{ label }}</span>` becomes `<StatusBadge :status="X" />` (the MAP already carries the zh labels; where a page shows a custom label, pass `:label`). Delete the now-dead `.status[data-status]` scoped CSS rules in all three files.

- [ ] **Step 3: Health captions** — add to each of the 5 `<table class="data-table">` elements a `<caption class="sr-only">…</caption>` naming the panel (渠道记分卡 / 金丝雀状态 / 转发路径状态 / 平台健康 / the panel's title for generic panels). Health keeps `.data-table` CSS convention per the guard-test exemption comment (Task 4) — no DataTable migration here.

- [ ] **Step 4: Run** `npm run test && npm run typecheck` → PASS (full vitest sweep — History/Drafts have substantial existing specs; if a spec asserted `.status[data-status]`, update the assertion to `[data-testid="status-badge"]`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/History/HistoryPage.vue frontend/src/pages/Drafts/DraftsPage.vue frontend/src/pages/ErrorReports/ErrorReportDetailPage.vue frontend/src/pages/Health/HealthPage.vue frontend/src/__tests__/component-adoption.spec.ts
git commit -m "feat(webui-a): StatusBadge in History/Drafts/ErrorReportDetail; Health table captions"
```

---

### Task 14: PublishWorkbench feedback-rule cleanup

**Files:**
- Modify: `frontend/src/pages/Publish/PublishWorkbench.vue` (styles ~406–427)

**Interfaces:**
- Consumes: the feedback rule (spec A3): fetch lifecycle → StateBlock; action outcomes → toast/inline `role="alert"`.
- Produces: none.

- [ ] **Step 1: Verify then delete dead CSS** — the template no longer renders `<span class="spinner">`; confirm with a search in the file, then delete the `.spinner { … }` rule and `@keyframes spin` (lines ~414–427). The `.publish-busy` aria-live panel and `publishError` `role="alert"` line already follow the A3 rule — leave them. Add the missing rule for the copy span so it stops relying on inheritance:

```css
.publish-busy__copy {
  font-size: var(--text-sm);
}
```

- [ ] **Step 2: Run** `npm run test -- Publish && npm run typecheck` → PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Publish/PublishWorkbench.vue
git commit -m "feat(webui-a): remove dead spinner CSS in PublishWorkbench per feedback rule"
```

---

### Task 15: frontend/AGENTS.md — codify the conventions

**Files:**
- Create: `frontend/AGENTS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the documented contract future pages must follow (referenced by guard tests).

- [ ] **Step 1: Write frontend/AGENTS.md**

```markdown
# frontend/ — SPA contributor guide

Conventions enforced by guard tests in `src/__tests__/` (component-adoption,
breakpoint-convention, data-table-adoption). Read alongside the repo-root
AGENTS.md.

## Tables
Every list view renders through `src/components/DataTable.vue` (generic over
`T extends { id: string }` — map a stable string `id` onto rows if the API
lacks one). It embeds StateBlock (loading/empty/error), optional selection
(`selectable`), pagination (`total`/`limit`/`offset`), and keyboard row nav
(`rowKeyboardNav` + `rowActivate`, fired on Enter and on non-interactive row
clicks). Exemption: Health/HealthPage.vue (expandable drill-down + dynamic
panels) keeps the `.data-table` CSS convention with sr-only captions.

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
The only sanctioned max-width media query is `@media (max-width: 960px)`
(desktop split-screen; mobile out of scope — app.css block comment). The
breakpoint-convention guard fails any other literal.

## Copy
UI copy is Simplified Chinese (zh-CN). No Bootstrap classes — style with
tokens from `webui_app/static/css/tokens.css` via `var(--…)`.
```

- [ ] **Step 2: Commit**

```bash
git add frontend/AGENTS.md
git commit -m "docs(webui-a): frontend contributor conventions (tables, badges, feedback, breakpoint)"
```

---

### Task 16: Ratchet to zero + full verification

**Files:**
- Modify: `frontend/src/__tests__/component-adoption.spec.ts` (final assert)

**Interfaces:**
- Consumes: all prior tasks.
- Produces: Phase A done-state.

- [ ] **Step 1: Empty-tolerance assertion** — both tolerance sets should now be empty. Replace the two `const *_TOLERANCE = new Set([...])` with `new Set<string>()` and add:

```ts
it('Phase A ratchet complete — tolerance lists are empty', () => {
  expect(TABLE_TOLERANCE.size).toBe(0)
  expect(BADGE_TOLERANCE.size).toBe(0)
})
```

If any entry remains, a page task was skipped — go back and finish it first.

- [ ] **Step 2: Full verification**

Run: `npm run test && npm run typecheck && npm run build`
Expected: all vitest suites PASS; typecheck clean; Vite build emits to `webui_app/spa_dist/` without warnings about missing classes. No Python changed in Phase A, so pytest is not required; run `python -m ruff check webui_app/` only if `git status` shows any accidental Python edits (there should be none).

- [ ] **Step 3: Manual smoke** — start `python webui.py`, open `http://localhost:8888/app/` and click through: Operations (row click → detail), PrQueue (✓/✕ buttons), ErrorReports (filters + pagination if wired), History/Drafts (selection still works), Health (panels render). Verify badges render as colored pills in BOTH themes (toggle via TopBar).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/__tests__/component-adoption.spec.ts
git commit -m "test(webui-a): Phase A ratchet complete — zero tolerance entries"
```

---

## Phase B pointer

Phase B (redirect completion + legacy retirement) is deliberately NOT planned here — it touches Flask routes and the flash-message contract and will be planned as its own document once Phase A ships, against the then-current state. See spec section "Phase B".
