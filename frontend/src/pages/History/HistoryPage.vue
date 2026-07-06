<script setup lang="ts">
// Publish-history page — Plan 2026-06-18-002 U7, undo UX per
// 2026-07-06-005 W5 (History-only; Drafts undo explicitly out of scope —
// see D17, no soft-delete backend for the Drafts JSON store).
//
// Replaces the legacy /ce:history Jinja tab. Lists publish history (four-state),
// with per-row delete + recheck, bulk-delete via selection, and purge-failed.
// Every mutation endpoint returns the refreshed list, so we just write the
// response back into the query cache (no re-fetch). Action failures go through
// classifyError → a toast (fixed copy, never raw server text).
//
// ── W5 state machine (selection × pagination × refetch × mutation × undo) ──
//
// State surfaces:
//  - `liveItems`      : GET /history (server-side filters out soft-deleted rows)
//  - `deletedItems`    : GET /history?include_deleted=window (D18) — ONLY rows
//                        soft-deleted within the undo window, `deleted_at` set
//  - `pendingIds`      : union of (a) ids we soft-deleted this session (local,
//                        immediate) and (b) ids discovered via `deletedItems`
//                        (server truth — covers page reload mid-window)
//  - `rowSnapshots`    : frozen row data captured at delete time, so a pending
//                        row keeps rendering its old content even though it's
//                        no longer in `liveItems`
//  - `displayRows`     : liveItems ∪ (pendingIds rows via rowSnapshots) — the
//                        actual `<tbody>` source; a pending row is never
//                        spliced out then back in, so no flicker (D5)
//  - `rowBusy` (Set)   : ids with a single-row op in flight
//  - `bulkBusy` (bool) : a bulk op (bulk-delete / bulk-recheck / purge-failed)
//                        in flight
//
// | Event                                            | Transition                                                                                   |
// |---------------------------------------------------|-----------------------------------------------------------------------------------------------|
// | click 删除 (row X)                                  | guard: skip if X busy or table locked → rowBusy+=X → POST /history/delete (soft, no confirm, D3) → snapshot X + pendingIds+=X + start 15s local timer + drop X from `selected` → rowBusy-=X |
// | click 撤销 (row X, pending)                          | guard: skip if X busy or table locked → rowBusy+=X → POST /history/undelete → success: clear timer, pendingIds-=X, drop snapshot; 404 (aged past window): finalize immediately + error toast → rowBusy-=X |
// | local undo timer fires (row X)                     | pendingIds-=X, finalized+=X, drop snapshot → X disappears from view (server-side purge is a separate lazy process; the UI's own window is intentionally the shorter `CLIENT_UNDO_WINDOW_SECONDS`, D18) |
// | manual refetch / query invalidate mid-window       | `liveItems` no longer contains X (still soft-deleted server-side); `deletedItems` still returns X with `deleted_at` set → X stays in `displayRows` unchanged, no disappear-then-reappear |
// | remount/reload while X still in undo window        | `deletedItems` (server truth) surfaces X on first fetch → snapshot + pendingIds+=X + timer scheduled from remaining time (`CLIENT_UNDO_WINDOW_MS - elapsed`), so a stale local timer isn't required |
// | bulk 删除 (selected ids)                            | guard: skip if any row busy or bulk busy → bulkBusy=true → POST /history/bulk-delete → snapshot+pend every id still absent from the refreshed live list → drop those ids from `selected` → toast shows exact `deleted`/`skipped` counts from the response → bulkBusy=false |
// | bulk 重核 (selected ids)                            | same bulkBusy lock; on success, only the acted-on ids are deselected (a mid-flight reselection of a different row is preserved) |
// | 清除失败 (purge-failed — irreversible, D4)           | guarded by ConfirmDialog; `purgeFrozenCount` snapshots the failed-row count at dialog-open time so the confirm label can't drift while the dialog is up; confirm → bulkBusy=true → POST /history/purge-failed |
// | refetch drops a selected id that is NOT soft-deleted (genuinely gone — e.g. another session hard-removed it) | a watcher on `displayRows` prunes any `selected` id no longer present, updating the bulk-button count in the same tick |
// | row op in flight (row A)                           | only row A's own buttons are disabled; row B's row buttons stay enabled; bulk buttons become disabled (mutual-exclusion matrix, D6) |
// | bulk op in flight                                  | entire table (every row's controls + checkboxes) + bulk buttons are disabled |
// | rapid repeated clicks on the same button           | the handler's busy-set check happens synchronously before the first `await`, so a second synchronous click sees the id/bulk lock already set and no-ops — exactly one API call |
// Plan 2026-07-06-005 W13 (D7, option b): this page's mutations deliberately
// stay hand-written async functions rather than migrating to `useMutation`.
// W5's rowBusy/bulkBusy mutual-exclusion matrix (D6) above and the undo
// state machine are precise and synchronous (the busy-set check happens
// BEFORE the first `await`, guaranteeing exactly-once dispatch under rapid
// clicks — see the "rapid repeated clicks" test); re-threading that through
// useMutation's per-call `isPending` risked introducing a race between the
// mutation's own reactive update and this page's own `rowBusy`/`bulkBusy`
// refs for no behavioral gain. Instead, every catch block below calls
// `reportManualMutationError` (in addition to the existing `toastError`) so
// a failure still reaches error-reports exactly like a real
// MutationCache-observed mutation would — see that function's docstring.
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  bulkDeleteHistory,
  bulkRecheckHistory,
  deleteHistory,
  listHistory,
  listHistoryDeletedWindow,
  purgeFailedHistory,
  recheckHistory,
  undeleteHistory,
  type HistoryItem,
} from '../../api/history'
import StateBlock from '../../components/StateBlock.vue'
import Icon from '../../components/Icon.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { reportManualMutationError } from '../../lib/errorCapture'
import { useNotificationsStore } from '../../stores/notifications'
import { useRowReportLinksStore } from '../../stores/rowReportLinks'

