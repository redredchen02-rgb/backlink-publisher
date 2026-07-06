// Optimization status API — Plan P13 B2 (SPA migration).

export interface PlatformWeight {
  platform: string
  weight: number
  base?: number
  delta_pct?: number
  adjustments?: number
  alive?: number
  total?: number
  drift?: number
  updated?: string
  locked?: boolean
}

export interface OptimizationSummary {
  ok: boolean
  platforms: PlatformWeight[]
  all_platforms: string[]
  error?: string
}

export interface ApiResult {
  ok: boolean
  message?: string
  error?: string
}

const _csrf = async (): Promise<string> => {
  const meta = document
    .querySelector('meta[name="csrf-token"]')
    ?.getAttribute('content')
  if (meta) return meta
  const resp = await fetch('/api/v1/csrf-token', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error('Failed to get CSRF token')
  return ((await resp.json()) as { csrf_token: string }).csrf_token
}

export const fetchPlatforms = async (): Promise<OptimizationSummary> => {
  const resp = await fetch('/api/optimization-status', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json() as Promise<OptimizationSummary>
}

export const setWeight = async (
  platform: string,
  weight: number,
): Promise<ApiResult> => {
  const resp = await fetch('/api/optimization-status/set-weight', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': await _csrf(),
    },
    body: JSON.stringify({ platform, weight }),
  })
  return resp.json() as Promise<ApiResult>
}

export const unlockWeight = async (platform: string): Promise<ApiResult> => {
  const resp = await fetch('/api/optimization-status/unlock-weight', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': await _csrf(),
    },
    body: JSON.stringify({ platform }),
  })
  return resp.json() as Promise<ApiResult>
}
