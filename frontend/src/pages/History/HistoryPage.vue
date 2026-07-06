<script setup lang="ts">
// Publish-history page — Plan 2026-06-18-002 U7 (first page of the campaign).
//
// Replaces the legacy /ce:history Jinja tab. Lists publish history (four-state,
// now via DataTable/U5), with per-row delete + recheck, bulk-delete via
// selection, and purge-failed. Action failures go through classifyError → a
// toast (fixed copy, never raw server text).
//
// Plan 2026-07-02-001 U5: paginated via DataTable. Mutation endpoints return
// the FULL table (unchanged contract), not a page-shaped envelope, so mutations
// refetch this page from the server rather than reshaping the full-table
// response locally -- the correct shape for total/limit/offset can only come
// from the paginated GET.
import { computed, ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import {
  bulkDeleteHistory,
  deleteHistory,
  listHistory,
  purgeFailedHistory,
  recheckHistory,
  type HistoryMutationResult,
} from '../../api/history'
import DataTable from '../../components/DataTable.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'
import { classifyError } from '../../lib/errors'

const PAGE_SIZE = 50

const notify = useNotificationsStore()
const { toastError } = useErrorToast()

const offset = ref(0)
const query = useQuery({
  queryKey: computed(() => ['history', offset.value]),
  queryFn: () => listHistory({ limit: PAGE_SIZE, offset: offset.value }),
  placeholderData: keepPreviousData,
})
const items = computed(() => query.data.value?.items ?? [])
const total = computed(() => query.data.value?.total)

const selected = ref<Set<string>>(new Set())
const busy = ref(false)

function reportError(e: unknown): void {
  toastError(e)
}

/** Run a mutation, refetch this page, clamp offset if deletion overflowed it. */
async function run(fn: () => Promise<HistoryMutationResult>): Promise<void> {
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

const onDelete = (id: string) => run(() => deleteHistory(id))
const onRecheck = (id: string) => run(() => recheckHistory(id))
// purge-failed acts on the FULL set (server-side), not just this page, so its
// availability isn't gated on whether the *visible* page happens to contain a
// failed row -- the backend already no-ops gracefully (200, not an error) when
// there's nothing to purge.
const onPurgeFailed = () => run(purgeFailedHistory)
const onBulkDelete = () => run(() => bulkDeleteHistory([...selected.value]))
</script>

<template>
  <section class="history">
    <header class="history__head">
      <h1>发布历史</h1>
      <div class="history__actions">
        <button
          type="button"
          :disabled="busy || !selected.size"
          class="bulk-delete"
          @click="onBulkDelete"
        >
          删除选中 ({{ selected.size }})
        </button>
        <button type="button" :disabled="busy" @click="onPurgeFailed">
          清除失败
        </button>
      </div>
    </header>

    <DataTable
      :items="items"
      :loading="query.isPending.value"
      :error="query.isError.value ? query.error.value : undefined"
      empty-text="还没有发布记录"
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
        <th>状态</th>
        <th>目标页</th>
        <th>平台</th>
        <th>发布文章（点击核查内链）</th>
        <th>时间</th>
        <th></th>
      </template>
      <template #row="{ row }">
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
