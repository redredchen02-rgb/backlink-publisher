<script setup lang="ts">
// Publish-history page — Plan 2026-06-18-002 U7, undo UX per
// 2026-07-06-005 W5 (History-only; Drafts undo explicitly out of scope —
// see D17, no soft-delete backend for the Drafts JSON store).
//
// Replaces the legacy /ce:history Jinja tab. Lists publish history (four-state,
// via DataTable/U5), with per-row delete + recheck, bulk-delete via selection,
// and purge-failed. Action failures go through classifyError → a toast (fixed
// copy, never raw server text).
//
// ── Reintegration (worktree bp-reintegrate-u5): W5 undo UX + W10 cross-page
// deep-link + W13 mutation error-reporting, re-threaded through the U5
// DataTable/pagination architecture ──
//
// State surfaces (W5 undo state machine):
//  - `liveItems`   : this page's slice from GET /history?limit=&offset=
//                    (server excludes soft-deleted rows entirely)
//  - `deletedItems`: GET /history?include_deleted=window (D18) — UNPAGINATED,
//                    only rows soft-deleted within the undo window, each with
//                    `deleted_at` set
//  - `pendingIds`  : union of (a) ids soft-deleted this session (local,
//                    immediate) and (b) ids discovered via `deletedItems`
//                    (server truth — covers page reload mid-window)
//  - `rowSnapshots`: frozen row data captured at delete time, so a pending
//                    row keeps rendering its old content even once it drops
//                    out of `liveItems`
//  - `displayRows` : liveItems ∪ (pendingIds rows via rowSnapshots) — fed to
//                    DataTable's `items` prop instead of the raw query data,
//                    so a pending row is never spliced out then back in (D5)
//  - `rowBusy` (Set) / `bulkBusy` (bool): D6 mutual-exclusion matrix
//
// Pagination note: `total` fed to DataTable is the LIVE query's total ONLY —
// pending rows are "extra" rows temporarily rendered on top of a page and
// must never perturb the pagination math.
//
// Plan 2026-07-06-005 W13 (D7, option b): mutations stay hand-written rather
// than useMutation for precise rowBusy/bulkBusy mutual exclusion.
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/vue-query'
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
import DataTable from '../../components/DataTable.vue'
import Icon from '../../components/Icon.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { reportManualMutationError } from '../../lib/errorCapture'
import { useNotificationsStore } from '../../stores/notifications'
import { useRowReportLinksStore } from '../../stores/rowReportLinks'

const PAGE_SIZE = 50
// Mirrors the backend's `CLIENT_UNDO_WINDOW_SECONDS = 15`
// (src/backlink_publisher/events/_history_mutations.py) — the server purge
// window is deliberately 2x this so a client-side undo click never races a
// backend purge. Keep these two constants in sync if the backend changes.
const CLIENT_UNDO_WINDOW_MS = 15_000

const DELETED_QKEY = ['history', 'deleted-window']
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const route = useRoute()
const router = useRouter()
const rowReportLinks = useRowReportLinksStore()

// ── live (paginated) + deleted-window (unpaginated) queries ────────────────
const offset = ref(0)
const query = useQuery({
  queryKey: computed(() => ['history', offset.value]),
  queryFn: () => listHistory({ limit: PAGE_SIZE, offset: offset.value }),
  placeholderData: keepPreviousData,
})
const liveItems = computed<HistoryItem[]>(() => query.data.value?.items ?? [])
const total = computed(() => query.data.value?.total)

const deletedQuery = useQuery({
  queryKey: DELETED_QKEY,
  queryFn: () => listHistoryDeletedWindow(),
})
const deletedItems = computed<HistoryItem[]>(() => deletedQuery.data.value?.items ?? [])

// ── undo-window bookkeeping (W5) ────────────────────────────────────────────
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

function rowClassFor(row: HistoryItem): Record<string, boolean> {
  return {
    'row--pending-delete': pendingIds.value.has(row.id),
    'row--highlight': highlightRowId.value === row.id,
  }
}

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
  [displayRows, () => query.isPending.value, pendingHighlightId],
  ([rows, isLoading]) => {
    if (!pendingHighlightId.value || isLoading) return
    const id = pendingHighlightId.value
    pendingHighlightId.value = null
    const row = (rows as HistoryItem[]).find((r) => r.id === id)
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
      const el = document.querySelector<HTMLElement>(`[data-id="${selector}"]`)
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

// Stale-selection pruning: if a previously-selected id vanishes from
// `displayRows` for a reason OTHER than "it's in its undo window" (i.e. it's
// genuinely gone — another session hard-removed it, or a page change moved
// it out of view), drop it from `selected` and let the bulk-button count
// follow. A pending row never triggers this (it stays in `displayRows` via
// its snapshot).
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

const bulkButtonsDisabled = computed(() => bulkBusy.value || rowBusy.value.size > 0)

/**
 * Refetch this page's live list (with the existing U5 offset-clamp
 * safeguard) plus the deleted-window query, so both state surfaces reflect
 * the mutation that just happened. `idsToDeselect` (code review, U5): only
 * the ids this specific call acted on are removed from `selected` on
 * success -- not a blanket clear, so a mid-flight reselection survives.
 */
async function afterMutation(idsToDeselect?: string[]): Promise<void> {
  await query.refetch()
  const newTotal = query.data.value?.total
  if (newTotal != null && offset.value > 0 && offset.value >= newTotal) {
    offset.value = Math.max(0, Math.floor((newTotal - 1) / PAGE_SIZE) * PAGE_SIZE)
    await query.refetch()
  }
  await deletedQuery.refetch()
  if (idsToDeselect?.length) {
    const remaining = new Set(selected.value)
    for (const id of idsToDeselect) remaining.delete(id)
    selected.value = remaining
  }
}

/** `context` is a short free-form call-site label (e.g. `'history.delete'`)
 *  — never raw error/response payload — forwarded to error-reports (D8:
 *  non-422 failures, incl. CSRF 403 / invariant 400 / aged-out undo 404, are
 *  incident-class and must be reported, same as a 500).
 *
 * When `rowIds` is given, once the report actually submits we record the
 * real (id, row) correlation in rowReportLinks so the affected row(s) can
 * surface a "查看报告" deep-link -- deliberately NOT awaited here (toastError
 * must fire immediately; the link appearing a moment later, once the POST
 * resolves, is fine -- it's reactive). */
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
    await deleteHistory(id)
    await afterMutation()
    beginUndoWindow(row)
  } catch (e) {
    reportError(e, 'history.delete', [id])
  } finally {
    setRowBusy(id, false)
  }
}

