// Typed wrappers for the /api/v1/sites* endpoints (Plan 2026-06-18-002 U7).
// The save/autopilot mutations return the refreshed site list (written straight
// into the query cache). Save validation failures arrive as an ApiError whose
// payload carries problem+json `errors[]` (field-level), surfaced inline by the
// page. Scope: config form + autopilot + read-only widgets — NOT the batch table.

import { getJson, sendJson } from './client'

export interface SiteItem {
  label: string
  main_url: string
  autopilot_enabled: boolean
  autopilot_interval: number
  alert_pending: boolean
  next_run_time_iso: string | null
}

export interface SiteList {
  items: SiteItem[]
}

export interface SiteForm {
  main_url: string
  list_url: string
  work_urls: string
  branded_pool: string
  partial_pool: string
  exact_pool: string
  work_anchor_templates: string
  count: string
  insecure_tls: boolean
}

export interface PlanGap {
  status: 'ok' | 'missing' | 'invalid'
  candidate_count?: number
  target_count?: number
  triggered_at?: string
  error?: string
}

export interface CitationAlert {
  ts: string
}

export interface SiteWidgets {
  plan_gap: PlanGap
  citation_alert: CitationAlert | null
}

export interface SiteSaveResult {
  ok: boolean
  saved_domain: string
  autofilled: string[]
  items: SiteItem[]
}

export interface SiteAutopilotResult {
  ok: boolean
  site_url: string
  enabled: boolean
  next_run_time: string | null
  last_run: unknown
  items: SiteItem[]
}

export interface ScrapePreview {
  status: 'ok' | 'error'
  title?: string
  description?: string
  h1?: string
  reason?: string
}

export const listSites = (): Promise<SiteList> => getJson('/sites')

export const getSitesWidgets = (): Promise<SiteWidgets> => getJson('/sites/widgets')

export const getSiteForm = (domain: string): Promise<{ form: SiteForm | null }> =>
  getJson(`/sites/form?domain=${encodeURIComponent(domain)}`)

export const saveSite = (form: Partial<SiteForm>): Promise<SiteSaveResult> =>
  sendJson('POST', '/sites/save', form)

export const setAutopilot = (
  site_url: string,
  enabled: boolean,
  interval_seconds: number,
): Promise<SiteAutopilotResult> =>
  sendJson('POST', '/sites/autopilot', { site_url, enabled, interval_seconds })

export const scrapePreview = (url: string): Promise<ScrapePreview> =>
  getJson(`/sites/scrape-preview?url=${encodeURIComponent(url)}`)
