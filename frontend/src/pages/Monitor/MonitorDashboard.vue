<script setup lang="ts">
// Monitoring aggregate dashboard — Plan 2026-06-18-002 U6 (inherits redesign R11).
//
// "Today's anomalies first": one fetch to /api/v1/monitor/summary returns cards
// already ranked server-side (danger → warning → ok → info); the SPA only
// displays them. Polled with TanStack Query + keepPreviousData so each tick does
// NOT flash the loading skeleton (the four-state 'stale' convention).
//
// Dual-stack wayfinding: each card's deep_link / action.href is a legacy Jinja
// page, so they are plain <a href> (full navigation OUT of the SPA, marked ↪) —
// not RouterLinks — until those pages are migrated.
import { computed } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { monitorSummary } from '../../api/monitor'
import StateBlock from '../../components/StateBlock.vue'

const POLL_MS = 30_000

const query = useQuery({
  queryKey: ['monitor-summary'],
  queryFn: monitorSummary,
  refetchInterval: POLL_MS,
  placeholderData: keepPreviousData, // don't flash the skeleton on each poll tick
})

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  // Zero cards only happens when the aggregator itself failed (degraded). All-OK
  // still returns cards — "no anomalies" is conveyed by the header banner.
  if ((query.data.value?.cards.length ?? 0) === 0) return 'empty'
  return 'ready'
})

const cards = computed(() => query.data.value?.cards ?? [])
const anomalyCount = computed(() => query.data.value?.anomaly_count ?? 0)
const degraded = computed(() => query.data.value?.degraded ?? false)
</script>

<template>
  <section class="monitor">
    <header class="monitor__head">
      <h1>监控聚合</h1>
      <p
        v-if="blockState === 'ready'"
        class="monitor__summary"
        role="status"
        aria-live="polite"
      >
        <span v-if="anomalyCount" class="anomaly">⚠ 今日 {{ anomalyCount }} 项异常</span>
        <span v-else class="ok">✓ 今日无异常</span>
        <span v-if="degraded" class="muted">（部分数据源不可用）</span>
      </p>
    </header>

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="监控数据暂不可用，请稍后重试"
      @retry="query.refetch()"
    >
      <ul class="cards">
        <li v-for="card in cards" :key="card.key" class="card" :data-severity="card.severity">
          <div class="card__head">
            <span class="card__sev" :data-severity="card.severity" aria-hidden="true" />
            <span class="card__title">{{ card.title }}</span>
          </div>
          <p class="card__headline">{{ card.headline }}</p>
          <p v-if="card.detail" class="card__detail muted">{{ card.detail }}</p>
          <div class="card__links">
            <a class="card__deep" :href="card.deep_link">深钻 ↪</a>
            <a v-if="card.action" class="card__action" :href="card.action.href">
              {{ card.action.label }} ↪
            </a>
          </div>
        </li>
      </ul>
    </StateBlock>
  </section>
</template>

<style scoped>
.monitor {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.monitor__head {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  flex-wrap: wrap;
}
.monitor__summary {
  margin: 0;
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.anomaly {
  color: var(--warning);
  font-weight: 600;
}
.ok {
  color: var(--success);
  font-weight: 600;
}
.cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: 0.75rem;
}
.card {
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.card[data-severity='danger'] {
  border-left-color: var(--danger);
}
.card[data-severity='warning'] {
  border-left-color: var(--warning);
}
.card[data-severity='ok'] {
  border-left-color: var(--success);
}
.card[data-severity='info'] {
  border-left-color: var(--primary);
}
.card__head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.card__sev {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--text-secondary);
}
.card__sev[data-severity='danger'] {
  background: var(--danger);
}
.card__sev[data-severity='warning'] {
  background: var(--warning);
}
.card__sev[data-severity='ok'] {
  background: var(--success);
}
.card__title {
  font-weight: 600;
}
.card__headline {
  margin: 0;
}
.card__links {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.25rem;
  font-size: var(--text-base);
}
</style>
