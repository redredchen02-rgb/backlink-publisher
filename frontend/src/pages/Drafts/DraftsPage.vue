<script setup lang="ts">
// Draft-queue page — Plan 2026-06-18-002 U7 (second page).
//
// Replaces the legacy ?tab=draft tab. Lists the draft queue (four-state); a
// pending draft can be scheduled (datetime), published now, or deleted; a
// scheduled draft can be cancelled or deleted; plus bulk-delete. Every mutation
// returns the refreshed list (written straight into the query cache). Server
// messages (incl. the "job lingered" warning) surface as toasts; failures go
// through classifyError (fixed copy, never raw server text).
import { computed, reactive, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  bulkDeleteDrafts,
  cancelDraft,
  deleteDraft,
  listDrafts,
  publishDraftNow,
  scheduleDraft,
  type DraftItem,
  type DraftMutationResult,
} from '../../api/drafts'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'

const QKEY = ['drafts']
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()

const query = useQuery({ queryKey: QKEY, queryFn: listDrafts })
const items = computed<DraftItem[]>(() => query.data.value?.items ?? [])

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return items.value.length ? 'ready' : 'empty'
})

const scheduleInputs = reactive<Record<string, string>>({})
const selected = ref<Set<string>>(new Set())
const busy = ref(false)

function toggle(id: string): void {
  const next = new Set(selected.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selected.value = next
}

function reportError(e: unknown): void {
  toastError(e)
}

async function run(fn: () => Promise<DraftMutationResult>): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const r = await fn()
    qc.setQueryData(QKEY, { items: r.items })
    selected.value = new Set()
    if (r.message) notify.push(r.message, 'info')
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

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="草稿队列是空的"
      @retry="query.refetch()"
    >
      <ul class="rows">
        <li v-for="row in items" :key="row.id" class="draft" :data-status="row.status">
          <input
            type="checkbox"
            :checked="selected.has(row.id)"
            :aria-label="`选择 ${row.target_url}`"
            @change="toggle(row.id)"
          />
          <div class="draft__main">
            <span class="draft__target">{{ row.target_url }}</span>
            <span class="muted">
              {{ row.platform }} · <span class="status" :data-status="row.status">{{ row.status }}</span>
              <template v-if="row.scheduled_at"> · {{ row.scheduled_at }}</template>
            </span>
          </div>
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
        </li>
      </ul>
    </StateBlock>
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
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.draft {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.draft__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
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
