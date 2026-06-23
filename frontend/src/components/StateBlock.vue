<script setup lang="ts">
// Four-state matrix (design-lens UX-continuity convention) — the single shared
// way every migrated page renders loading / empty / error / ready. Server-rendered
// pages had no loading gap; fetch-based pages do, so this is the regression guard.
// Error copy comes from the classifyError taxonomy (fixed templates, never raw
// server text). 'stale' is handled by callers via TanStack Query keep-previous-data.
import { computed } from 'vue'
import { classifyError, type Classified } from '../lib/errors'

const props = withDefaults(
  defineProps<{
    state: 'loading' | 'empty' | 'error' | 'ready'
    error?: unknown
    emptyText?: string
    retryable?: boolean
  }>(),
  { emptyText: '暂无数据', retryable: true },
)

const emit = defineEmits<{ retry: [] }>()

const classified = computed<Classified | null>(() =>
  props.state === 'error' ? classifyError(props.error) : null,
)
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

  <slot v-else />
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
  border-radius: 4px;
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
.state__title {
  font-weight: 600;
  margin: 0 0 0.25rem;
}
</style>
