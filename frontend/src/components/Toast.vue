<script setup lang="ts">
// Toast host — renders the notifications store into aria-live regions so
// screen readers announce transient feedback. Two separate regions required:
// aria-live="assertive" for errors (interrupt immediately) vs "polite" for
// success/info/warning (next idle). Dynamic per-item aria-live changes don't
// work — the attribute must be on a static container present at page load.
// Unit 7 adds a "补充说明" (add detail) action for any toast carrying a
// `reportId` (set only on toasts raised from a successfully-submitted,
// auto-captured error report — see notifications.ts's Toast doc). Clicking
// it opens the shared ReportProblemPanel (stores/reportPanel.ts) pre-filled
// with that report's id, switching its submit path to PATCH.
//
// Plan 2026-07-06-004 Unit 6 adds a second, independent action: a toast
// carrying `undoAction` renders its own button (e.g. "撤销" after the monitor
// dashboard's mark-resolved). It fires the caller-supplied `onClick`
// directly — this component has no opinion on what "undo" means, unlike the
// reportId button's hardcoded ReportProblemPanel wiring.
import { watch, onUnmounted } from 'vue'
import { useNotificationsStore, type Toast } from '../stores/notifications'
import { useReportPanelStore } from '../stores/reportPanel'

const store = useNotificationsStore()
const reportPanel = useReportPanelStore()
const timers = new Map<number, ReturnType<typeof setTimeout>>()

// Arm auto-dismiss for any toast with a positive timeout (errors are sticky).
watch(
  () => store.toasts.slice(),
  (toasts: Toast[]) => {
    // Cancel timers for manually-dismissed toasts (prevents orphaned handles)
    for (const [id, handle] of timers) {
      if (!toasts.find(t => t.id === id)) {
        clearTimeout(handle)
        timers.delete(id)
      }
    }
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

onUnmounted(() => { timers.forEach(clearTimeout); timers.clear() })
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
        <button
          v-if="t.reportId"
          type="button"
          class="toast__detail"
          @click="reportPanel.open(t.reportId)"
        >补充说明</button>
        <button
          v-if="t.undoAction"
          type="button"
          class="toast__undo"
          @click="t.undoAction.onClick()"
        >{{ t.undoAction.label }}</button>
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
        <button
          v-if="t.reportId"
          type="button"
          class="toast__detail"
          @click="reportPanel.open(t.reportId)"
        >补充说明</button>
        <button
          v-if="t.undoAction"
          type="button"
          class="toast__undo"
          @click="t.undoAction.onClick()"
        >{{ t.undoAction.label }}</button>
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
.toast__detail,
.toast__undo {
  background: none;
  border: none;
  color: var(--info);
  cursor: pointer;
  font-size: var(--text-sm);
  padding: 0;
  white-space: nowrap;
  text-decoration: underline;
}
</style>
