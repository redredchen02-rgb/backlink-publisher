// Notifications store — Plan 2026-06-18-002 U4.
//
// Replaces the legacy 700-line notifications.js (which violated the anti-rot
// rules: innerHTML splicing + a `window.notifications` global, and had no
// subscription contract). This Pinia store IS the subscription contract: any
// component reads the reactive `toasts` list; `push`/`dismiss` are the only
// mutators. No window.* global; no innerHTML (Toast.vue renders via textContent
// through Vue's default escaping).

import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Severity = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: number
  severity: Severity
  message: string
  /** ms before auto-dismiss; 0 = sticky (errors stay until dismissed). */
  timeout: number
  /** The server-persisted error-report row id (Plan 2026-07-01-002 U3's
   *  POST /api/v1/error-reports response `id` — NOT the client-minted
   *  request-side `reportId` correlation marker). Set only on toasts raised
   *  by an auto-captured, successfully-submitted error report (U6); Unit 7's
   *  "补充说明" action uses this to PATCH the right row. */
  reportId?: string
  /** Optional single-shot reversal action rendered as a button on the toast
   *  (Plan 2026-07-06-004 Unit 6) — e.g. "撤销" after the monitor dashboard's
   *  mark-resolved action. Distinct from `reportId`'s "补充说明" button: this
   *  is a generic caller-supplied callback, not tied to the shared
   *  ReportProblemPanel. The callback itself owns its own error handling
   *  (e.g. re-PATCHing a since-deleted row) — this store just renders the
   *  button and lets the click fire it; a stale/expired undo (toast already
   *  auto-dismissed, or state changed via another path) is the callback's
   *  problem to degrade gracefully, not this store's. */
  undoAction?: { label: string; onClick: () => void }
}

/** Map the legacy server flash_type vocabulary onto Toast severities, so flash
 *  messages emitted by not-yet-migrated Jinja pages render consistently when the
 *  SPA surfaces them (dual-stack flash->Toast bridge). */
export function flashTypeToSeverity(flashType: string | null | undefined): Severity {
  switch ((flashType || '').toLowerCase()) {
    case 'success':
      return 'success'
    case 'danger':
    case 'error':
      return 'error'
    case 'warning':
    case 'warn':
      return 'warning'
    default:
      return 'info'
  }
}

let _seq = 0

export const useNotificationsStore = defineStore('notifications', () => {
  const toasts = ref<Toast[]>([])

  function push(
    message: string,
    severity: Severity = 'info',
    timeout = severity === 'error' ? 0 : 4000,
    reportId?: string,
    undoAction?: { label: string; onClick: () => void },
  ): number {
    const id = ++_seq
    toasts.value.push({ id, severity, message, timeout, reportId, undoAction })
    return id
  }

  function dismiss(id: number): void {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  function clear(): void {
    toasts.value = []
  }

  /** Bridge a legacy {flash_msg, flash_type} payload into a toast. */
  function pushFlash(flashMsg: string, flashType?: string): number | null {
    if (!flashMsg) return null
    return push(flashMsg, flashTypeToSeverity(flashType))
  }

  return { toasts, push, dismiss, clear, pushFlash }
})
