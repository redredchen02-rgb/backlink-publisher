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
}

export interface HistoryList {
  items: HistoryItem[]
}

export interface HistoryMutationResult {
  items: HistoryItem[]
  message?: string
}

export const listHistory = (): Promise<HistoryList> => getJson('/history')

export const deleteHistory = (id: string): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/delete', { id })

export const bulkDeleteHistory = (ids: string[]): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/bulk-delete', { ids })

export const purgeFailedHistory = (): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/purge-failed', {})

export const recheckHistory = (id: string): Promise<HistoryMutationResult> =>
  sendJson('POST', '/history/recheck', { id })
