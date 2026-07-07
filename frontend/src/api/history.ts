// Typed wrappers for the /api/v1/history* endpoints (Plan 2026-06-18-002 U7).
// Every mutation returns the refreshed list, so callers replace their cache with
// the response rather than re-fetching.

import { getJson, sendJson } from './client'

export interface HistoryItem {
  id: string
  target_url: string
  created_at?: string
  platform?: string
  status?: string
  article_urls?: string[]
  run_id?: string
  language?: string
  error?: string
  verified_at?: number | null
  publish_mode?: string
  target_dofollow?: string
  // W4/W5: only populated on rows returned by `?include_deleted=window` --
  // the ISO timestamp the row was soft-deleted at, used to compute the
  // undo window's *remaining* time (rather than restarting a fresh timer)
  // when a page reload rediscovers a still-pending row.
  deleted_at?: string | null
}

export interface HistoryList {
  items: HistoryItem[]
  // Plan 2026-07-02-001 U5: present only when the request included `limit`.
  total?: number
  limit?: number
  offset?: number
}

export interface HistoryMutationResult {
  items: HistoryItem[]
  message?: string
  // W4 bulk-delete only: honest per-call counts (additive, oasdiff-safe) --
  // a partially-stale selection (some ids already gone) reports exactly how
  // many were actually deleted vs skipped instead of an all-or-nothing result.
  deleted?: number
  skipped?: number
}

export const listHistory = (params?: { limit?: number; offset?: number }): Promise<HistoryList> => {
  if (params?.limit == null) return getJson('/history')
  const qs = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset ?? 0),
  })
  return getJson(`/history?${qs}`)
}

/**
 * W4/W5 — unpaginated: only soft-deleted rows still within the undo window,
 * each carrying `deleted_at`. Intentionally never combined with `?limit=&
 * offset=` (see webui_app/api/v1/history.py's `history_list` docstring).
 */
export const listHistoryDeletedWindow = (): Promise<HistoryList> =>
  getJson('/history?include_deleted=window')

export const deleteHistory = (id: string): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/delete', { id })

/** W4/W5 — restore a soft-deleted row still within the undo window. 404s
 *  (aged past the window / never deleted / unknown id) reject as an
 *  `ApiError`, same as every other mutation here. */
export const undeleteHistory = (id: string): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/undelete', { id })

export const bulkDeleteHistory = (ids: string[]): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/bulk-delete', { ids })

export const purgeFailedHistory = (): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/purge-failed', {})

export const recheckHistory = (id: string): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/recheck', { id })

export const bulkRecheckHistory = (ids: string[]): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/bulk-recheck', { ids })
