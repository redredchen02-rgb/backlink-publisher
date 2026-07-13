<script setup lang="ts">
// Error-reports dashboard list — Plan 2026-07-01-002 Unit 8 (R5).
//
// Filterable, paginated read surface over Unit 3's GET /api/v1/error-reports.
// Data-fetching mirrors api/drafts.ts + DraftsPage.vue's list+filter+paginate
// shape (TanStack Query, queryKey includes filters + offset so changing
// either re-fetches; `placeholderData: keepPreviousData` keeps the last page
// on screen while the next one loads instead of flashing to the loading
// skeleton).
//
// Task 10 (Phase A consistency): migrated to the shared DataTable (which
// embeds its own StateBlock — loading/empty/error/ready) + StatusBadge.
// `query.isError`/`query.isPending` are wired directly into DataTable's
// props: unlike CampaignProgressPage's usePolledQuery (which repeatedly
// refetches the SAME query key every 2s, so a failed poll after a successful
// one leaves real cached data sitting next to a truthy isError — the
// regression DataTable's error-before-items.length check would otherwise
// surface), this page has no polling loop. Each filter/offset combination is
// its own query key, matching the same direct-wiring shape already used by
// DraftsPage.vue / HistoryPage.vue for their paginated DataTables.
//
// Two distinct empty-state strings, not one: a genuinely empty dataset reads
// differently from "filtered down to zero", which also offers a clear-filters
// action. That action lives in the always-visible filter toolbar (below) —
// DataTable does not forward a `#empty-action` slot the way the page's old
// hand-rolled StateBlock usage did, so the button moved out of the (now
// removed) empty-state slot into the toolbar, where it was already
// duplicated defensively; this migration just drops the now-impossible
// second copy.
import { computed, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { listErrorReports, type ErrorReportFilters, type ErrorReportItem } from '../../api/errorReports'
import DataTable from '../../components/DataTable.vue'
import StatusBadge from '../../components/StatusBadge.vue'

const PAGE_SIZE = 50

const filters = reactive<{ status: string; severity: string; source: string }>({
  status: '',
  severity: '',
  source: '',
})

const isFiltering = computed(
  () => !!(filters.status || filters.severity || filters.source),
)

function clearFilters(): void {
  filters.status = ''
  filters.severity = ''
  filters.source = ''
}

const activeFilters = computed<ErrorReportFilters>(() => {
  const f: ErrorReportFilters = {}
  if (filters.status) f.status = filters.status
  if (filters.severity) f.severity = filters.severity
  if (filters.source) f.source = filters.source
  return f
})

const offset = ref(0)

// Reset to page 1 whenever the filter set changes -- an offset carried over
// from a previous filter could point past the end of the newly-filtered
// result set (or just land on a confusingly different page of it).
watch(activeFilters, () => {
  offset.value = 0
})

const query = useQuery({
  queryKey: computed(() => ['error-reports', activeFilters.value, offset.value] as const),
  queryFn: () => listErrorReports({ ...activeFilters.value, limit: PAGE_SIZE, offset: offset.value }),
  placeholderData: keepPreviousData,
})

const items = computed<ErrorReportItem[]>(() => query.data.value?.items ?? [])
const total = computed<number>(() => query.data.value?.total ?? 0)

const emptyText = computed(() =>
  isFiltering.value ? '没有符合目前筛选条件的错误报告' : '尚无任何错误报告',
)

function fmtTime(iso: string | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isFinite(d.getTime()) ? d.toLocaleString('zh-CN') : iso
}

function preview(text: string | undefined): string {
  if (!text) return '—'
  return text.length > 80 ? `${text.slice(0, 77)}…` : text
}
</script>

<template>
  <section class="error-reports">
    <header class="error-reports__head">
      <h1>错误报告</h1>
      <p class="muted">共 {{ total }} 条（本页 {{ items.length }} 条）</p>
    </header>

    <form class="filters" novalidate @submit.prevent>
      <label>
        状态
        <select v-model="filters.status" aria-label="按状态筛选">
          <option value="">全部</option>
          <option value="open">待处理</option>
          <option value="acknowledged">已确认</option>
          <option value="resolved">已解决</option>
        </select>
      </label>
      <label>
        严重度
        <input v-model="filters.severity" type="text" placeholder="例如 error" aria-label="按严重度筛选" />
      </label>
      <label>
        来源
        <input v-model="filters.source" type="text" placeholder="例如 vue-error-handler" aria-label="按来源筛选" />
      </label>
      <button v-if="isFiltering" type="button" class="clear-filters" @click="clearFilters">
        清除筛选
      </button>
    </form>

    <DataTable
      :items="items"
      :loading="query.isPending.value"
      :error="query.isError.value ? query.error.value : undefined"
      :empty-text="emptyText"
      caption="错误报告列表"
      :total="total"
      :limit="PAGE_SIZE"
      :offset="offset"
      @retry="query.refetch()"
      @update:offset="offset = $event"
    >
      <template #head>
        <th>状态</th>
        <th>严重度</th>
        <th>来源</th>
        <th>消息</th>
        <th>次数</th>
        <th>最后发生</th>
        <th><span class="sr-only">详情</span></th>
      </template>
      <template #row="{ row }">
        <td><StatusBadge :status="row.status" /></td>
        <td>{{ row.severity ?? '—' }}</td>
        <td>{{ row.source ?? '—' }}</td>
        <td class="col-text" :title="row.message">{{ preview(row.message) }}</td>
        <td class="col-num">{{ row.occurrences ?? 1 }}</td>
        <td class="col-date">{{ fmtTime(row.last_seen_at) }}</td>
        <td><RouterLink :to="`/error-reports/${row.id}`" class="detail-link">查看详情</RouterLink></td>
      </template>
    </DataTable>
  </section>
</template>

<style scoped>
/* DataTable owns .data-table/.data-table-wrap layout; page-specific styles below */
.error-reports {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.error-reports__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.filters {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.filters label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--text-sm, 0.85rem);
}
.filters select,
.filters input {
  padding: var(--control-pad-y, 0.35rem) var(--control-pad-x, 0.5rem);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  color: inherit;
  font: inherit;
}
.clear-filters {
  cursor: pointer;
}
.detail-link {
  color: var(--primary);
  text-decoration: none;
}
.detail-link:hover {
  text-decoration: underline;
}
.muted {
  color: var(--text-secondary);
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
</style>
