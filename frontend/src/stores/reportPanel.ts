// Shared open/reportId state for ReportProblemPanel.vue — Plan
// 2026-07-01-002 Unit 7.
//
// TopBar.vue's nav-bar "report a problem" button and Toast.vue's per-toast
// "补充说明" action are SIBLINGS under AppShell.vue (not parent/child), so
// they need a shared contract to open the very same panel instance rather
// than each mounting its own. Mirrors notifications.ts's own documented
// rationale ("This Pinia store IS the subscription contract") — a Pinia
// store, not a window.* global or a DOM CustomEvent bridge, is this
// codebase's established cross-component mechanism for the Vue SPA.

import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useReportPanelStore = defineStore('reportPanel', () => {
  const isOpen = ref(false)
  /** The server-persisted error-report row id (see notifications.ts's Toast
   *  `reportId` doc). Present -> PATCH path (add detail to that report);
   *  absent -> POST path (fresh manual report). */
  const reportId = ref<number | undefined>(undefined)

  /** Open the panel. Pass the toast's `reportId` to switch to the PATCH
   *  "补充说明" path; call with no argument for the manual nav-bar POST path. */
  function open(id?: number): void {
    reportId.value = id
    isOpen.value = true
  }

  function close(): void {
    isOpen.value = false
    reportId.value = undefined
  }

  return { isOpen, reportId, open, close }
})
