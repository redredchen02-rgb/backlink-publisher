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
import { computed, reactive, ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import {
  bulkDeleteDrafts,
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
import { classifyError } from '../../lib/errors'

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
const busy = ref(false)

function reportError(e: unknown): void {
  toastError(e)
}

/** Run a mutation, refetch this page, clamp offset if deletion overflowed it. */
async function run(fn: () => Promise<DraftMutationResult>): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const r = await fn()
    if (r.message) notify.push(r.message, 'info')
    await query.refetch()
    const newTotal = query.data.value?.total
    if (newTotal != null && offset.value > 0 && offset.value >= newTotal) {
      offset.value = Math.max(0, Math.floor((newTotal - 1) / PAGE_SIZE) * PAGE_SIZE)
      await query.refetch()
    }
    selected.value = new Set()
  } catch (e) {
    reportError(e)
  } finally {
    busy.value = false
  }
}

function onSchedule(id: string): void {
  const at = scheduleInputs[id]
  if (!at) {
    notify.push('请先选择排程时间', 'warning')
    return
  }
  run(() => scheduleDraft(id, at))
}
const onPublishNow = (id: string) => run(() => publishDraftNow(id))
const onCancel = (id: string) => run(() => cancelDraft(id))
const onDelete = (id: string) => run(() => deleteDraft(id))
const onBulkDelete = () => run(() => bulkDeleteDrafts([...selected.value]))
</script>

<template>
  <section class="drafts">
    <header class="drafts__head">
      <h1>草稿队列</h1>
      <button
        type="button"
        class="bulk-delete"
        :disabled="busy || !selected.size"
        @click="onBulkDelete"
      >
        删除选中 ({{ selected.size }})
      </button>
    </header>

    <DataTable
      :items="items"
      :loading="query.isPending.value"
      :error="query.isError.value ? query.error.value : undefined"
      empty-text="草稿队列是空的"
      :selected="selected"
      :total="total"
      :limit="PAGE_SIZE"
      :offset="offset"
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
