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

export const fetchPrQueue = async (): Promise<PrItem[]> => {
  const resp = await fetch('/api/pr-queue', {
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
  const resp = await fetch('/api/pr-queue/status', {
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
