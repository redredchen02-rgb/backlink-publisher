<script setup lang="ts">
// Console top bar — Plan 2026-06-18-002 U4.
// Theme toggle (Pinia store, the explicit owner — no window.* global) + a Pro
// status pill sourced from /api/v1/app-config (the context-processor data, now
// JSON). Search (Ctrl+K) is a stub placeholder for a later unit.
//
// Plan 2026-07-01-001 U4: hamburger toggle for the sidenav drawer, visible
// only below the 1024px breakpoint (CSS `display: none` above it — removes it
// from the tab order too, so wide-screen keyboard behaviour is unchanged).
// Falls back to a standalone drawer instance when mounted without an
// AppShell ancestor, matching SideNav.vue's fallback.
import { inject, onMounted, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getJson } from '../api/client'
import { useThemeStore } from '../stores/theme'
import { SIDENAV_DRAWER_KEY, useSidenavDrawer } from '../composables/useSidenavDrawer'

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

const drawer = inject(SIDENAV_DRAWER_KEY, () => useSidenavDrawer(), true)
const hamburgerEl = ref<HTMLElement | null>(null)
onMounted(() => {
  drawer.triggerEl.value = hamburgerEl.value
})
</script>

<template>
  <header class="topbar">
    <button
      ref="hamburgerEl"
      type="button"
      class="topbar__hamburger"
      aria-label="打开导航菜单"
      aria-controls="sidenav-drawer"
      :aria-expanded="drawer.isOpen.value"
      @click="drawer.toggle()"
    >
      ☰
    </button>
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
  border-bottom: 1px solid var(--border);
  background: var(--surface-raised);
  /* Stay above AppShell's drawer overlay (z-index: 1040) so the hamburger
     toggle that opens the drawer remains clickable to close it too. */
  position: relative;
  z-index: 1041;
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
.topbar__hamburger {
  display: none;
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--text-xl);
  color: var(--text-primary);
  padding: 0.15rem 0.4rem;
}
@media (max-width: 1024px) {
  .topbar__hamburger {
    display: inline-flex;
  }
}
</style>
