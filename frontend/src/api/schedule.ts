// Typed wrapper for the /api/v1/schedule endpoint (Plan 2026-06-18-002 U7).
// Read-only view of drafts scheduled for future publish — single source over
// drafts_store, shared with the drafts queue (mutations live on the Drafts page).

import { getJson } from './client'

export interface ScheduledItem {
  id?: string
  title?: string
  target_url?: string
  platform?: string
  scheduled_at?: string | null
  created_at?: string
  status?: string
}

export interface ScheduledList {
  items: ScheduledItem[]
}

export const listScheduled = (): Promise<ScheduledList> => getJson('/schedule')
