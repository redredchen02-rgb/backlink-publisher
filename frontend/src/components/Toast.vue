<script setup lang="ts">
// Toast host — renders the notifications store into an aria-live region so
// screen readers announce transient feedback (a11y half of the subscription
// contract). Messages render via {{ }} (Vue escaping) — never innerHTML.
import { watch } from 'vue'
import { useNotificationsStore, type Toast } from '../stores/notifications'

const store = useNotificationsStore()
const timers = new Map<number, ReturnType<typeof setTimeout>>()

// Arm auto-dismiss for any toast with a positive timeout (errors are sticky).
watch(
  () => store.toasts.slice(),
  (toasts: Toast[]) => {
    for (const t of toasts) {
      if (t.timeout > 0 && !timers.has(t.id)) {
        timers.set(
          t.id,
          setTimeout(() => {
            store.dismiss(t.id)
            timers.delete(t.id)
          }, t.timeout),
        )
      }
    }
  },
  { deep: false },
)
</script>

<template>
  <div class="toast-host" role="region" aria-label="通知">
    <div
      v-for="t in store.toasts"
      :key="t.id"
      class="toast"
      :class="`toast--${t.severity}`"
      :role="t.severity === 'error' ? 'alert' : 'status'"
      aria-live="polite"
    >
      <span class="toast__msg">{{ t.message }}</span>
      <button type="button" class="toast__close" aria-label="关闭" @click="store.dismiss(t.id)">
        ×
      </button>
    </div>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 1200;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 22rem;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.6rem 0.75rem;
  border-radius: var(--radius-md);
  background: var(--surface-overlay);
  border-left: 3px solid var(--info);
  color: var(--text-primary);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}
.toast--success {
  border-left-color: var(--success);
}
.toast--error {
  border-left-color: var(--danger);
}
.toast--warning {
  border-left-color: var(--warning);
}
.toast__msg {
  flex: 1;
  font-size: var(--text-base);
}
.toast__close {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--text-lg);
  line-height: 1;
}
</style>
