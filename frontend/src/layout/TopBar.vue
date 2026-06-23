<script setup lang="ts">
// Console top bar — Plan 2026-06-18-002 U4.
// Theme toggle (Pinia store, the explicit owner — no window.* global) + a Pro
// status pill sourced from /api/v1/app-config (the context-processor data, now
// JSON). Search (Ctrl+K) is a stub placeholder for a later unit.
import { useQuery } from '@tanstack/vue-query'
import { getJson } from '../api/client'
import { useThemeStore } from '../stores/theme'

interface AppConfig {
  lite_edition: boolean
  llm_configured: boolean
  pro_status: { configured: boolean; model?: string }
}

const theme = useThemeStore()
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
      <button type="button" class="topbar__theme" @click="theme.toggle()">
        {{ theme.theme === 'dark' ? '🌙' : '☀️' }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--border, #30363d);
  background: var(--surface-raised, #161b22);
}
.topbar__search {
  flex: 1;
  max-width: 28rem;
  padding: 0.35rem 0.6rem;
  border-radius: var(--radius-sm, 4px);
  border: 1px solid var(--border, #30363d);
  background: var(--surface-base, #0d1117);
  color: var(--text-primary, #e6edf3);
}
.topbar__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.pill {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  border: 1px solid var(--border, #30363d);
}
.pill--on {
  color: var(--success, #2ea043);
  border-color: var(--success, #2ea043);
}
.pill--off {
  color: var(--text-secondary, #8b949e);
}
.topbar__theme {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.1rem;
}
</style>
