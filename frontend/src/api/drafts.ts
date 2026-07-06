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
  // Plan 2026-07-02-001 U5: present only when the request included `limit`.
  total?: number
  limit?: number
  offset?: number
}

export interface DraftMutationResult {
  items: DraftItem[]
  message?: string
}

export const listDrafts = (params?: { limit?: number; offset?: number }): Promise<DraftList> => {
  if (params?.limit == null) return getJson('/drafts')
  const qs = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset ?? 0),
  })
  return getJson(`/drafts?${qs}`)
}

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

// Single-flight on the backend: a concurrent call while one is still executing
// rejects with ApiError (status 409, payload.error_class === 'already_running')
// rather than queuing -- callers should disable the trigger button while a call
// is in flight to avoid surfacing that as a user-facing error unnecessarily.
export const bulkPublishDraftsNow = (ids: string[]): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/bulk-publish-now', { ids })

export const bulkCancelDrafts = (ids: string[]): Promise<DraftMutationResult> =>
  sendJson('POST', '/drafts/bulk-cancel', { ids })
