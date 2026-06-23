// Shared error-toast composable — collapses the repeated 4-line pattern:
//   const c = classifyError(err); notify.push(`${c.title}：${c.message}`, 'error')
// into a single call: toastError(err)
//
// Invariant: never renders raw server text — classifyError maps to fixed templates.

import { useNotificationsStore } from '../stores/notifications'
import { classifyError } from '../lib/errors'

export function useErrorToast() {
  const notify = useNotificationsStore()

  /** Classify err and push a sticky error toast. */
  function toastError(err: unknown): void {
    const c = classifyError(err)
    notify.push(`${c.title}：${c.message}`, 'error')
  }

  return { toastError }
}
