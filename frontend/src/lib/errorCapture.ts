// Plan 2026-07-01-002 Unit 6 — Vue SPA failure-interception bootstrap.
//
// Five independent hooks feed into one shared capture pipeline defined in
// this module (see the plan's "High-Level Technical Design" table for why
// all five are needed — each covers a failure surface the others miss):
//   1. window 'error' (capture phase) / 'unhandledrejection' — native errors
//      Vue never schedules and so never sees (installGlobalErrorListeners).
//   2. app.config.errorHandler — component render/lifecycle/watcher/directive
//      errors (installVueErrorHandler).
//   3. router.onError() — wired from router/index.ts via reportRouterError.
//   4. QueryCache/MutationCache constructor-time onError — wired from
//      main.ts's QueryClient construction via reportQueryError /
//      reportMutationError.
//   5. Pinia $onAction onError — wired from errorCapturePlugin.ts via
//      reportPiniaActionError (vuejs/pinia#576: a store action's rejection
//      sometimes does NOT bubble to window.unhandledrejection, which is
//      exactly why this hook must exist independently of hook 1).
//
// SECURITY (see the plan's security-review note): hooks 4 and 5 naturally
// receive the raw call `variables`/`args` of the failed query/mutation/
// action, not just an error — e.g. api/settings.ts's saveLlmConfig takes a
// plaintext `api_key`. Those field names are not in the backend's
// `_SENSITIVE_KEYS` list, so this module must NEVER forward `variables`/
// `args` into the submitted payload. Only a query/mutation KEY (an
// identifier tuple, not a value payload) and the store id + action NAME are
// ever accepted by reportQueryError/reportMutationError/
// reportPiniaActionError below — there is no code path in this file that
// can reach a mutation's variables or a store action's args.
//
// Fingerprinting/noise-filtering/self-origin-guard/severity logic is shared
// with the legacy capture engine via error-capture-core.js (see that file's
// module docstring for why) — this module must not reimplement or fork it.
//
// Deliberately a plain module, not a composable: there is no reactive state
// here, only a page-lifetime dedup tracker (mirrors the legacy
// ui/error-capture.js module-level tracker).

import type { App } from 'vue'
// Cross-boundary import into the DOM-free shared decision module — the same
// precedent already used for tokens.css in vite.config.ts's `server.fs.allow`.
import {
  computeFingerprint,
  shouldIgnoreError,
  classifySeverity,
  DedupTracker,
} from '../../../webui_app/static/js/lib/error-capture-core.js'
import { sendJson } from '../api/client'
import { useNotificationsStore } from '../stores/notifications'

interface ErrorInfo {
  name: string
  message: string
  stack: string
  filename: string
  source: string
}

interface ReportPayload {
  message: string
  stack: string | null
  url: string
  source: string
  severity: string
  fingerprint: string
  reportId: string
}

const DEDUP_WINDOW_MS = 60_000
const SESSION_SUBMIT_CAP = 50

let tracker = new DedupTracker({ windowMs: DEDUP_WINDOW_MS, sessionCap: SESSION_SUBMIT_CAP })

// ── helpers ──────────────────────────────────────────────────────────────────

function currentUrl(): string {
  try {
    return window.location.href
  } catch {
    return ''
  }
}

