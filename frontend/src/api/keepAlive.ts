// Keep-alive API — Plan P15 A1 (SPA migration).

export interface KeepAliveTarget {
  target_url: string
  live_dofollow: number
  stripped: number
  decayed: number
  check_failed: number
  strip_rate: number
  trend: string
  platforms: string
  last_verified: string | null
  needs_attention: boolean
}

export interface KeepAliveGap {
  target_url: string
  platform: string
  publish_ts: string
  stripped_ts: string
}

export interface KeepAliveSummary {
  targets: KeepAliveTarget[]
  gaps: KeepAliveGap[]
  stale: boolean
  stale_days: number
  last_recheck: string | null
  is_empty: boolean
  alive_count: number
  stripped_count: number
  unknown_count: number
  live_excluded: number
  gap_channel_exhausted: number
}

export interface JobStatus {
  job_id?: string
  status: string
  kind?: string
  progress?: number
  total?: number
  message?: string
}

export interface RecheckResult {
  status: 'started' | 'running'
  job_id?: string
  message?: string
}

// GET /ce:keep-alive/republish-token payload (issue_confirm_token). Audit [01]:
// the backend returns a confirm nonce + the server-derived sticky target set and
// per-seed destinations — NOT an {ok, token} envelope.
export interface RepublishTokenResponse {
  confirm_token: string
  gap_fingerprint?: string
  targets: string[]
  seed_count?: number
  seeds: { target_url: string; platform: string }[]
}

// POST /ce:keep-alive/republish response: {status:'started', job_id} (202) on
// success, {status:'error', error} otherwise. No `ok` field.
export interface RepublishResult {
  status?: string
  job_id?: string
  error?: string
  message?: string
}

export interface CycleStatus {
  running: boolean
  last_cycle_at?: string
  next_cycle_at?: string
  stage?: string
  status?: string
}

const _csrf = async (): Promise<string> => {
  const meta = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
  if (meta) return meta
  const resp = await fetch('/api/v1/csrf-token', {
    headers: { Accept: 'application/json' }, credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error('Failed to get CSRF token')
  return ((await resp.json()) as { csrf_token: string }).csrf_token
}

export const fetchSummary = async (): Promise<KeepAliveSummary> => {
  const resp = await fetch('/api/keep-alive/summary', {
    headers: { Accept: 'application/json' }, credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as KeepAliveSummary
}

export const startRecheck = async (): Promise<RecheckResult> => {
  const resp = await fetch('/ce:keep-alive/recheck', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'X-CSRFToken': await _csrf() },
  })
  return (await resp.json()) as RecheckResult
}

export const pollRecheck = async (jobId: string): Promise<JobStatus> => {
  const resp = await fetch(`/ce:keep-alive/recheck-status/${jobId}`, {
    headers: { Accept: 'application/json' }, credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as JobStatus
}

export const cancelRecheck = async (jobId: string): Promise<JobStatus> => {
  const resp = await fetch(`/ce:keep-alive/recheck-cancel/${jobId}`, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'X-CSRFToken': await _csrf() },
  })
  return (await resp.json()) as JobStatus
}

export const getRepublishToken = async (): Promise<RepublishTokenResponse> => {
  const resp = await fetch('/ce:keep-alive/republish-token', {
    headers: { Accept: 'application/json' }, credentials: 'same-origin',
  })
  return (await resp.json()) as RepublishTokenResponse
}

export const executeRepublish = async (
  targets: string[], confirmToken: string,
): Promise<RepublishResult> => {
  const resp = await fetch('/ce:keep-alive/republish', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': await _csrf() },
    body: JSON.stringify({ targets, confirm_token: confirmToken }),
  })
  return (await resp.json()) as RepublishResult
}

export const pollRepublish = async (jobId: string): Promise<JobStatus> => {
  const resp = await fetch(`/ce:keep-alive/republish-status/${jobId}`, {
    headers: { Accept: 'application/json' }, credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as JobStatus
}

export const fetchCycleStatus = async (): Promise<CycleStatus> => {
  const resp = await fetch('/ce:keep-alive/cycle-status', {
    headers: { Accept: 'application/json' }, credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as CycleStatus
}

export const resetExhausted = async (): Promise<{ ok: boolean; message?: string }> => {
  const resp = await fetch('/ce:keep-alive/reset-exhausted', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'X-CSRFToken': await _csrf() },
  })
  return (await resp.json()) as { ok: boolean; message?: string }
}
