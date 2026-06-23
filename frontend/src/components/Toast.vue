<script setup lang="ts">
// Toast host — renders the notifications store into aria-live regions so
// screen readers announce transient feedback. Two separate regions required:
// aria-live="assertive" for errors (interrupt immediately) vs "polite" for
// success/info/warning (next idle). Dynamic per-item aria-live changes don't
// work — the attribute must be on a static container present at page load.
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
  <div class="toast-host">
    <!-- Error: assertive — screen reader interrupts immediately -->
    <div aria-live="assertive" aria-atomic="false" class="toast-region">
      <div
        v-for="t in store.toasts.filter(t => t.severity === 'error')"
        :key="t.id"
        class="toast toast--error"
        role="alert"
      >
        <span class="toast__msg">{{ t.message }}</span>
        <button type="button" class="toast__close" aria-label="关闭" @click="store.dismiss(t.id)">×</button>
      </div>
    </div>
    <!-- Non-error: polite — announced at next idle -->
    <div aria-live="polite" aria-atomic="false" class="toast-region">
      <div
        v-for="t in store.toasts.filter(t => t.severity !== 'error')"
        :key="t.id"
        class="toast"
        :class="`toast--${t.severity}`"
        role="status"
      >
        <span class="toast__msg">{{ t.message }}</span>
        <button type="button" class="toast__close" aria-label="关闭" @click="store.dismiss(t.id)">×</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: var(--space-4);
  right: var(--space-4);
  z-index: 1200;
  max-width: 22rem;
  pointer-events: none;
}
.toast-region {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  pointer-events: auto;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--control-pad-y) var(--space-3);
  border-radius: var(--radius-lg);
  background: var(--surface-overlay);
  border-left: 3px solid var(--info);
  color: var(--text-primary);
  box-shadow: var(--shadow-glass);
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
  padding: 0;
}
</style>
