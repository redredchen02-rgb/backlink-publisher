// Typed wrapper for the /api/v1/monitor aggregate (Plan 2026-06-18-002 U6).
// The severity + equity-gap are computed server-side (single source); the SPA
// only displays the cards in the order the server already ranked them.
//
// Plan 2026-07-06-004 Unit 6 adds the write-side calls the interactive
// dashboard needs: queue-task retry (a genuine /api/v1 endpoint, so it uses
// getJson/sendJson's automatic '/api/v1' prefix) and channel re-verify (a
// LEGACY route OUTSIDE that prefix — see verifyChannel()'s own comment for
// why it can't just call sendJson()). Mark-resolved/undo for error-report
// items reuses api/errorReports.ts's existing updateErrorReport() directly —
// no new function needed for that action.

import { ApiError, csrfToken, getJson, sendJson } from './client'

export type Severity = 'danger' | 'warning' | 'ok' | 'info'

export interface MonitorAction {
  label: string
  href: string
}

// One individual item inside a hybrid card's `items` list (Plan
// 2026-07-06-004 Unit 2 K1: error-reports backlog + schedule/queue backlog).
// `item_type` is the discriminator the UI switches on; fields that don't
// apply to a given item_type are simply blank/absent rather than null-padded.
export type MonitorCardItemType = 'error_report' | 'scheduled_draft' | 'queue_task'

export interface MonitorCardItem {
  id: string
  item_type: MonitorCardItemType
  status?: string
  headline: string
  detail: string
  severity?: string | null
  occurrences?: number | null
}

export interface MonitorCard {
  key: string
  title: string
  severity: Severity
  headline: string
  detail: string
  deep_link: string
  action: MonitorAction | null
  // Present (possibly empty) only on the two hybrid cards (error_reports,
  // schedule_queue); absent on the 4 original aggregate-only cards.
  items?: MonitorCardItem[]
  // Present (possibly empty) only on the credentials card (Plan
  // 2026-07-06-004 Unit 6) — the structured channel-name list backing the
  // per-channel "重新验证" buttons. `detail` already carries a "、"-joined
  // display string of the same names; this is the machine-usable twin.
  failed_channels?: string[]
}

export interface MonitorSummary {
  cards: MonitorCard[]
  anomaly_count: number
  degraded: boolean
}

export const monitorSummary = (): Promise<MonitorSummary> => getJson('/monitor/summary')

// Plan 2026-07-06-005 W8 (R8): shared query-key constant so SideNav.vue's
// anomaly badge and pages/Monitor/MonitorDashboard.vue's own poll read the
// SAME TanStack Query cache entry (keys are matched by deep-equality on the
// array's contents, not by reference — no import wiring required for the
// sharing itself to work). MonitorDashboard.vue is out of this unit's scope
// (owned by a parallel unit) and still defines its own literal
// `['monitor-summary']` locally; that file was deliberately left untouched,
// so if its literal ever drifts from this constant's value the cache-sharing
// silently stops (no compile-time link between the two) — flagged here so a
// future edit to either site notices the coupling.
export const MONITOR_SUMMARY_QUERY_KEY = ['monitor-summary'] as const

// ── Queue-task retry (Plan 2026-07-06-004 Unit 3 endpoint, Unit 6 caller) ────
//
// A genuine /api/v1 endpoint, so sendJson's automatic API_BASE prefix applies
// directly. Success means "re-queued", NOT "published" — see the caller
// (MonitorDashboard.vue) for why a successful retry must NOT remove the item
// from its card's local list.

export interface QueueRetryResult {
  ok: boolean
  error_code?: string
  flash_type?: string
  flash_msg?: string
  message?: string
}

export const retryQueueTask = (taskId: string): Promise<QueueRetryResult> =>
  sendJson('POST', `/queue/${encodeURIComponent(taskId)}/retry`)

// ── Channel re-verify (Plan 2026-07-06-004 Unit 3's settings_basic.py) ───────
//
// `POST /api/<channel>/verify` is a LEGACY-namespaced route, not a `/api/v1`
// endpoint — client.ts's getJson/sendJson always prepend API_BASE ('/api/v1'),
// so calling it through them would silently hit the wrong URL
// (`/api/v1/<channel>/verify`, which doesn't exist). This reuses client.ts's
// exported `csrfToken()` (same token cache + 403-rotation contract sendJson
// uses internally) but issues its own `fetch()` against the absolute legacy
// path, mirroring keepAlive.ts's existing pattern for the same kind of
// legacy-route call.

export interface ChannelVerifyResult {
  ok: boolean
  identity: string | null
  last_verified_at: string | null
  last_verify_result: string | null
  blockers: string[]
  dofollow: boolean | string | null
}

async function _verifyFetch(channel: string, token: string): Promise<Response> {
  return fetch(`/api/${encodeURIComponent(channel)}/verify`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      'X-CSRFToken': token,
    },
  })
}

export async function verifyChannel(channel: string): Promise<ChannelVerifyResult> {
  let resp = await _verifyFetch(channel, await csrfToken())
  if (resp.status === 403) {
    // Token may have rotated — drop the cached one and retry once with a fresh.
    resp = await _verifyFetch(channel, await csrfToken(true))
  }
  if (!resp.ok) {
    let payload: unknown = null
    try {
      payload = await resp.json()
    } catch {
      /* non-JSON body (e.g. an HTML 404 from an unknown channel) */
    }
    const detail =
      (payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as Record<string, unknown>).detail)
        : '') || `HTTP ${resp.status}`
    throw new ApiError(detail, resp.status, payload)
  }
  return (await resp.json()) as ChannelVerifyResult
}
