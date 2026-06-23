// Typed wrappers for the /api/v1/drafts* endpoints (Plan 2026-06-18-002 U7).
// Every mutation returns the refreshed list (message may be a warning when a
// scheduled job lingered but the draft itself was cancelled/deleted).

import { getJson, sendJson } from './client'

export interface DraftItem {
  id: string
  target_url: string
  platform?: string
  language?: string
  publish_mode?: string
  status?: string
  scheduled_at?: string | null
  created_at?: string
  article_urls?: string[]
  error?: string | null
}

export interface DraftList {
  items: DraftItem[]
}

export interface DraftMutationResult {
  items: DraftItem[]
  message?: string
}

export const listDrafts = (): Promise<DraftList> => getJson('/drafts')

export const scheduleDraft = (id: string, scheduled_at: string): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/schedule', { id, scheduled_at })

export const publishDraftNow = (id: string): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/publish-now', { id })

export const cancelDraft = (id: string): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/cancel', { id })

export const deleteDraft = (id: string): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/delete', { id })

export const bulkDeleteDrafts = (ids: string[]): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/bulk-delete', { ids })
