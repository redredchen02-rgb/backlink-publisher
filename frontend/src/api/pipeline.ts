// Typed wrappers for the /api/v1/pipeline/* publish-workbench endpoints
// (Plan 2026-06-18-002 U5). Thin over sendJson/getJson; the CSRF + retry +
// problem+json error handling lives in api/client.ts.
//
// Plan rows are open-ended engine output, so they are typed as Record<string,
// unknown> here — the workbench renders known fields defensively and never
// splices raw values into innerHTML (Vue escaping + classifyError taxonomy).

import { getJson, sendJson } from './client'

export type PlanRow = Record<string, unknown>

export interface Platform {
  slug: string
  display_name: string
}

export interface PlanPayload {
  urls: string[]
  platform?: string
  url_mode?: string
  publish_mode?: string
  target_language?: string
  custom_title?: string
  custom_tags?: string
  fetch_tdk?: string
}

export interface PlanResponse {
  plans: PlanRow[]
}

export interface PreviewResponse {
  plan: PlanRow | null
}

export interface ValidateResponse {
  validated: PlanRow[]
}

export interface PublishPayload {
  plans: PlanRow[] | string
  platform: string
  publish_mode?: string
  tier_1?: boolean
  target_language?: string
  target_url?: string
}

export interface PublishResult {
  state: 'all_success' | 'partial_success'
  n_ok: number
  n_total: number
  failure_detail?: string
  results: PlanRow[]
}

export interface RegenBodyPayload {
  main_domain: string
  anchors: string[]
  language?: string
  topic?: string | null
}

export interface RegenBodyResponse {
  content_markdown: string
  content_html: string
  content_source: string
}

export const planBacklinks = (p: PlanPayload): Promise<PlanResponse> =>
  sendJson('POST', '/pipeline/plan', p)

export const previewBacklink = (p: PlanPayload): Promise<PreviewResponse> =>
  sendJson('POST', '/pipeline/preview', p)

export const validateBacklinks = (plans: PlanRow[] | string): Promise<ValidateResponse> =>
  sendJson('POST', '/pipeline/validate', { plans })

// Backend publish is synchronous with a documented 300s timeout (see
// webui_app/api/v1/pipeline.py's module docstring). The client timeout here
// is set safely above that so a slow-but-still-running publish isn't
// mistaken for a hang, and noRetry is set because a client-side abort/
// network error doesn't prove the server didn't already publish — retrying
// could duplicate a live post to an external platform (code-review finding,
// 2026-07-02).
const PUBLISH_TIMEOUT_MS = 310_000

export const publishBacklinks = (p: PublishPayload): Promise<PublishResult> =>
  sendJson('POST', '/pipeline/publish', p, {
    timeoutMs: PUBLISH_TIMEOUT_MS,
    noRetry: true,
  })

export const regenArticleBody = (p: RegenBodyPayload): Promise<RegenBodyResponse> =>
  sendJson('POST', '/pipeline/regen-body', p)

/** Bound + manifest-visible platforms — the publish-form picker source (U2). */
export const boundPlatforms = (): Promise<{ platforms: Platform[] }> =>
  getJson('/bound-platforms')
