<script setup lang="ts">
// Four-state matrix (design-lens UX-continuity convention) — the single shared
// way every migrated page renders loading / empty / error / ready. Server-rendered
// pages had no loading gap; fetch-based pages do, so this is the regression guard.
// Error copy comes from the classifyError taxonomy (fixed templates, never raw
// server text). 'stale' is handled by callers via TanStack Query keep-previous-data.
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { classifyError, type Classified } from '../lib/errors'

const props = withDefaults(
  defineProps<{
    state: 'loading' | 'empty' | 'error' | 'ready'
    error?: unknown
    emptyText?: string
    retryable?: boolean
    /** True while a background refetch is in flight (keepPreviousData pattern). */
    isFetching?: boolean
    /** True when data is stale (TanStack isStale). Shows last-updated hint. */
    stale?: boolean
    /** ISO timestamp of last successful fetch for the stale hint. */
    lastUpdated?: string
  }>(),
  { emptyText: '暂无数据', retryable: true, isFetching: false, stale: false },
)

const emit = defineEmits<{ retry: [] }>()

const classified = computed<Classified | null>(() =>
  props.state === 'error' ? classifyError(props.error) : null,
)

// Reactive clock for fmtRelative — updates every 60 s so the relative
// timestamp re-renders without user interaction. Only ticks while mounted.
const now = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | undefined
onMounted(() => { ticker = setInterval(() => { now.value = Date.now() }, 60_000) })
onUnmounted(() => { clearInterval(ticker) })

function fmtRelative(iso: string): string {
  const ms = new Date(iso).getTime()
  if (!Number.isFinite(ms)) return '—'
  const diff = Math.floor((now.value - ms) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  return `${Math.floor(diff / 3600)} 小时前`
}
</script>

<template>
  <div v-if="state === 'loading'" class="state state--loading" aria-busy="true">
    <span class="skeleton" /><span class="skeleton" /><span class="skeleton" />
  </div>

  <div v-else-if="state === 'empty'" class="state state--empty">
    <p class="muted">{{ emptyText }}</p>
    <slot name="empty-action" />
  </div>

  <div v-else-if="state === 'error'" class="state state--error" role="alert">
    <p class="state__title">{{ classified?.title }}</p>
    <p class="muted">{{ classified?.message }}</p>
    <button v-if="retryable && classified?.retryable" type="button" @click="emit('retry')">
      重试
    </button>
  </div>

  <template v-else>
    <!-- Stale / refreshing strip — aria-live container is always present in the DOM
         so screen readers have already registered it before content changes (WCAG). -->
    <div class="state__stalebar" role="status" aria-live="polite">
      <template v-if="isFetching || stale">
        <span v-if="isFetching" class="state__pulse" aria-hidden="true" />
        <span class="state__stale-text">
          <template v-if="isFetching">更新中…</template>
          <template v-else-if="stale && lastUpdated">最后更新：{{ fmtRelative(lastUpdated) }}</template>
          <template v-else-if="stale">数据可能不是最新</template>
        </span>
      </template>
    </div>
    <slot />
  </template>
</template>

<style scoped>
.state {
  padding: 1rem 0;
}
.state--loading {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.skeleton {
  height: 1rem;
  border-radius: var(--radius-sm);
  background: linear-gradient(
    90deg,
    var(--surface-raised) 25%,
    var(--surface-overlay) 50%,
    var(--surface-raised) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.2s infinite;
}
.skeleton:nth-child(2) {
  width: 80%;
}
.skeleton:nth-child(3) {
  width: 60%;
}
@keyframes shimmer {
  to {
    background-position: -200% 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton { animation: none; }  /* static gradient, no motion */
}
.state__title {
  font-weight: var(--font-weight-semibold);
  margin: 0 0 0.25rem;
}
.state__stalebar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0 var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  min-height: 1rem;  /* keeps layout stable when empty */
}
.state__pulse {
  display: inline-block;
  width: 0.5rem;
  height: 0.5rem;
  border-radius: var(--radius-pill);
  background: var(--primary);
  animation: state-pulse 1s ease-in-out infinite;
}
@keyframes state-pulse {
  0%, 100% { opacity: 0.5; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .state__pulse { animation: none; opacity: 0.7; }
}
</style>
