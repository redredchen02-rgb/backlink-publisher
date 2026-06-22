// Typed wrappers for the /api/v1/settings/* global (non-channel) settings —
// Plan 2026-06-18-002 U7. Single source over GlobalSettingsAPI: the keyword-pool
// editor (target domains + per-domain pools) and the publish-cadence form. The
// channel / LLM / OAuth / diagnostics sections of the settings page have their own
// already-migrated endpoints; this module is the global-config slice.

import { getJson, sendJson } from './client'

// ── keyword pools ────────────────────────────────────────────────────────────

export interface KeywordPoolsView {
  /** Known target domains to render an editor for (blog-id-mapped ∪ already-pooled). */
  targets: string[]
  /** Each domain's current keyword pool. */
  pools: Record<string, string[]>
}

export interface SettingsSaveResult {
  ok: boolean
  message: string
}

export const getKeywordPools = (): Promise<KeywordPoolsView> =>
  getJson('/settings/keywords')

export const saveKeywordPools = (
  pools: Record<string, string[]>,
): Promise<SettingsSaveResult> => sendJson('POST', '/settings/keywords', { pools })

// ── publish cadence ──────────────────────────────────────────────────────────

export interface ScheduleSettings {
  min_interval_hours: number
  jitter_minutes: number
}

export const getScheduleSettings = (): Promise<ScheduleSettings> =>
  getJson('/settings/schedule')

export const saveScheduleSettings = (
  settings: ScheduleSettings,
): Promise<SettingsSaveResult> => sendJson('POST', '/settings/schedule', settings)