const QKEY = ['history']
const DELETED_QKEY = ['history', 'deleted-window']
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const route = useRoute()
const router = useRouter()
const rowReportLinks = useRowReportLinksStore()

// Mirrors the backend's `CLIENT_UNDO_WINDOW_SECONDS = 15`
// (src/backlink_publisher/events/_history_mutations.py) — the server purge
// window is deliberately 2x this so a client-side undo click never races a
// backend purge (see that module's docstring). Keep these two constants in
// sync if the backend value changes.
const CLIENT_UNDO_WINDOW_MS = 15_000

const query = useQuery({ queryKey: QKEY, queryFn: () => listHistory() })
const liveItems = computed<HistoryItem[]>(() => query.data.value?.items ?? [])

const deletedQuery = useQuery({ queryKey: DELETED_QKEY, queryFn: () => listHistoryDeletedWindow() })
const deletedItems = computed<HistoryItem[]>(() => deletedQuery.data.value?.items ?? [])

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  // `displayRows` (not `liveItems`) — a row soft-deleted into its undo window
  // must not flip the whole page to the empty state (D5).
  return displayRows.value.length ? 'ready' : 'empty'
})

// ── undo-window bookkeeping ──────────────────────────────────────────────
const localPending = ref<Set<string>>(new Set())
const finalized = ref<Set<string>>(new Set())
const rowSnapshots = new Map<string, HistoryItem>()
const finalizeTimers = new Map<string, ReturnType<typeof setTimeout>>()

const serverPendingIds = computed(() => new Set(deletedItems.value.map((i) => i.id)))

const pendingIds = computed<Set<string>>(() => {
  const s = new Set<string>()
  for (const id of localPending.value) if (!finalized.value.has(id)) s.add(id)
  for (const id of serverPendingIds.value) if (!finalized.value.has(id)) s.add(id)
  return s
})

