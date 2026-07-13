<script setup lang="ts">
// Operations task center — Plan 2026-07-09 (U3).
//
// Lists the operator's recent async operations (publish / publish-chain / plan
// / validate) with status, progress and a link to each detail view. Polls the
// list so a running op shows live; also keeps the sidenav badge count fresh.
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { listOperations, type OperationList } from '../../api/operations'
import { usePolledQuery } from '../../composables/usePolledQuery'
import { useOperationsStore } from '../../stores/operations'
import StatusBadge from '../../components/StatusBadge.vue'
import DataTable from '../../components/DataTable.vue'

const router = useRouter()
const opsStore = useOperationsStore()

const query = usePolledQuery<OperationList>({
  queryKey: ['operations-list'],
  queryFn: () => listOperations(50),
  intervalMs: 5000,
  isTerminal: () => false, // dashboard: keep polling while mounted
})

const list = computed(() =>
  (query.data.value?.operations ?? []).map((o) => ({ ...o, id: o.op_id })),
)

// Keep the sidenav badge in sync with how many ops are in flight.
const activeCount = computed(
  () => list.value.filter((o) => o.status === 'running' || o.status === 'pending').length,
)
opsStore.setActiveCount(activeCount.value)

const kindLabel: Record<string, string> = {
  plan: '生成',
  validate: '验证',
  publish: '发布',
  publish_chain: '一键发布',
}

function openDetail(opId: string): void {
  router.push(`/operations/${opId}`)
}
</script>

<template>
  <section class="ops-page container py-3">
    <header class="d-flex align-items-center justify-content-between mb-3">
      <h1 class="h4 mb-0">任务中心</h1>
      <span class="text-muted small">进行中：{{ activeCount }}</span>
    </header>

    <!-- Data-wins error gating (CampaignProgressPage precedent, commit
         326b093a): DataTable's own blockState checks `error` BEFORE
         `items.length` (see DataTable.vue's blockState computed), so
         wiring the raw query.isError straight through replaces an
         already-rendered list with the error/retry UI on every single
         failed poll tick, even though keepPreviousData still has the last
         good page cached. Only surface the error when there is no cached
         data left to show. -->
    <DataTable
      :items="list"
      :loading="query.isPending.value"
      :error="!query.data.value && query.isError.value ? query.error.value : undefined"
      empty-text="还没有任务。"
      caption="后台任务列表"
      row-keyboard-nav
      row-click-activate
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
        <td style="min-width: 140px">
          <div class="progress" style="height: 14px">
            <div
              class="progress-bar"
              :class="{ 'progress-bar-striped progress-bar-animated': op.running }"
              :style="{ width: Math.round(op.progress_pct) + '%' }"
            />
          </div>
        </td>
        <td class="col-date">{{ op.created_at }}</td>
        <td><RouterLink :to="`/operations/${op.op_id}`" @click.stop>详情 →</RouterLink></td>
      </template>
    </DataTable>
  </section>
</template>

<style scoped>
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
