<script setup lang="ts">
// Scheduled-drafts page — Plan 2026-06-18-002 U7 (schedule page).
//
// Read-only table of drafts queued for future publish (platform / title /
// target / scheduled-at / created-at). Reschedule + cancel live on the Drafts
// page (this is a calendar-style view, not a control surface). Four-state via
// StateBlock; auto-refreshes when the tab regains focus.
import { computed, onMounted, onUnmounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { listScheduled, type ScheduledItem } from '../../api/schedule'
import StateBlock from '../../components/StateBlock.vue'

const query = useQuery({ queryKey: ['schedule'], queryFn: listScheduled })
const items = computed<ScheduledItem[]>(() => query.data.value?.items ?? [])

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return items.value.length ? 'ready' : 'empty'
})

function fmt(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString('zh-CN')
}

// Refresh on tab refocus (mirrors the legacy ESM's visibilitychange handler).
function onVisible(): void {
  if (document.visibilityState === 'visible') query.refetch()
}
onMounted(() => document.addEventListener('visibilitychange', onVisible))
onUnmounted(() => document.removeEventListener('visibilitychange', onVisible))
</script>

<template>
  <section class="schedule">
    <h1>计划发布</h1>
    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="暂无计划发布"
      @retry="query.refetch()"
    >
      <table class="sched-table">
        <thead>
          <tr><th>平台</th><th>标题</th><th>目标链接</th><th>计划时间</th><th>创建时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in items" :key="row.id ?? i">
            <td><span class="badge">{{ row.platform || '—' }}</span></td>
            <td>{{ row.title || '无标题' }}</td>
            <td class="truncate">
              <a v-if="row.target_url" :href="row.target_url" target="_blank" rel="noopener">{{ row.target_url }}</a>
              <span v-else>—</span>
            </td>
            <td>{{ fmt(row.scheduled_at) }}</td>
            <td>{{ fmt(row.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </StateBlock>
  </section>
</template>

<style scoped>
.schedule {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.sched-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.sched-table th,
.sched-table td {
  text-align: left;
  padding: 0.45rem 0.6rem;
  border-bottom: 1px solid var(--border, #30363d);
  white-space: nowrap;
}
.truncate {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.badge {
  background: var(--bg-overlay, #1f2630);
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.8rem;
}
</style>