function withoutId(set: Set<string>, id: string): Set<string> {
  if (!set.has(id)) return set
  const next = new Set(set)
  next.delete(id)
  return next
}

function clearFinalizeTimer(id: string): void {
  const h = finalizeTimers.get(id)
  if (h !== undefined) {
    clearTimeout(h)
    finalizeTimers.delete(id)
  }
}

function finalizeDelete(id: string): void {
  clearFinalizeTimer(id)
  localPending.value = withoutId(localPending.value, id)
  finalized.value = new Set(finalized.value).add(id)
  rowSnapshots.delete(id)
  // The row is gone for good — any stale "查看报告" link for a past action
  // failure no longer has a live row to point at.
  rowReportLinks.unlinkRow(id)
}

/** Schedule the client-side "stop showing this row" timer. `deletedAtIso`
 * (when known from server truth) lets a freshly-discovered row resume with
 * its *remaining* time instead of a fresh 15s. */
function scheduleFinalize(id: string, deletedAtIso?: string | null): void {
  clearFinalizeTimer(id)
  let delay = CLIENT_UNDO_WINDOW_MS
  if (deletedAtIso) {
    const elapsed = Date.now() - Date.parse(deletedAtIso)
    if (Number.isFinite(elapsed)) delay = Math.max(0, CLIENT_UNDO_WINDOW_MS - elapsed)
  }
  finalizeTimers.set(id, setTimeout(() => finalizeDelete(id), delay))
}

function beginUndoWindow(row: HistoryItem, deletedAtIso?: string | null): void {
  rowSnapshots.set(row.id, row)
  localPending.value = new Set(localPending.value).add(row.id)
  finalized.value = withoutId(finalized.value, row.id)
  scheduleFinalize(row.id, deletedAtIso)
  selected.value = withoutId(selected.value, row.id)
}

// Server-discovered pending rows (e.g. a page reload mid-undo-window) that
// aren't already tracked locally: adopt them, using `deleted_at` to compute
// the remaining window instead of restarting a full 15s.
watch(
  deletedItems,
  (list) => {
    for (const it of list) {
      if (finalized.value.has(it.id) || finalizeTimers.has(it.id)) continue
      beginUndoWindow(it, it.deleted_at)
    }
  },
  { immediate: true },
)

const displayRows = computed<HistoryItem[]>(() => {
  const map = new Map<string, HistoryItem>()
  for (const it of liveItems.value) map.set(it.id, it)
  for (const id of pendingIds.value) {
    if (map.has(id)) continue
    const snap = rowSnapshots.get(id)
    if (snap) map.set(id, snap)
  }
  return [...map.values()]
})

// ── W10 deep-link: highlight a row on return from an error-report ──────────
// ErrorReportDetailPage.vue's "回到来源" sends us here as
// `/history?highlight=<rowId>` when it still knows (this SPA session only —
// see rowReportLinks.ts) which row the report's failure came from. We strip
// the query param immediately (router.replace, no history entry) so a
// refresh/back-navigation never re-triggers it, then resolve it against
// `displayRows` once the list has actually loaded.
const pendingHighlightId = ref<string | null>(null)
const highlightRowId = ref<string | null>(null)
const highlightMissing = ref(false)
const highlightAnnouncement = ref('')
let highlightClearTimer: ReturnType<typeof setTimeout> | undefined

watch(
  () => route.query.highlight,
  (val) => {
    if (typeof val !== 'string' || !val) return
    pendingHighlightId.value = val
    const rest = { ...route.query }
    delete rest.highlight
    void router.replace({ query: rest })
  },
  { immediate: true },
)

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

