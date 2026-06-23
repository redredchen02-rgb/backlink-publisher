// Typed wrapper for the /api/v1/monitor aggregate (Plan 2026-06-18-002 U6).
// The severity + equity-gap are computed server-side (single source); the SPA
// only displays the cards in the order the server already ranked them.

import { getJson } from './client'

export type Severity = 'danger' | 'warning' | 'ok' | 'info'

export interface MonitorAction {
  label: string
  href: string
}

export interface MonitorCard {
  key: string
  title: string
  severity: Severity
  headline: string
  detail: string
  deep_link: string
  action: MonitorAction | null
}

export interface MonitorSummary {
  cards: MonitorCard[]
  anomaly_count: number
  degraded: boolean
}

export const monitorSummary = (): Promise<MonitorSummary> => getJson('/monitor/summary')
