<script setup lang="ts">
// Console top bar — Plan 2026-06-18-002 U4.
// Theme toggle (Pinia store, the explicit owner — no window.* global) + a Pro
// status pill sourced from /api/v1/app-config (the context-processor data, now
// JSON). Search (Ctrl+K) is a stub placeholder for a later unit.
// Unit 7 adds the "report a problem" entry — opens the shared
// ReportProblemPanel (stores/reportPanel.ts) with no reportId, i.e. the
// manual POST path (see ReportProblemPanel.vue's module docstring).
import { useQuery } from '@tanstack/vue-query'
import { getJson } from '../api/client'
import { useThemeStore } from '../stores/theme'
import { useReportPanelStore } from '../stores/reportPanel'
import ReportProblemPanel from '../components/ReportProblemPanel.vue'

interface AppConfig {
  lite_edition: boolean
  llm_configured: boolean
  pro_status: { configured: boolean; model?: string }
}

const theme = useThemeStore()
const reportPanel = useReportPanelStore()
const config = useQuery({
  queryKey: ['app-config'],
  queryFn: () => getJson<AppConfig>('/app-config'),
})
</script>

<template>
  <header class="topbar">
    <input
      class="topbar__search"
      type="search"
      placeholder="搜索…（Ctrl+K，后续启用）"
      aria-label="搜索"
      disabled
    />
    <div class="topbar__right">
      <span
        v-if="config.data.value"
        class="pill"
        :class="config.data.value.llm_configured ? 'pill--on' : 'pill--off'"
      >
        Pro {{ config.data.value.llm_configured ? '已启用' : '未配置' }}
      </span>
      <button type="button" class="topbar__report" @click="reportPanel.open()">
        报告问题
      </button>
      <button type="button" class="topbar__theme" @click="theme.toggle()">
        {{ theme.theme === 'dark' ? '🌙' : '☀️' }}
      </button>
    </div>
  </header>
  <ReportProblemPanel />
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface-raised);
}
.topbar__search {
  flex: 1;
  max-width: 28rem;
  padding: 0.35rem 0.6rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-base);
  color: var(--text-primary);
}
.topbar__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.pill {
  font-size: var(--text-xs);
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
}
.pill--on {
  color: var(--success);
  border-color: var(--success);
}
.pill--off {
  color: var(--text-secondary);
}
.topbar__theme {
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--text-xl);
}
.topbar__report {
  font-size: var(--text-sm);
  padding: 0.3rem 0.6rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
}
</style>
