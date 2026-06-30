<script setup lang="ts">
// Survival dashboard — Plan P13 B1 (SPA migration).
import { computed, onMounted, ref } from 'vue'
import { fetchSurvival, type SurvivalView } from '../../api/survival'
import StateBlock from '../../components/StateBlock.vue'

const view = ref<SurvivalView | null>(null)
const error = ref<Error | null>(null)
const loading = ref(true)

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (!view.value || view.value.state === 'empty') return 'empty'
  return 'ready'
})

const numberClass = computed(() => {
  if (!view.value?.has_rate || view.value.survival_rate == null) return 'surv-number--muted'
  const pct = view.value.survival_rate * 100
  if (pct >= 80) return 'surv-number--good'
  if (pct >= 50) return 'surv-number--warn'
  return 'surv-number--bad'
})

const load = async () => {
  loading.value = true
  error.value = null
  try {
    view.value = await fetchSurvival()
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="surv-page">
    <header class="surv-title-row">
      <h1 class="surv-title">鏈接存活率</h1>
      <a href="/app/keep-alive" class="btn btn-sm btn-outline-light btn-outline-glass">
        <i class="bi bi-shield-check me-1" />保活看板
      </a>
    </header>

    <StateBlock
      :state="blockState"
      :error="error"
      empty-text="暂无成熟外链。发布 30 天后的外链将纳入统计。"
      @retry="load"
    >
      <section class="surv-card" aria-label="存活率概覽">
        <p class="surv-headline">
          {{ view?.headline ?? '—' }}（近 {{ view?.cohort_days ?? 30 }} 天成熟樣本）
        </p>

        <div :class="['surv-number', numberClass]">{{ view?.display ?? '—' }}</div>
        <p class="surv-sub">{{ view?.sub ?? '' }}</p>

        <span v-if="view?.stale" class="surv-flag">
          <i class="bi bi-exclamation-triangle-fill" />
          部分樣本：{{ view?.stale_count }} 條成熟鏈接待巡检（最久 {{ view?.stale_days }} 天）
        </span>

        <dl class="surv-meta">
          <div><dt>樣本數</dt><dd>{{ view?.sample_size ?? 0 }}</dd></div>
          <div><dt>存活</dt><dd>{{ view?.survived ?? 0 }}</dd></div>
          <div><dt>成熟中</dt><dd>{{ view?.maturing_count ?? 0 }}</dd></div>
        </dl>
      </section>

      <p class="surv-note">
        存活率 = 已發布滿 {{ view?.cohort_days ?? 30 }} 天、最近一次巡检判定仍 live + dofollow 的鏈接佔比。
        數據來自每週自動巡检（link.rechecked）。樣本不足 2 條時不顯示百分比。
      </p>
    </StateBlock>
  </section>
</template>

<style scoped>
.surv-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.surv-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.surv-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.surv-card {
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  padding: 2rem;
  box-shadow: var(--shadow-glass);
}
.surv-headline {
  font-size: 0.9rem;
  color: var(--text-secondary);
  margin: 0 0 0.5rem;
}
.surv-number {
  font-size: 4rem;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 0.25rem;
}
.surv-number--muted { color: rgba(255,255,255,0.35); }
.surv-number--good  { color: #34d399; }
.surv-number--warn  { color: #fbbf24; }
.surv-number--bad   { color: #f87171; }
.surv-sub {
  color: var(--text-secondary);
  font-size: 0.88rem;
  margin-top: 0.4rem;
  margin-bottom: 1rem;
}
.surv-meta {
  display: flex;
  gap: 1.5rem;
  flex-wrap: wrap;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255,255,255,0.10);
  font-size: 0.85rem;
}
.surv-meta div {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.surv-meta dt { color: var(--text-secondary); }
.surv-meta dd {
  font-weight: 700;
  margin: 0;
  font-size: 1.1rem;
}
.surv-flag {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.75rem;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  background: rgba(245,158,11,0.18);
  color: #fcd34d;
  border: 1.5px solid rgba(245,158,11,0.45);
}
.surv-note {
  font-size: 0.82rem;
  color: var(--text-secondary);
  line-height: 1.6;
}
</style>
