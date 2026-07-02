// Typed wrappers for the /api/v1/error-reports* endpoints (Plan
// 2026-07-01-002 Unit 8 — the SPA "error reports" dashboard).
//
// Backend contract (Unit 3, webui_app/api/v1/error_reports.py):
//  - GET  /error-reports              -> { items, total } (total is the count
//         BEFORE limit/offset are applied, so pagination math is possible).
//         Unrecognized filter values fail-soft to zero rows, never a 400.
//  - GET  /error-reports/<id>         -> the report dict, or a 404 problem+json.
//  - PATCH /error-reports/<id>        -> the updated report dict.
//  - DELETE /error-reports/<id>       -> { ok: true, id }.
//
// The report dict's free-text fields (message/stack/url/user_description) are
// whatever Unit 1's sanitizer produced from the client submission — this
// module deliberately does NOT declare them as required, since a given report
// may be missing any of them (e.g. a manual report has no `stack`).

import { getJson, sendJson } from './client'

export type ErrorReportStatus = 'open' | 'acknowledged' | 'resolved'

export interface ErrorReportItem {
  id: string
  status: ErrorReportStatus
  severity?: string
  source?: string
  fingerprint?: string
  occurrences?: number
  created_at?: string
  updated_at?: string
  last_seen_at?: string
  message?: string
  stack?: string | null
  url?: string
  user_description?: string
  sanitize_degraded?: boolean
  // Sanitized payloads may carry additional free-form fields this module
  // does not need to name individually.
  [extra: string]: unknown
}

export interface ErrorReportList {
  items: ErrorReportItem[]
  total: number
}

export interface ErrorReportFilters {
  status?: string
  severity?: string
  source?: string
  fingerprint?: string
  since?: string
  until?: string
  limit?: number
  offset?: number
}

export interface ErrorReportPatch {
  description?: string
  status?: ErrorReportStatus
}

export interface DeleteErrorReportResult {
  ok: boolean
  id: string
}

function buildQuery(filters?: ErrorReportFilters): string {
  if (!filters) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export const listErrorReports = (filters?: ErrorReportFilters): Promise<ErrorReportList> =>
  getJson(`/error-reports${buildQuery(filters)}`)

export const getErrorReport = (id: string): Promise<ErrorReportItem> =>
  getJson(`/error-reports/${encodeURIComponent(id)}`)

export const updateErrorReport = (
  id: string,
  patch: ErrorReportPatch,
): Promise<ErrorReportItem> => sendJson('PATCH', `/error-reports/${encodeURIComponent(id)}`, patch)

export const deleteErrorReport = (id: string): Promise<DeleteErrorReportResult> =>
  sendJson('DELETE', `/error-reports/${encodeURIComponent(id)}`)
