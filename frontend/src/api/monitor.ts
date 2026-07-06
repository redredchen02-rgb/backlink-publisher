// Typed wrapper for the /api/v1/monitor aggregate (Plan 2026-06-18-002 U6).
// The severity + equity-gap are computed server-side (single source); the SPA
// only displays the cards in the order the server already ranked them.

import { getJson } from './client'

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
}

export interface MonitorSummary {
  cards: MonitorCard[]
  anomaly_count: number
  degraded: boolean
}

export const monitorSummary = (): Promise<MonitorSummary> => getJson('/monitor/summary')
