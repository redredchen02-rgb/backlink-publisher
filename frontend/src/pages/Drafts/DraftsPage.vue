<script setup lang="ts">
// Draft-queue page — Plan 2026-06-18-002 U7 (second page).
//
// Replaces the legacy ?tab=draft tab. Lists the draft queue (four-state, now
// via DataTable/U5); a pending draft can be scheduled (datetime), published
// now, or deleted; a scheduled draft can be cancelled or deleted; plus
// bulk-delete. Server messages (incl. the "job lingered" warning) surface as
// toasts; failures go through classifyError (fixed copy, never raw server text).
//
// Plan 2026-07-02-001 U5: paginated via DataTable. Mutation endpoints return
// the FULL table (unchanged contract), not a page-shaped envelope, so
// mutations refetch this page from the server rather than reshaping the
// full-table response locally.
//
// Plan 2026-07-06-005 W13 (D7) reintegration: every draft mutation now runs
// through a single shared `useMutation` (rather than a bare try/catch), so a
// failure is observed by main.ts's `MutationCache.onError` and flows into
// the error-reports dashboard automatically (D8 filters out expected 422s).
// One shared mutation (not one per action) preserves this page's existing
// "single shared `busy` lock across every action, row or bulk" semantics --
// `mutation.isPending` stands in for the old plain `busy` ref 1:1. Drafts has
// no undo state machine to protect (W5 explicitly excludes Drafts, D17 -- no
// soft-delete backend for the Drafts JSON store), so unlike HistoryPage
// there's no reason to keep a hand-rolled mutation runner here: `useMutation`
// is strictly simpler for this page's flat busy/disabled model. The
// mutation's "variables" is a closure (`fn`), so it can never carry a page's
// raw call arguments/secrets even though `useMutation` makes `variables`
// available to `MutationCache.onError` (see lib/errorCapture.ts's module
// docstring for why that boundary matters).
import { computed, reactive, ref } from 'vue'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/vue-query'
import {
  bulkCancelDrafts,
  bulkDeleteDrafts,
  bulkPublishDraftsNow,
  cancelDraft,
  deleteDraft,
  listDrafts,
  publishDraftNow,
  scheduleDraft,
  type DraftMutationResult,
} from '../../api/drafts'
import DataTable from '../../components/DataTable.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'

const PAGE_SIZE = 50

const notify = useNotificationsStore()
const { toastError } = useErrorToast()

const offset = ref(0)
const query = useQuery({
  queryKey: computed(() => ['drafts', offset.value]),
  queryFn: () => listDrafts({ limit: PAGE_SIZE, offset: offset.value }),
  placeholderData: keepPreviousData,
})
const items = computed(() => query.data.value?.items ?? [])
const total = computed(() => query.data.value?.total)

const scheduleInputs = reactive<Record<string, string>>({})
const selected = ref<Set<string>>(new Set())

// Single shared mutation for every draft action (row or bulk) — see the
// script-block header comment for why this replaces the old plain `busy`
// ref/try-catch runner: `mutation.isPending` now backs the SAME `busy`
// external contract (name unchanged) so every existing template binding and
// test assertion against `busy` keeps working unmodified.
const mutation = useMutation({
  mutationKey: ['drafts', 'mutate'],
  mutationFn: (fn: () => Promise<DraftMutationResult>) => fn(),
})
const busy = computed(() => mutation.isPending.value)

function reportError(e: unknown): void {
  toastError(e)
}

/**
 * Run a mutation, refetch this page, clamp offset if deletion overflowed it.
 *
 * `idsToDeselect` (code review): only the ids this specific call acted on are
 * removed from `selected` on success -- not a blanket clear. Without this, a
 * user who changes their selection WHILE a bulk action is in flight has that
 * reselection silently wiped out when the in-flight call resolves, even though
 * it had nothing to do with the completed action.
 */