async function onUndo(id: string): Promise<void> {
  if (rowDisabled(id)) return
  setRowBusy(id, true)
  try {
    await undeleteHistory(id)
    await afterMutation()
    clearFinalizeTimer(id)
    localPending.value = withoutId(localPending.value, id)
    rowSnapshots.delete(id)
    qc.setQueryData(DELETED_QKEY, {
      items: deletedItems.value.filter((it) => it.id !== id),
    })
    notify.push('已撤销删除', 'success')
  } catch (e) {
    finalizeDelete(id)
    reportError(e, 'history.undelete', [id])
  } finally {
    setRowBusy(id, false)
  }
}

async function onRecheck(id: string): Promise<void> {
  if (rowDisabled(id)) return
  setRowBusy(id, true)
  try {
    const r = await recheckHistory(id)
    await afterMutation([id])
    if (r.message) notify.push(r.message, 'info')
  } catch (e) {
    reportError(e, 'history.recheck', [id])
  } finally {
    setRowBusy(id, false)
  }
}

// W11 keyboard row nav: Enter on a keyboard-focused row triggers this row's
// "main action" -- opening the published target URL, mirroring the existing
// mouse path (click the row's target-url link) rather than any of the
// destructive/mutating row buttons (recheck/delete), which stay strictly
// click-only to avoid an accidental Enter causing a mutation.
function onRowActivate(row: HistoryItem): void {
  window.open(row.target_url, '_blank', 'noopener')
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
    await afterMutation(ids)
    const stillLiveIds = new Set(liveItems.value.map((it) => it.id))
    for (const row of rows) {
      if (!stillLiveIds.has(row.id)) beginUndoWindow(row)
    }
    if (r.message) notify.push(r.message, 'info')
    for (const id of ids) rowReportLinks.unlinkRow(id)
  } catch (e) {
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
    await afterMutation(ids)
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

function openPurgeConfirm(): void {
  if (bulkButtonsDisabled.value || !hasFailed.value) return
  purgeFrozenCount.value = liveItems.value.filter((i) => i.status === 'failed').length
  purgeConfirmOpen.value = true
}

async function confirmPurge(): Promise<void> {
  bulkBusy.value = true
  try {
    const r = await purgeFailedHistory()
    await afterMutation()
    if (r.message) notify.push(r.message, 'info')
  } catch (e) {
    reportError(e, 'history.purge-failed')
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

    <!-- W10 deep-link: sr-only live region for the highlight outcome, plus a
         visible, dismissible banner for the "row no longer here" edge case
         (never silent). -->
    <p class="sr-only" aria-live="polite">{{ highlightAnnouncement }}</p>
    <div v-if="highlightMissing" class="highlight-missing" role="status">
      <span>该项目已不在列表中，可能已被删除或翻页后不可见。</span>
      <button type="button" class="highlight-missing__dismiss" aria-label="关闭提示" @click="dismissHighlightMissing">×</button>
    </div>

    <ConfirmDialog
      v-model:open="purgeConfirmOpen"
      title="确认清除失败记录"
      :confirm-label="`确认清除（${purgeFrozenCount} 条）`"
      danger
      :confirm="confirmPurge"
    >
      此操作不可撤销，将永久删除全部失败记录，无法通过撤销恢复。
    </ConfirmDialog>

    <DataTable
      :items="displayRows"
      :loading="query.isPending.value"
      :error="query.isError.value ? query.error.value : undefined"
      empty-text="还没有发布记录"
      caption="发布历史列表"
      row-keyboard-nav
      :selected="selected"
      :total="total"
      :limit="PAGE_SIZE"
      :offset="offset"
      :disabled="bulkBusy"
      :row-class="rowClassFor"
      @retry="query.refetch()"
      @update:selected="selected = $event"
      @update:offset="offset = $event"
      @row-activate="onRowActivate"
    >
      <template #head>
        <th>状态</th>
        <th>目标页</th>
        <th>平台</th>
        <th>发布文章（点击核查内链）</th>
        <th>时间</th>
        <th></th>
      </template>
      <template #row="{ row }">
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
      </template>
    </DataTable>
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
:deep(.row--highlight) {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
  transition: outline-color 0.3s ease;
}
:deep(.row--highlight) .url-link {
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
/* DataTable owns .data-table/.data-table-wrap layout; page-specific column overrides below */
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
:deep(.row--pending-delete) {
  opacity: 0.6;
}
.row-actions {
  display: flex;
  gap: 0.4rem;
  align-items: center;
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
