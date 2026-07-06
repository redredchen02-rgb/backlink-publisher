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
  /** Set only by the `?include_deleted=window` read path (W4/D18) — ISO-8601
   *  UTC timestamp of the soft-delete, present while the row is still within
   *  the undo window. Absent/undefined on live rows. */
  deleted_at?: string | null
}

export interface HistoryList {
  items: HistoryItem[]
}

export interface HistoryMutationResult {
  items: HistoryItem[]
  message?: string
  /** bulk-delete only (W4 `/history/bulk-delete` response) — how many of the
   *  submitted ids were actually soft-deleted vs. already gone/deleted. */
  deleted?: number
  skipped?: number
}

export const listHistory = (): Promise<HistoryList> => getJson('/history')

/** W4/D18 read path: returns ONLY rows soft-deleted within the undo window
 *  (each with `deleted_at` populated), never mixed with live rows. Used by
 *  HistoryPage (W5) so a refetch or remount mid-undo-window still renders
 *  the "deleted · undo" row instead of it silently vanishing. */
export const listHistoryDeletedWindow = (): Promise<HistoryList> =>
  getJson('/history?include_deleted=window')

export const deleteHistory = (id: string): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/delete', { id })

/** W4 `/history/undelete` — restores a soft-deleted row within the purge
 *  window. 404s (surfaced as ApiError) for an id that never existed, was
 *  never deleted, or already aged past the purge window. */
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
