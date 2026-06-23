<script setup lang="ts">
// Settings in-page navigation (Plan 2026-06-18-002 U7, section 4 — page chrome).
// The settings page grew into a long scroll (global config + AI + 6 channel cards);
// this sticky rail gives an at-a-glance bind overview + jump-to-section links. It is
// presentational — the legacy sidebar's pane-SWITCHING is replaced by scroll-to in
// the SPA's single-scroll idiom. Channel counts reuse the overview query
// (['settings','channels']) already loaded by ChannelsCard — no extra request.
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getChannels } from '../../api/settings'

interface Section {
  id: string
  label: string
}

// Mirrors the anchor ids SettingsPage puts on each section, in page order.
const SECTIONS: Section[] = [
  { id: 'sec-channels', label: '渠道总览' },
  { id: 'sec-binding', label: '凭据绑定' },
  { id: 'sec-medium', label: 'Medium' },
  { id: 'sec-velog', label: 'velog' },
  { id: 'sec-blogger', label: 'Blogger' },
  { id: 'sec-notion', label: 'Notion' },
  { id: 'sec-blogids', label: 'Blog ID 映射' },
  { id: 'sec-keywords', label: '关键词池' },
  { id: 'sec-schedule', label: '排程' },
  { id: 'sec-ai', label: 'AI 整合' },
]

const channelsQuery = useQuery({ queryKey: ['settings', 'channels'], queryFn: getChannels })
const channels = computed(() => channelsQuery.data.value?.channels ?? [])
const boundCount = computed(() => channels.value.filter((c) => c.bound).length)
const totalCount = computed(() => channels.value.length)
const hasBlockers = computed(() => channels.value.some((c) => c.blockers.length > 0))

function jumpTo(id: string): void {
  document.getElementById(id)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <nav class="snav" aria-label="设置分区导航">
    <div class="snav__overview" data-test="snav-overview">
      <span class="snav__count">{{ boundCount }}/{{ totalCount }}</span>
      <span class="snav__label">渠道已绑定</span>
      <span v-if="hasBlockers" class="snav__warn" title="部分渠道有未解决的阻断项">⚠ 有阻断项</span>
    </div>
    <ul class="snav__list">
      <li v-for="s in SECTIONS" :key="s.id">
        <button type="button" class="snav__item" @click="jumpTo(s.id)">{{ s.label }}</button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.snav {
  position: sticky;
  top: 1rem;
  align-self: start;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.snav__overview {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem;
  padding: 0.6rem 0.75rem;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.snav__count {
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--success);
}
.snav__label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.snav__warn {
  flex-basis: 100%;
  font-size: var(--text-xs);
  color: var(--warning);
}
.snav__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.snav__item {
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  padding: 0.35rem 0.5rem;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-base);
  cursor: pointer;
}
.snav__item:hover {
  background: var(--surface-base);
  color: var(--text-primary);
}
</style>
