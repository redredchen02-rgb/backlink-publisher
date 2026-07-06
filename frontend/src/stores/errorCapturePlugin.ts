// Plan 2026-07-01-002 Unit 6 — Pinia global error-capture plugin (hook 5).
//
// Pinia has no built-in global error hook, and a store action's rejected
// promise is known to sometimes NOT bubble to window.unhandledrejection
// (vuejs/pinia#576) — installGlobalErrorListeners() alone would silently
// miss those. This plugin calls `store.$onAction` for every store created
// under the Pinia instance it's registered on, so every action's failure
// path is observed regardless of whether it happens to also reject a
// top-level promise.
//
// SECURITY: only the store id, the action NAME, and the error itself are
// forwarded to errorCapture.ts's reportPiniaActionError — never `args` (the
// action's raw call arguments), which may carry plaintext secrets (e.g. a
// settings-store action wrapping api/settings.ts's saveLlmConfig, whose
// `api_key` argument must never reach the submitted report).
//
// Usage: `pinia.use(errorCapturePlugin)` before `app.use(pinia)` (see main.ts).

import type { PiniaPluginContext } from 'pinia'
import { reportPiniaActionError } from '../lib/errorCapture'

export function errorCapturePlugin({ store }: PiniaPluginContext): void {
  store.$onAction(({ name, onError }) => {
    onError((error) => {
      reportPiniaActionError(store.$id, name, error)
    })
  })
}
