// PR opportunity queue API — Plan P12 A1 (SPA Phase 3 migration).
// Uses legacy /api/pr-queue endpoints (no /api/v1 equivalent yet).

export interface PrItem {
  id: string
  status: string
  relevance_score?: number
  headline?: string
  summary?: string
  source?: string
  deadline?: string
}

export interface PrQueueResponse {
  ok: boolean
  items: PrItem[]
}

export interface PrStatusResponse {
  ok: boolean
  item?: PrItem
  error?: string
}

// client.ts's getJson/sendJson can't be reused here: they hardcode the
// /api/v1 base path, and these are legacy /api/pr-queue endpoints (see file
// header). Rather than pull in client.ts's full dedup/retry/CSRF-refresh
// machinery for a base path it doesn't support, this mirrors just the piece
// that was actually missing — a bounded timeout via AbortController — so a
// hung backend can't leave the caller stuck on the loading skeleton forever
// with no way out (found during B2's code review, backlog B3; 15s matches
// client.ts's DEFAULT_TIMEOUT_MS).
const _TIMEOUT_MS = 15_000

const _fetchWithTimeout = (url: string, init: RequestInit): Promise<Response> => {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), _TIMEOUT_MS)
  return fetch(url, { ...init, signal: ctrl.signal }).finally(() => clearTimeout(timer))
}

const _csrf = async (): Promise<string> => {
  const meta = document
    .querySelector('meta[name="csrf-token"]')
    ?.getAttribute('content')
  if (meta) return meta
  const resp = await _fetchWithTimeout('/api/v1/csrf-token', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error('Failed to get CSRF token')
  return ((await resp.json()) as { csrf_token: string }).csrf_token
}

export const fetchPrQueue = async (): Promise<PrItem[]> => {
  const resp = await _fetchWithTimeout('/api/pr-queue', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = (await resp.json()) as PrQueueResponse
  if (!data.ok) throw new Error('API returned not ok')
  return data.items
}

export const updatePrStatus = async (
  id: string,
  status: string,
): Promise<PrItem> => {
  const resp = await _fetchWithTimeout('/api/pr-queue/status', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': await _csrf(),
    },
    body: JSON.stringify({ id, status }),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = (await resp.json()) as PrStatusResponse
  if (!data.ok) throw new Error(data.error ?? 'Update failed')
  return data.item!
}