watch(
  [displayRows, blockState, pendingHighlightId],
  ([rows, state]) => {
    if (!pendingHighlightId.value || state === 'loading') return
    const id = pendingHighlightId.value
    pendingHighlightId.value = null
    const row = rows.find((r) => r.id === id)
    if (!row) {
      highlightMissing.value = true
      highlightAnnouncement.value = '该项目已不在列表中，可能已被删除或翻页后不可见。'
      return
    }
    highlightMissing.value = false
    highlightRowId.value = id
    highlightAnnouncement.value = `已定位到目标记录：${row.target_url}`
    void nextTick(() => {
      const selector = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(id) : id
      const el = document.querySelector<HTMLElement>(`[data-row-id="${selector}"]`)
      el?.scrollIntoView?.({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' })
    })
    if (highlightClearTimer) clearTimeout(highlightClearTimer)
    highlightClearTimer = setTimeout(() => {
      if (highlightRowId.value === id) highlightRowId.value = null
    }, 4000)
  },
  { immediate: true },
)

function dismissHighlightMissing(): void {
  highlightMissing.value = false
}

// ── selection ─────────────────────────────────────────────────────────────
const selected = ref<Set<string>>(new Set())

function toggle(id: string): void {
  const next = new Set(selected.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selected.value = next
}

// Stale-selection pruning: if a previously-selected id vanishes from
// `displayRows` for a reason OTHER than "it's in its undo window" (i.e. it's
// genuinely gone — another session hard-removed it, or it aged past
// everything), drop it from `selected` and let the bulk-button count follow.
watch(displayRows, (rows) => {
  const ids = new Set(rows.map((r) => r.id))
  let changed = false
  const next = new Set(selected.value)
  for (const id of selected.value) {
    if (!ids.has(id)) {
      next.delete(id)
      changed = true
    }
  }
  if (changed) selected.value = next
})

// ── busy / mutual-exclusion (D6) ─────────────────────────────────────────
const rowBusy = ref<Set<string>>(new Set())
const bulkBusy = ref(false)

function setRowBusy(id: string, val: boolean): void {
  rowBusy.value = val ? new Set(rowBusy.value).add(id) : withoutId(rowBusy.value, id)
}

function rowDisabled(id: string): boolean {
  return bulkBusy.value || rowBusy.value.has(id)
}

const tableLocked = computed(() => bulkBusy.value)
const bulkButtonsDisabled = computed(() => bulkBusy.value || rowBusy.value.size > 0)

/** `context` is a short free-form call-site label (e.g. `'history.delete'`)
 *  — never raw error/response payload — forwarded to error-reports (D8:
 *  non-422 failures, incl. CSRF 403 / invariant 400 / aged-out undo 404, are
 *  incident-class and must be reported, same as a 500).
 *
 * Plan 2026-07-06-005 W10: when `rowIds` is given, once the report actually
 * submits we record the real (id, row) correlation in rowReportLinks so the
 * affected row(s) can surface a "查看报告" deep-link — see that store's
 * docstring for why this is exact, not a heuristic guess, and why it's
 * deliberately NOT awaited here (toastError must fire immediately; the link
 * appearing a moment later, once the POST resolves, is fine — it's reactive). */
function reportError(e: unknown, context: string, rowIds?: string | string[]): void {
  void reportManualMutationError(e, context).then((reportId) => {
    if (!reportId) return
    const ids = Array.isArray(rowIds) ? rowIds : rowIds ? [rowIds] : []
    for (const id of ids) rowReportLinks.link('history', id, reportId)
  })
  toastError(e)
}

// ── single-row mutations ──────────────────────────────────────────────────
async function onDelete(id: string): Promise<void> {
  if (rowDisabled(id)) return
  const row = displayRows.value.find((r) => r.id === id)
  if (!row) return
  setRowBusy(id, true)
  try {
    const r = await deleteHistory(id)
    qc.setQueryData(QKEY, { items: r.items })
    beginUndoWindow(row)
    rowReportLinks.unlinkRow(id)
  } catch (e) {
    reportError(e, 'history.delete', id)
  } finally {
    setRowBusy(id, false)
  }
}

async function onUndo(id: string): Promise<void> {
  if (rowDisabled(id)) return
  setRowBusy(id, true)
  try {
    const r = await undeleteHistory(id)
    qc.setQueryData(QKEY, { items: r.items })
    clearFinalizeTimer(id)
    localPending.value = withoutId(localPending.value, id)
    rowSnapshots.delete(id)
    qc.setQueryData(DELETED_QKEY, {
      items: deletedItems.value.filter((it) => it.id !== id),
    })
    notify.push('已撤销删除', 'success')
    rowReportLinks.unlinkRow(id)
  } catch (e) {
    // 404 (aged past the purge window) — nothing left to undo; hide it.
    // D8: a 404 here is an operator-visible race (server purged the row
    // before the undo click landed), NOT an expected-422 — still reported.
    finalizeDelete(id)
    reportError(e, 'history.undelete', id)
  } finally {
    setRowBusy(id, false)
  }
}

async function onRecheck(id: string): Promise<void> {
  if (rowDisabled(id)) return
  setRowBusy(id, true)
  try {
    const r = await recheckHistory(id)
    qc.setQueryData(QKEY, { items: r.items })
    selected.value = withoutId(selected.value, id)
    if (r.message) notify.push(r.message, 'info')
    rowReportLinks.unlinkRow(id)
  } catch (e) {
    reportError(e, 'history.recheck', id)
  } finally {
    setRowBusy(id, false)
  }
}

// ── bulk mutations ─────────────────────────────────────────────────────────
async function onBulkDelete(): Promise<void> {
  const ids = [...selected.value]
  if (!ids.length || bulkButtonsDisabled.value) return
  const rows = ids
    .map((id) => displayRows.value.find((r) => r.id === id))
    .filter((r): r is HistoryItem => !!r)
  bulkBusy.value = true
  try {
    const r = await bulkDeleteHistory(ids)
    qc.setQueryData(QKEY, { items: r.items })
    const stillLiveIds = new Set(r.items.map((it) => it.id))
    for (const row of rows) {
      if (!stillLiveIds.has(row.id)) beginUndoWindow(row)
    }
    if (r.message) notify.push(r.message, 'info')
    for (const id of ids) rowReportLinks.unlinkRow(id)
  } catch (e) {
    // Bulk endpoints are ONE HTTP call for every selected id, so a single
    // failure genuinely explains all of them — not a guess, the same request
    // that failed covers every row in `ids`.
    reportError(e, 'history.bulk-delete', ids)
  } finally {
    bulkBusy.value = false
  }
}

async function onBulkRecheck(): Promise<void> {
  const ids = [...selected.value]
  if (!ids.length || bulkButtonsDisabled.value) return
  bulkBusy.value = true
  try {
    const r = await bulkRecheckHistory(ids)
    qc.setQueryData(QKEY, { items: r.items })
    const remaining = new Set(selected.value)
    for (const id of ids) remaining.delete(id)
    selected.value = remaining
    if (r.message) notify.push(r.message, 'info')
    for (const id of ids) rowReportLinks.unlinkRow(id)
  } catch (e) {
    reportError(e, 'history.bulk-recheck', ids)
  } finally {
    bulkBusy.value = false
  }
}

// ── purge-failed: the one genuinely irreversible op (D4) ───────────────────
const hasFailed = computed(() => liveItems.value.some((i) => i.status === 'failed'))
const purgeConfirmOpen = ref(false)
const purgeFrozenCount = ref(0)
const purgeFrozenIds = ref<string[]>([])

function openPurgeConfirm(): void {
  if (bulkButtonsDisabled.value || !hasFailed.value) return
  const failedIds = liveItems.value.filter((i) => i.status === 'failed').map((i) => i.id)
  purgeFrozenCount.value = failedIds.length
  purgeFrozenIds.value = failedIds
  purgeConfirmOpen.value = true
}

async function confirmPurge(): Promise<void> {
  bulkBusy.value = true
  try {
    const r = await purgeFailedHistory()
    qc.setQueryData(QKEY, { items: r.items })
    if (r.message) notify.push(r.message, 'info')
    for (const id of purgeFrozenIds.value) rowReportLinks.unlinkRow(id)
  } catch (e) {
    // No toastError here (unlike reportError above) — ConfirmDialog itself
    // shows an inline error and keeps the dialog open on rejection (see its
    // onConfirmClick), so a global toast would double-surface the same
    // failure. Error-reports still needs this failure (D8), so report it
    // manually, then rethrow so ConfirmDialog's own handling still runs.
    const failedIds = purgeFrozenIds.value
    void reportManualMutationError(e, 'history.purge-failed').then((reportId) => {
      if (!reportId) return
      for (const id of failedIds) rowReportLinks.link('history', id, reportId)
    })
    throw e
  } finally {
    bulkBusy.value = false
  }
}
</script>

<template>
  <section class="history">
    <header class="history__head">
      <h1>发布历史</h1>
      <div class="history__actions">
        <button
          type="button"
          :disabled="bulkButtonsDisabled || !selected.size"
          class="bulk-recheck"
          @click="onBulkRecheck"
        >
          重核选中 ({{ selected.size }})
        </button>
        <button
          type="button"
          :disabled="bulkButtonsDisabled || !selected.size"
          class="bulk-delete"
          @click="onBulkDelete"
        >
          删除选中 ({{ selected.size }})
        </button>
        <button
          type="button"
          :disabled="bulkButtonsDisabled || !hasFailed"
          @click="openPurgeConfirm"
        >
          清除失败
        </button>
      </div>
    </header>

    <ConfirmDialog
      v-model:open="purgeConfirmOpen"
      title="确认清除失败记录"
      :confirm-label="`确认清除（${purgeFrozenCount} 条）`"
      danger
      :confirm="confirmPurge"
    >
      此操作不可撤销，将永久删除全部失败记录，无法通过撤销恢复。
    </ConfirmDialog>

    <!-- W10 deep-link: sr-only live region for the highlight outcome, plus a
         visible, dismissible banner for the "row no longer here" edge case
         (never silent — see plan Test scenarios). -->
    <p class="sr-only" aria-live="polite">{{ highlightAnnouncement }}</p>
    <div v-if="highlightMissing" class="highlight-missing" role="status">
      <span>该项目已不在列表中，可能已被删除或翻页后不可见。</span>
      <button type="button" class="highlight-missing__dismiss" aria-label="关闭提示" @click="dismissHighlightMissing">×</button>
    </div>

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="还没有发布记录"
      @retry="query.refetch()"
    >
      <div class="data-table-wrap">
        <table class="rows data-table" :class="{ 'rows--locked': tableLocked }">
          <thead>
            <tr>
              <th></th>
              <th>状态</th>
              <th>目标页</th>
              <th>平台</th>
              <th>发布文章（点击核查内链）</th>
              <th>时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in displayRows"
              :key="row.id"
              :data-row-id="row.id"
              :data-status="row.status"
              :class="{ 'row--pending-delete': pendingIds.has(row.id), 'row--highlight': highlightRowId === row.id }"
            >
              <td>
                <input
                  type="checkbox"
                  :checked="selected.has(row.id)"
                  :disabled="tableLocked || pendingIds.has(row.id)"
                  :aria-label="`选择 ${row.target_url}`"
                  @change="toggle(row.id)"
                />
              </td>
              <td class="col-status">
                <span v-if="pendingIds.has(row.id)" class="status status--deleted" data-status="deleted">
                  已删除 ·
                  <button
                    type="button"
                    class="undo-link"
                    :disabled="rowDisabled(row.id)"
                    @click="onUndo(row.id)"
                  >撤销</button>
                </span>
                <span v-else class="status" :data-status="row.status">{{ row.status }}</span>
              </td>
              <td class="col-url target" :title="row.target_url">
                <a :href="row.target_url" target="_blank" rel="noopener" class="url-link">
                  {{ row.target_url }}<Icon name="box-arrow-up-right" class="ext-icon" />
                </a>
              </td>
              <td>{{ row.platform }}</td>
              <td class="col-article-urls">
                <template v-if="row.article_urls?.length">
                  <div v-for="(url, i) in row.article_urls" :key="i" class="article-url-row">
                    <a :href="url" target="_blank" rel="noopener" :title="url" class="article-link">
                      <Icon name="box-arrow-up-right" class="me-1" />{{ url }}
                    </a>
                  </div>
                  <div v-if="row.verified_at" class="verified-at">
                    核查于 {{ new Date(row.verified_at * 1000).toLocaleDateString('zh-CN') }}
                  </div>
                </template>
                <span v-else class="muted">—</span>
              </td>
              <td class="col-date muted">{{ row.created_at }}</td>
              <td class="row-actions">
                <RouterLink
                  v-if="rowReportLinks.reportIdForRow(row.id)"
                  :to="`/error-reports/${rowReportLinks.reportIdForRow(row.id)}`"
                  class="row-report-link"
                  :aria-label="`查看 ${row.target_url} 操作失败对应的错误报告`"
                >查看报告</RouterLink>
                <template v-if="!pendingIds.has(row.id)">
                  <button type="button" :disabled="rowDisabled(row.id)" @click="onRecheck(row.id)">重核存活</button>
                  <button type="button" :disabled="rowDisabled(row.id)" @click="onDelete(row.id)">删除</button>
                </template>
                <span v-else class="muted">撤销窗口内</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
.history {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.highlight-missing {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--control-pad-y) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--surface-overlay);
  border-left: 3px solid var(--warning);
  color: var(--text-primary);
}
.highlight-missing__dismiss {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--text-lg);
  line-height: 1;
  padding: 0;
}
/* Row highlight: not color-only — an outline (+ underline on the target-url
   cell) so the a11y guard "highlight is not color alone" holds. The global
   `@media (prefers-reduced-motion: reduce)` rule in app.css already zeroes
   this transition's duration, so reduced-motion users get an instant,
   static outline instead of a fade. */
.row--highlight {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
  transition: outline-color 0.3s ease;
}
.row--highlight .url-link {
  text-decoration: underline;
}
.row-report-link {
  color: var(--danger);
  text-decoration: underline;
  font-size: 0.8rem;
  white-space: nowrap;
}
.history__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.history__actions {
  display: flex;
  gap: 0.5rem;
}
/* .rows inherits .data-table layout; only page-specific overrides below */
.target {
  max-width: 24rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status[data-status='published'] {
  color: var(--success);
}
.status[data-status='failed'] {
  color: var(--danger);
}
.status--deleted {
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.undo-link {
  background: none;
  border: none;
  color: var(--primary);
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  font-size: inherit;
}
.undo-link:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.row--pending-delete {
  opacity: 0.6;
}
.row-actions {
  display: flex;
  gap: 0.4rem;
}
.url-link {
  color: inherit;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  max-width: 24rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.url-link:hover {
  text-decoration: underline;
  color: var(--primary);
}
.ext-icon {
  flex-shrink: 0;
  font-size: 0.7em;
  opacity: 0.5;
}
.col-article-urls {
  max-width: 32rem;
}
.article-url-row {
  margin-bottom: 0.2rem;
}
.article-link {
  display: inline-flex;
  align-items: center;
  color: var(--primary);
  text-decoration: none;
  font-size: 0.8rem;
  font-family: ui-monospace, monospace;
  max-width: 30rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.article-link:hover {
  text-decoration: underline;
}
.verified-at {
  font-size: 0.72rem;
  color: var(--text-secondary);
  margin-top: 0.15rem;
}
</style>
