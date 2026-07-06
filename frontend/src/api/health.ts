// Typed wrapper for the /api/v1/health/* dashboard API (Plan 2026-07-02-001 U6).
// Versioned binding of the legacy /ce:health Jinja page + its pause/reverify/
// circuit-reset actions. Every panel is fail-open: GET /health/summary is
// always 200, with each panel carrying its own `degraded` flag.

import { getJson, sendJson } from './client'

export interface HealthPanel<T> {
  data: T
  degraded: boolean
}

export interface HealthProjection {
  events_inserted: number
  sources_projected: number
  latest_event_utc: string | null
  gap: boolean
  gap_reason: string | null
  degraded: boolean
  degraded_reason: string | null
}

export interface SuccessRate {
  targets: number
  confirmed: number
  pct: number | null
}

export interface AdapterHealth {
  platform: string
  confirmed: number
  unverified: number
  failed: number
  total: number
  pct: number | null
  small_sample: boolean
}

export interface ErrorBucket {
  error_class: string
  count: number
}

export interface BrokenChannel {
  channel: string
  status: string
  last_verified_at: string | null
}

export interface Health {
  window_days: number
  since_utc: string
  success: SuccessRate
  per_adapter: AdapterHealth[]
  errors: ErrorBucket[]
  broken: BrokenChannel[]
}

export interface CanaryRow {
  platform: string
  status: string | null
  consecutive_failures: number
  consecutive_oks: number
  quarantined: boolean
  last_ok_at: string | null
  last_drift_at: string | null
}

export interface ForwardPathRow extends Omit<CanaryRow, 'quarantined'> {
  degraded: boolean
}

export interface PlatformHealthRecord {
  platform: string
  last_success_at: string | null
  last_failure_at: string | null
  last_error_msg: string | null
  consecutive_failures: number
  circuit_tripped: boolean
  circuit_tripped_at: string | null
  paused: boolean
}

export interface PublishMetrics {
  success_rate: SuccessRate | null
  coverage: Record<string, unknown> | null
  readiness: Record<string, unknown> | null
  policy_mode: string | null
  enforce_channels: string[]
}

export interface HealthSummary {
  projection: HealthProjection
  health: Health
  agg_degraded: boolean
  panels: {
    canary: HealthPanel<CanaryRow[]>
    forward_path: HealthPanel<ForwardPathRow[]>
    reconciliation_gaps: HealthPanel<{ pending_checkpoints?: number; quarantine_gaps?: number }>
    recheck_decay: HealthPanel<Record<string, number>>
    channel_scorecard: HealthPanel<Record<string, unknown>[]>
    geo_panel: HealthPanel<{ targets?: unknown[] }>
    pipeline_summary: HealthPanel<Record<string, unknown>>
    storage_health: HealthPanel<{
      events_db_mb?: number; dedup_db_mb?: number; config_dir_mb?: number
      events_rows?: number; articles_rows?: number; events_db_warn?: boolean
    }>
    platform_health: HealthPanel<Record<string, PlatformHealthRecord>>
    autopilot_alerts: HealthPanel<Record<string, unknown>[]>
    weights_snapshot: HealthPanel<Record<string, unknown> | null>
    decay_alerts: HealthPanel<{ target_url: string; lost_count: number; ts: string }[]>
    gsc_indexation: HealthPanel<Record<string, unknown>[]>
    gsc_ranking: HealthPanel<Record<string, unknown>[]>
    publish_index_latency: HealthPanel<Record<string, unknown>[]>
    index_rate_by_channel: HealthPanel<Record<string, unknown>[]>
    impression_analysis: HealthPanel<Record<string, unknown>[]>
    ranking_lift_analysis: HealthPanel<Record<string, unknown>[]>
    referral_conversion: HealthPanel<Record<string, unknown>[]>
    cost_metrics: HealthPanel<Record<string, unknown>>
    decisions_by_platform: HealthPanel<Record<string, unknown>[]>
    publish_metrics: HealthPanel<PublishMetrics>
  }
}

export interface HealthScorecardLinks {
  ok: boolean
  links: Record<string, unknown>[]
}

export interface HealthRecheckLinkResult {
  ok: boolean
  verdict?: unknown
  live_url?: string
  last_recheck_ts?: string
  error_code?: string
}

export interface HealthActionResult {
  ok: boolean
  platform: string
  paused?: boolean
  ready?: boolean
  reason?: string
}

export const fetchHealthSummary = (): Promise<HealthSummary> => getJson('/health/summary')

export const fetchScorecardLinks = (channel: string): Promise<HealthScorecardLinks> =>
  getJson(`/health/scorecard/${encodeURIComponent(channel)}/links`)

export const recheckLink = (liveUrl: string): Promise<HealthRecheckLinkResult> =>
  sendJson('POST', '/health/scorecard/recheck-link', { live_url: liveUrl })

export const pausePlatform = (platform: string, paused: boolean): Promise<HealthActionResult> =>
  sendJson('POST', '/health/actions/pause', { platform, paused })

export const reverifyPlatform = (platform: string): Promise<HealthActionResult> =>
  sendJson('POST', '/health/actions/reverify', { platform })

export const circuitResetPlatform = (platform: string): Promise<HealthActionResult> =>
  sendJson('POST', '/health/actions/circuit-reset', { platform })
