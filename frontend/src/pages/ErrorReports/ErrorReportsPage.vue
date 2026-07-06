<script setup lang="ts">
// Error-reports dashboard list — Plan 2026-07-01-002 Unit 8 (R5).
//
// Filterable, paginated read surface over Unit 3's GET /api/v1/error-reports.
// Data-fetching mirrors api/history.ts + HistoryPage.vue's list+filter shape
// (TanStack Query, queryKey includes the filters so changing a filter
// re-fetches automatically).
//
// Four-state rendering goes through the shared StateBlock.vue, with `isError`
// evaluated BEFORE the empty check (blockState below) — getting this order
// backwards would render a failed fetch as "no error reports", the exact
// false-success shape docs/solutions/ux-honesty/webui-false-success-resolution.md
// warns against, and especially dishonest on the one page whose entire job is
// reporting problems.
//
// Two distinct empty-state strings, not one: a genuinely empty dataset reads
// differently from "filtered down to zero", which also offers a clear-filters
// action — conflating them would make an operator believe there are zero
// errors when the filters may just be hiding dozens.
import { computed, reactive } from 'vue'
import { RouterLink } from 'vue-router'
import { useQuery } from '@tanstack/vue-query'
import { listErrorReports, type ErrorReportFilters, type ErrorReportItem } from '../../api/errorReports'
import StateBlock from '../../components/StateBlock.vue'

const STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  acknowledged: '已确认',
  resolved: '已解决',
}

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

const QKEY = computed(() => ['error-reports', activeFilters.value] as const)

const query = useQuery({
  queryKey: QKEY,
  queryFn: () => listErrorReports(activeFilters.value),
})

const items = computed<ErrorReportItem[]>(() => query.data.value?.items ?? [])
const total = computed<number>(() => query.data.value?.total ?? 0)

// isError checked BEFORE items.length === 0 — see file header.
const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return items.value.length ? 'ready' : 'empty'
})

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

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      :empty-text="emptyText"
      @retry="query.refetch()"
    >
      <template #empty-action>
        <button v-if="isFiltering" type="button" class="clear-filters" @click="clearFilters">
          清除筛选
        </button>
      </template>

      <div class="data-table-wrap">
        <table class="rows data-table">
          <thead>
            <tr>
              <th>状态</th>
              <th>严重度</th>
              <th>来源</th>
              <th>消息</th>
              <th>次数</th>
              <th>最后发生</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id" :data-status="row.status">
              <td><span class="status" :data-status="row.status">{{ STATUS_LABELS[row.status] ?? row.status }}</span></td>
              <td>{{ row.severity ?? '—' }}</td>
              <td>{{ row.source ?? '—' }}</td>
              <td class="col-message" :title="row.message">{{ preview(row.message) }}</td>
              <td>{{ row.occurrences ?? 1 }}</td>
              <td class="muted">{{ fmtTime(row.last_seen_at) }}</td>
              <td>
                <RouterLink :to="`/error-reports/${row.id}`" class="detail-link">查看详情</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
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
.status[data-status='open'] {
  color: var(--danger);
}
.status[data-status='acknowledged'] {
  color: var(--warning);
}
.status[data-status='resolved'] {
  color: var(--success);
}
.col-message {
  max-width: 26rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
</style>
