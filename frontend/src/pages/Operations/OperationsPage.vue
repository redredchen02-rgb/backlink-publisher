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
import StateBlock from '../../components/StateBlock.vue'

const router = useRouter()
const opsStore = useOperationsStore()

const query = usePolledQuery<OperationList>({
  queryKey: ['operations-list'],
  queryFn: () => listOperations(50),
  intervalMs: 5000,
  isTerminal: () => false, // dashboard: keep polling while mounted
})

const list = computed(() => query.data.value?.operations ?? [])

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value && !query.data.value) return 'loading'
  if (query.data.value) return 'ready'
  if (query.isError.value) return 'error'
  return 'empty'
})

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

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="还没有任务。"
      @retry="query.refetch()"
    >
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle">
          <thead>
            <tr>
              <th>状态</th>
              <th>类型</th>
              <th>当前阶段</th>
              <th>进度</th>
              <th>创建时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="op in list"
              :key="op.op_id"
              class="op-row"
              tabindex="0"
              role="button"
              @click="openDetail(op.op_id)"
              @keyup.enter="openDetail(op.op_id)"
            >
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
              <td class="text-muted small">{{ op.created_at }}</td>
              <td><span class="btn btn-sm btn-link">详情 →</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
.op-row {
  cursor: pointer;
}
.op-row:focus-visible {
  outline: 2px solid var(--primary);
}
</style>
