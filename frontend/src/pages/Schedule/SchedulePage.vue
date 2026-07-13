<script setup lang="ts">
// Scheduled-drafts page — Plan 2026-06-18-002 U7 (schedule page).
//
// Read-only table of drafts queued for future publish (platform / title /
// target / scheduled-at / created-at). Reschedule + cancel live on the Drafts
// page (this is a calendar-style view, not a control surface). Auto-refreshes
// when the tab regains focus.
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { listScheduled, type ScheduledItem } from '../../api/schedule'
import DataTable from '../../components/DataTable.vue'

// refetchOnWindowFocus: explicit to remain resilient if global QueryClient
// config is ever changed to disable it. Old manual visibilitychange handler
// was double-triggering alongside TanStack Query's built-in focus handling.
const query = useQuery({ queryKey: ['schedule'], queryFn: listScheduled, refetchOnWindowFocus: true })
const rawItems = computed<ScheduledItem[]>(() => query.data.value?.items ?? [])

// Map items to include stable string IDs for DataTable (which requires T extends { id: string })
const items = computed(() =>
  rawItems.value.map((r, i) => ({
    ...r,
    id: r.id ?? `${r.platform}|${r.scheduled_at}|${i}`,
  })),
)

function fmt(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('zh-CN')
}
</script>

<template>
  <section class="schedule">
    <h1>计划发布</h1>
    <DataTable
      :items="items"
      :loading="query.isPending.value"
      :error="query.isError.value ? query.error.value : undefined"
      empty-text="暂无计划发布"
      caption="计划发布列表"
      @retry="query.refetch()"
    >
      <template #head>
        <th>平台</th><th>标题</th><th>目标链接</th><th>计划时间</th><th>创建时间</th>
      </template>
      <template #row="{ row }">
        <td><span class="chip">{{ row.platform || '—' }}</span></td>
        <td>{{ row.title || '无标题' }}</td>
        <td class="col-url">
          <a v-if="row.target_url" :href="row.target_url" target="_blank" rel="noopener" :title="row.target_url">{{ row.target_url }}</a>
          <template v-else>—</template>
        </td>
        <td class="col-date">{{ fmt(row.scheduled_at) }}</td>
        <td class="col-date">{{ fmt(row.created_at) }}</td>
      </template>
    </DataTable>
  </section>
</template>

<style scoped>
.schedule {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
