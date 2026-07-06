<script setup lang="ts">
// Publish-history page — Plan 2026-06-18-002 U7 (first page of the campaign).
//
// Replaces the legacy /ce:history Jinja tab. Lists publish history (four-state),
// with per-row delete + recheck, bulk-delete via selection, and purge-failed.
// Every mutation endpoint returns the refreshed list, so we just write the
// response back into the query cache (no re-fetch). Action failures go through
// classifyError → a toast (fixed copy, never raw server text).
import { computed, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  bulkDeleteHistory,
  bulkRecheckHistory,
  deleteHistory,
  listHistory,
  purgeFailedHistory,
  recheckHistory,
  type HistoryItem,
  type HistoryMutationResult,
} from '../../api/history'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'

const QKEY = ['history']
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()

const query = useQuery({ queryKey: QKEY, queryFn: listHistory })
const items = computed<HistoryItem[]>(() => query.data.value?.items ?? [])

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return items.value.length ? 'ready' : 'empty'
})

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

/**
 * Run a mutation, write the refreshed list back into the cache, surface message.
 *
 * `idsToDeselect` (code review): only the ids this specific call acted on are
 * removed from `selected` on success -- not a blanket clear. Without this, a
 * user who changes their selection WHILE a bulk action is in flight has that
 * reselection silently wiped out when the in-flight call resolves, even though
 * it had nothing to do with the completed action.
 */
async function run(
  fn: () => Promise<HistoryMutationResult>,
  idsToDeselect?: string[],
): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const r = await fn()
    qc.setQueryData(QKEY, { items: r.items })
    if (idsToDeselect?.length) {
      const remaining = new Set(selected.value)
      for (const id of idsToDeselect) remaining.delete(id)
      selected.value = remaining
    }
    if (r.message) notify.push(r.message, 'info')
  } catch (e) {
    reportError(e)
  } finally {
    busy.value = false
  }
}

const onDelete = (id: string) => run(() => deleteHistory(id), [id])
const onRecheck = (id: string) => run(() => recheckHistory(id), [id])
const onPurgeFailed = () => run(purgeFailedHistory)
const onBulkDelete = () => {
  const ids = [...selected.value]
  return run(() => bulkDeleteHistory(ids), ids)
}
const onBulkRecheck = () => {
  const ids = [...selected.value]
  return run(() => bulkRecheckHistory(ids), ids)
}

const hasFailed = computed(() => items.value.some((i) => i.status === 'failed'))
</script>

<template>
  <section class="history">
    <header class="history__head">
      <h1>发布历史</h1>
      <div class="history__actions">
        <button
          type="button"
          :disabled="busy || !selected.size"
          class="bulk-recheck"
          @click="onBulkRecheck"
        >
          重核选中 ({{ selected.size }})
        </button>
        <button
          type="button"
          :disabled="busy || !selected.size"
          class="bulk-delete"
          @click="onBulkDelete"
        >
          删除选中 ({{ selected.size }})
        </button>
        <button type="button" :disabled="busy || !hasFailed" @click="onPurgeFailed">
          清除失败
        </button>
      </div>
    </header>

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="还没有发布记录"
      @retry="query.refetch()"
    >
      <div class="data-table-wrap">
        <table class="rows data-table">
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
            <tr v-for="row in items" :key="row.id" :data-status="row.status">
              <td>
                <input
                  type="checkbox"
                  :checked="selected.has(row.id)"
                  :aria-label="`选择 ${row.target_url}`"
                  @change="toggle(row.id)"
                />
              </td>
              <td class="col-status"><span class="status" :data-status="row.status">{{ row.status }}</span></td>
              <td class="col-url target" :title="row.target_url">
                <a :href="row.target_url" target="_blank" rel="noopener" class="url-link">
                  {{ row.target_url }}<i class="bi bi-box-arrow-up-right ext-icon"></i>
                </a>
              </td>
              <td>{{ row.platform }}</td>
              <td class="col-article-urls">
                <template v-if="row.article_urls?.length">
                  <div v-for="(url, i) in row.article_urls" :key="i" class="article-url-row">
                    <a :href="url" target="_blank" rel="noopener" :title="url" class="article-link">
                      <i class="bi bi-box-arrow-up-right me-1"></i>{{ url }}
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
                <button type="button" :disabled="busy" @click="onRecheck(row.id)">重核存活</button>
                <button type="button" :disabled="busy" @click="onDelete(row.id)">删除</button>
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