function mintCorrelationId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    // fall through to the fallback below
  }
  return `ec-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function safeStringify(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** Build an errorInfo from any thrown/rejected value (Error instance or not). */
function toErrorInfo(error: unknown, source: string, filename = ''): ErrorInfo {
  if (error instanceof Error) {
    return {
      name: error.name || 'Error',
      message: error.message || '',
      stack: error.stack || '',
      filename,
      source,
    }
  }
  return { name: 'Error', message: safeStringify(error), stack: '', filename, source }
}

/** Render a cache key (query/mutation key — an identifier, never a value
 *  payload) as a short readable string for prefixing into the message. */
function keyToString(key: unknown): string {
  if (key == null) return ''
  try {
    const s = JSON.stringify(key)
    return s && s !== '[]' && s !== '{}' ? s : ''
  } catch {
    return ''
  }
}

function withContextPrefix(info: ErrorInfo, prefix: string): ErrorInfo {
  if (!prefix) return info
  return { ...info, message: `[${prefix}] ${info.message}` }
}

// ── payload + submission ─────────────────────────────────────────────────────

function buildPayload(errorInfo: ErrorInfo, fingerprint: string): ReportPayload {
  return {
    message: errorInfo.message || '',
    stack: errorInfo.stack || null,
    url: currentUrl(),
    // Prefixed per-hook so an operator can tell which of the five
    // interception points caught a given report (source is free-form on
    // the backend — see webui_store/error_reports.py).
    source: `vue-${errorInfo.source}`,
    severity: classifySeverity(errorInfo),
    fingerprint,
    // Client-minted, throwaway TRUTHY correlation marker (see
    // webui_app/api/v1/error_reports.py module docstring) — tells the
    // server "apply fingerprint dedup"; it is NOT the row id. The server's
    // response `id` is the only value ever surfaced to the toast/UI.
    reportId: mintCorrelationId(),
  }
}

async function submitReport(payload: ReportPayload): Promise<{ id: string } | null> {
  try {
    const result = await sendJson<{ id: string }>('POST', '/error-reports', payload, {
      keepalive: true,
    })
    return result && result.id ? result : null
  } catch {
    return null // network error, CSRF/session hiccup, non-2xx, etc.
  }
}

function notifySuccess(message: string, reportId: string): void {
  try {
    const notify = useNotificationsStore()
    // Sticky (timeout 0), matching notifications.ts's existing
    // severity === 'error' -> timeout 0 convention for auto-captured errors.
    notify.push(message || 'An error was captured and reported.', 'error', 0, reportId)
  } catch {
    // Pinia not active / notifications store unavailable — best effort only.
  }
}

async function captureAndSubmit(errorInfo: ErrorInfo): Promise<void> {
  try {
    if (shouldIgnoreError(errorInfo)) return
    const fingerprint = computeFingerprint(errorInfo)
    const decision = tracker.record(fingerprint)
    if (!decision.shouldSubmitNow) return
    const payload = buildPayload(errorInfo, fingerprint)
    const result = await submitReport(payload)
    if (result) notifySuccess(errorInfo.message || errorInfo.name, result.id)
  } catch {
    // A bug in this module's own capture/submission logic must never itself
    // become a new uncaught error — isSelfOriginatedError guards against the
    // resulting self-report loop, but only if we never let it escape here.
  }
}

// ── hook 1: window 'error' (capture phase) / 'unhandledrejection' ──────────

function isResourceErrorEvent(event: Event): boolean {
  const target = event.target as (EventTarget & { tagName?: string }) | null
  return !!target && target !== window && typeof target.tagName === 'string'
}

function onWindowError(event: Event): void {
  const errorEvent = event as ErrorEvent
  if (isResourceErrorEvent(event)) {
    const target = event.target as Element & { src?: string; href?: string; tagName?: string }
    const src = target.src || target.href || ''
    const tag = (target.tagName || '').toLowerCase()
    void captureAndSubmit({
      name: 'ResourceError',
      message: `Failed to load resource: <${tag}> ${src}`,
      stack: '',
      filename: src,
      source: 'resource-error',
    })
    return
  }
  const err = errorEvent.error as Error | undefined
  void captureAndSubmit({
    name: (err && err.name) || 'Error',
    message: errorEvent.message || (err && err.message) || '',
    stack: (err && err.stack) || '',
    filename: errorEvent.filename || '',
    source: 'window-error',
  })
}

function onUnhandledRejection(event: PromiseRejectionEvent): void {
  const reason = event.reason as unknown
  if (reason instanceof Error) {
    void captureAndSubmit({
      name: reason.name || 'UnhandledRejection',
      message: reason.message || safeStringify(reason),
      stack: reason.stack || '',
      filename: '',
      source: 'unhandled-rejection',
    })
    return
  }
  void captureAndSubmit({
    name: 'UnhandledRejection',
    message: typeof reason === 'string' ? reason : safeStringify(reason),
    stack: '',
    filename: '',
    source: 'unhandled-rejection',
  })
}

let listenersInstalled = false

/** Hook 1 — window 'error' (capture phase, needed for non-bubbling resource
 *  load failures) + 'unhandledrejection' (native, non-Vue-scheduled async
 *  rejections `app.config.errorHandler` never sees). Idempotent. */
export function installGlobalErrorListeners(): void {
  if (listenersInstalled) return
  listenersInstalled = true
  window.addEventListener('error', onWindowError, true)
  window.addEventListener('unhandledrejection', onUnhandledRejection)
}

/** Test seam: undo installGlobalErrorListeners()'s idempotency guard so a
 *  test can reinstall against a fresh set of spies. */
export function _resetGlobalErrorListenersForTest(): void {
  window.removeEventListener('error', onWindowError, true)
  window.removeEventListener('unhandledrejection', onUnhandledRejection)
  listenersInstalled = false
}

/** Test seam: reset the in-tab dedup tracker between tests. */
export function _resetCaptureStateForTest(): void {
  tracker = new DedupTracker({ windowMs: DEDUP_WINDOW_MS, sessionCap: SESSION_SUBMIT_CAP })
}

// ── hook 2: app.config.errorHandler ──────────────────────────────────────────

/** Hook 2 — component render/lifecycle/watcher/directive errors; this is
 *  the official scope of app.config.errorHandler and nothing wider. */
export function installVueErrorHandler(app: App): void {
  app.config.errorHandler = (err, _instance, info) => {
    void captureAndSubmit(toErrorInfo(err, 'error-handler'))
    if (import.meta.env.DEV) {
      console.error('[vue error]', info, err)
    }
  }
}

// ── hook 3: router.onError() ─────────────────────────────────────────────────

/** Hook 3 — navigation-guard / async-component-resolution failures, which
 *  the Router cancels before they ever reach a render/lifecycle call site
 *  (so app.config.errorHandler never sees them). Wired from
 *  router/index.ts's router.onError(). */
export function reportRouterError(error: unknown): void {
  void captureAndSubmit(toErrorInfo(error, 'router-error'))
}

// ── hook 4: QueryCache / MutationCache onError ──────────────────────────────
//
// SECURITY: these two functions accept ONLY `error` + an optional cache KEY
// (an identifier tuple, e.g. ['settings', 'llm'] — never the query/mutation
// call's `variables`/`args`, which may carry plaintext secrets such as
// api/settings.ts's saveLlmConfig `api_key`). Callers in main.ts must not
// pass anything else through, and no other parameter is accepted here.

/** Hook 4a — QueryCache constructor onError (useQuery fetcher failures that
 *  TanStack Query v5 stores on query state instead of re-throwing). */
export function reportQueryError(error: unknown, queryKey?: unknown): void {
  const info = withContextPrefix(toErrorInfo(error, 'query-error'), keyToString(queryKey))
  void captureAndSubmit(info)
}

/** Hook 4b — MutationCache constructor onError (useMutation failures).
 *  `mutationKey` must be the mutation's KEY only — never its `variables`. */
export function reportMutationError(error: unknown, mutationKey?: unknown): void {
  const info = withContextPrefix(toErrorInfo(error, 'mutation-error'), keyToString(mutationKey))
  void captureAndSubmit(info)
}

// ── hook 5: Pinia $onAction onError ──────────────────────────────────────────
//
// SECURITY: accepts ONLY the store id + action NAME + the error — never the
// action's call `args` (vuejs/pinia#576: some store action rejections don't
// bubble to window.unhandledrejection, which is why this hook must exist
// independently of hook 1). Wired from errorCapturePlugin.ts.

/** Hook 5 — Pinia store action rejection. */
export function reportPiniaActionError(storeId: string, actionName: string, error: unknown): void {
  const info = withContextPrefix(toErrorInfo(error, 'pinia-action-error'), `${storeId}.${actionName}`)
  void captureAndSubmit(info)
}