async function run(fn: () => Promise<DraftMutationResult>, idsToDeselect?: string[]): Promise<void> {
  if (busy.value) return
  try {
    // mutateAsync rethrows on failure (so the local catch below still runs
    // classifyError -> toast), while main.ts's MutationCache.onError
    // independently observes every failure -> error-reports (D7/D8).
    const r = await mutation.mutateAsync(fn)
    if (r.message) notify.push(r.message, 'info')
    await query.refetch()
    const newTotal = query.data.value?.total
    if (newTotal != null && offset.value > 0 && offset.value >= newTotal) {
      offset.value = Math.max(0, Math.floor((newTotal - 1) / PAGE_SIZE) * PAGE_SIZE)
      await query.refetch()
    }
    if (idsToDeselect?.length) {
      const remaining = new Set(selected.value)
      for (const id of idsToDeselect) remaining.delete(id)
      selected.value = remaining
    }
  } catch (e) {
    reportError(e)
  }
}

function onSchedule(id: string): void {
  const at = scheduleInputs[id]
  if (!at) {
    notify.push('请先选择排程时间', 'warning')
    return
  }
  run(() => scheduleDraft(id, at), [id])
}
const onPublishNow = (id: string) => run(() => publishDraftNow(id), [id])
const onCancel = (id: string) => run(() => cancelDraft(id), [id])
const onDelete = (id: string) => run(() => deleteDraft(id), [id])
const onBulkDelete = () => {
  const ids = [...selected.value]
  return run(() => bulkDeleteDrafts(ids), ids)
}
const onBulkPublishNow = () => {
  const ids = [...selected.value]
  return run(() => bulkPublishDraftsNow(ids), ids)
}
const onBulkCancel = () => {
  const ids = [...selected.value]
  return run(() => bulkCancelDrafts(ids), ids)
}
</script>

<template>
  <section class="drafts">
    <header class="drafts__head">
      <h1>草稿队列</h1>
      <div class="drafts__bulk-actions">
        <button
          type="button"
          class="bulk-publish-now"
          :disabled="busy || !selected.size"
          @click="onBulkPublishNow"
        >
          立即发布选中 ({{ selected.size }})
        </button>
        <button
          type="button"
          class="bulk-cancel"
          :disabled="busy || !selected.size"
          @click="onBulkCancel"
        >
          取消选中排程 ({{ selected.size }})
        </button>
        <button
          type="button"
          class="bulk-delete"
          :disabled="busy || !selected.size"
          @click="onBulkDelete"
        >
          删除选中 ({{ selected.size }})
        </button>
      </div>
    </header>

    <DataTable
      :items="items"
      :loading="query.isPending.value"
      :error="query.isError.value ? query.error.value : undefined"
      empty-text="草稿队列是空的"
      caption="草稿队列列表"
      :selected="selected"
      :total="total"
      :limit="PAGE_SIZE"
      :offset="offset"
      :disabled="busy"
      @retry="query.refetch()"
      @update:selected="selected = $event"
      @update:offset="offset = $event"
    >
      <template #head>
        <th>目标页</th>
        <th>状态</th>
        <th>操作</th>
      </template>
      <template #row="{ row }">
        <td class="col-target draft__target" :title="row.target_url">{{ row.target_url }}</td>
        <td class="muted">
          {{ row.platform }} · <span class="status" :data-status="row.status">{{ row.status }}</span>
          <template v-if="row.scheduled_at"> · {{ row.scheduled_at }}</template>
        </td>
        <td>
          <div class="draft__actions">
            <template v-if="row.status === 'scheduled'">
              <button type="button" :disabled="busy" @click="onCancel(row.id)">取消排程</button>
            </template>
            <template v-else>
              <input
                v-model="scheduleInputs[row.id]"
                type="datetime-local"
                :aria-label="`排程时间 ${row.target_url}`"
              />
              <button type="button" :disabled="busy" @click="onSchedule(row.id)">排程</button>
              <button type="button" :disabled="busy" @click="onPublishNow(row.id)">立即发布</button>
            </template>
            <button type="button" class="delete" :disabled="busy" @click="onDelete(row.id)">删除</button>
          </div>
        </td>
      </template>
    </DataTable>
  </section>
</template>

<style scoped>
.drafts {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.drafts__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.drafts__bulk-actions {
  display: flex;
  gap: 0.5rem;
}
.col-target {
  max-width: 24rem;
}
.draft__target {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.draft__actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.status[data-status='scheduled'] {
  color: var(--primary);
}
.status[data-status='failed'] {
  color: var(--danger);
}
</style>
