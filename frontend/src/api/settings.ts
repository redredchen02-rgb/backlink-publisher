// Typed wrappers for the /api/v1/settings/* global (non-channel) settings —
// Plan 2026-06-18-002 U7. Single source over GlobalSettingsAPI: the keyword-pool
// editor (target domains + per-domain pools) and the publish-cadence form. The
// channel / LLM / OAuth / diagnostics sections of the settings page have their own
// already-migrated endpoints; this module is the global-config slice.

import { ApiError, getJson, sendJson } from './client'

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

// ── channel overview (read-only binding-status list) ─────────────────────────

export interface ChannelOverviewItem {
  slug: string
  display_name: string
  auth_type: string | null
  bound: boolean
  identity: string | null
  /** true | false | "uncertain" | null */
  dofollow: boolean | string | null
  last_verify_result: string | null
  blockers: string[]
}

export const getChannels = (): Promise<{ channels: ChannelOverviewItem[] }> =>
  getJson('/settings/channels')

// ── channel binding forms (credential write) ─────────────────────────────────

/** One input in a binding form — presentation only, never a value. ``secret``
 *  marks a password input: never pre-filled, a blank submit preserves the stored
 *  secret. ``type`` ∈ text | password | url | textarea. */
export interface BindingField {
  name: string
  label: string
  type: string
  placeholder: string
  help: string
  secret: boolean
}

/** A fixed-credential channel's form schema. Bind-state (bound/identity) is NOT
 *  here — join it from getChannels() by slug. ``save_via`` selects the write
 *  endpoint: 'credential' = the generic dispatch; 'token' = the dedicated
 *  token-paste route (devto / ghpages). */
export interface ChannelBindingForm {
  slug: string
  display_name: string
  auth_type: string
  supports_clear: boolean
  save_via: string
  fields: BindingField[]
}

export const getChannelForms = (): Promise<{ forms: ChannelBindingForm[] }> =>
  getJson('/settings/channels/forms')

export interface CredentialSaveResult {
  ok: boolean
  message: string
  cleared?: boolean
}

/** Save (or clear) a channel credential → 0600 file. ``body`` mirrors the form
 *  fields: auth_type (cross-checked vs registry), the auth-type's inputs, and
 *  ``clear: 1`` to remove. 422 = rejected credential, 502 = persistence failure. */
export const saveChannelCredential = (
  channel: string,
  body: Record<string, string | number>,
): Promise<CredentialSaveResult> =>
  sendJson('POST', `/settings/channels/${channel}/credential`, body)

/** Save (or clear) a single-token paste channel (devto / ghpages) via its dedicated
 *  route. ``body`` is the same shape the credential form builds ({token} / {clear:1});
 *  the endpoint reads ``token``/``clear`` and ignores the extra ``auth_type`` key. */
export const saveChannelToken = (
  channel: string,
  body: Record<string, string | number>,
): Promise<CredentialSaveResult> =>
  sendJson('POST', `/settings/channels/${channel}/token`, body)

// ── Medium channel card (browser-login + oauth-token) ────────────────────────

/** Browser-fallback readiness. ``state`` ∈ not_installed | no_profile |
 *  profile_exists_unverified | logged_in. No secrets. */
export interface MediumBrowserStatus {
  state: string
  playwright_installed: boolean
  profile_has_cookies: boolean
  cookies_age_days: number | null
  singleton_lock_present: boolean
  logged_in: boolean
}

export interface MediumStatus {
  browser: MediumBrowserStatus
  oauth_token_exists: boolean
}

/** A browser-login action outcome — ``level`` (success|info|warning|danger) is the
 *  toast class; the call always succeeds (a failed launch/probe is a result, not an
 *  error). ``logged_in`` = resulting publish-gating state, null when unchanged. */
export interface MediumActionResult {
  level: string
  message: string
  logged_in: boolean | null
}

export const getMediumStatus = (): Promise<MediumStatus> =>
  getJson('/settings/medium/status')

export const launchMediumLogin = (): Promise<MediumActionResult> =>
  sendJson('POST', '/settings/medium/launch-browser-login')

export const probeMediumLogin = (): Promise<MediumActionResult> =>
  sendJson('POST', '/settings/medium/probe-browser-login')

export const clearMediumLogin = (): Promise<MediumActionResult> =>
  sendJson('POST', '/settings/medium/clear-browser-login')

export const clearMediumOauth = (): Promise<SettingsSaveResult> =>
  sendJson('POST', '/settings/medium-oauth/clear')

// ── Velog channel card (status + browser-login spawn) ────────────────────────

/** Velog card status. ``state`` ∈ err | warn | ok | fresh | cap_reached |
 *  permission_denied. ``cookies_path`` is a local path (not a secret). */
export interface VelogStatus {
  state: string
  label: string
  guide?: string
  cookies_path?: string
  count?: number
  cap?: number
}

/** velog-login spawn outcome — always succeeds (an early-died subprocess is a
 *  result, not a transport error). ``error_code`` null on success. */
export interface VelogLoginResult {
  ok: boolean
  message: string
  error_code: string | null
  log_path?: string
}

export const getVelogStatus = (): Promise<VelogStatus> =>
  getJson('/settings/velog/status')

export const velogLogin = (): Promise<VelogLoginResult> =>
  sendJson('POST', '/settings/velog/login')

// ── Blogger channel card (OAuth credential) ──────────────────────────────────

/** Blogger card state. ``client_id`` is the public OAuth app id (not a secret);
 *  the secret is exposed only as ``client_secret_set``. ``callback_uri`` is what to
 *  register in Google Cloud Console for the Web-application client type. */
export interface BloggerStatus {
  authorized: boolean
  client_id: string
  client_secret_set: boolean
  callback_uri: string
}

export const getBloggerStatus = (): Promise<BloggerStatus> =>
  getJson('/settings/blogger/status')

/** Save Client ID / Secret (blank secret preserves the stored one). 422 = missing
 *  creds, 502 = config write failed. The OAuth login redirect to Google is a
 *  separate full-page navigation to the legacy oauth-start route. */
export const saveBloggerOauth = (
  client_id: string,
  client_secret: string,
): Promise<SettingsSaveResult> =>
  sendJson('POST', '/settings/blogger-oauth', { client_id, client_secret })

export const revokeBlogger = (): Promise<SettingsSaveResult> =>
  sendJson('POST', '/settings/blogger/revoke')

/** The domain → Blogger Blog ID routing map (consulted at publish time). */
export const getBlogIds = (): Promise<{ blog_ids: Record<string, string> }> =>
  getJson('/settings/blogger/blog-ids')

/** Save the mapping. The server strips entries, drops blank pairs and dedups by
 *  domain (later wins), so the client need not pre-clean. */
export const saveBlogIds = (
  blog_ids: Record<string, string>,
): Promise<SettingsSaveResult> =>
  sendJson('POST', '/settings/blogger/blog-ids', { blog_ids })

// ── Notion channel card (token-paste: integration_token + database_id) ───────

/** Notion card state. ``configured`` = a credential file with an integration_token
 *  exists; ``database_id`` is the non-secret target database, echoed for display.
 *  The integration_token itself is never returned. */
export interface NotionStatus {
  configured: boolean
  database_id: string
}

export const getNotionStatus = (): Promise<NotionStatus> =>
  getJson('/settings/notion/status')

/** Save the two-field Notion credential → 0600 file. A blank integration_token or
 *  database_id is rejected (422); 502 = persistence failure. */
export const saveNotionToken = (
  integration_token: string,
  database_id: string,
): Promise<CredentialSaveResult> =>
  sendJson('POST', '/settings/notion-token', { integration_token, database_id })

export const clearNotionToken = (): Promise<CredentialSaveResult> =>
  sendJson('POST', '/settings/notion-token', { clear: true })

// ── LLM / image-gen integration ──────────────────────────────────────────────

/** Redaction-safe hydration view. The two secrets are exposed ONLY as has_*
 *  booleans (the form shows a "已设置" placeholder; a blank submit preserves them). */
export interface LlmConfigView {
  endpoint: string
  model: string
  temperature: number
  system_prompt: string
  article_system_prompt: string
  use_article_gen: boolean
  use_image_gen: boolean
  image_gen_endpoint: string
  image_gen_model: string
  image_gen_banner_size: string
  has_api_key: boolean
  has_image_gen_api_key: boolean
}

export interface LlmConfigSave {
  endpoint: string
  api_key: string // blank preserves the stored secret
  model: string
  temperature: number
  system_prompt: string
  use_article_gen: boolean
  article_system_prompt: string
  use_image_gen: boolean
  image_gen_api_key: string // blank preserves
  image_gen_endpoint: string
  image_gen_model: string
  image_gen_banner_size: string
}

export const getLlmConfig = (): Promise<LlmConfigView> => getJson('/settings/llm-config')

export const saveLlmConfig = (body: Partial<LlmConfigSave>): Promise<SettingsSaveResult> =>
  sendJson('POST', '/settings/llm-config', body)

export const clearLlmConfig = (): Promise<SettingsSaveResult> =>
  sendJson('POST', '/settings/llm-config', { action: 'clear' })

// Diagnostic envelopes (status ∈ ok|failed|error; NOT problem+json — a failed
// probe is a successful call). The LLM connection probe answers 400 for an
// SSRF-rejected endpoint, which sendJson would throw; `diagnostic()` unwraps that
// envelope so the card renders the failure instead of toasting a transport error.
export interface LlmDiagnostic {
  status: 'ok' | 'failed' | 'error'
  message?: string
  models?: string[]
  result?: string
  reason?: string
}

export interface ImageGenDiagnostic {
  ok: boolean
  error?: string
  model_count?: number
  configured_model?: string
  note?: string
  frw_credits_remaining?: number
  data_url?: string
  mime?: string
  size_kb?: number
  prompt?: string
  source_url?: string
}

async function diagnostic<T>(call: Promise<T>): Promise<T> {
  try {
    return await call
  } catch (e) {
    if (
      e instanceof ApiError &&
      e.payload &&
      typeof e.payload === 'object' &&
      ('status' in e.payload || 'ok' in e.payload)
    ) {
      return e.payload as T
    }
    throw e
  }
}

export const testLlmConnection = (
  body: { endpoint?: string; api_key?: string; model?: string },
): Promise<LlmDiagnostic> => diagnostic(sendJson('POST', '/settings/llm/test-connection', body))

export const testLlmGeneration = (
  body: { test_title?: string },
): Promise<LlmDiagnostic> => diagnostic(sendJson('POST', '/settings/llm/test-generation', body))

export const testImageGen = (): Promise<ImageGenDiagnostic> =>
  diagnostic(sendJson('POST', '/settings/image-gen/test-connection'))

export const generateImageSample = (
  body: { prompt?: string },
): Promise<ImageGenDiagnostic> =>
  diagnostic(sendJson('POST', '/settings/image-gen/generate-sample', body))
