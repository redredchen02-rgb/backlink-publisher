// Equity ledger API — Plan P14 B1 (SPA migration).

export interface EquityRow {
  target_url: string
  main_domain: string
  platform: string
  status: string
  first_seen?: string
  last_checked?: string
  dofollow: boolean
  live: boolean
  relevance_score?: number
}

export interface EquityResponse {
  ok: boolean
  rows: EquityRow[]
  exact_match_threshold?: number
  stale_days?: number
  error?: string
}

export const fetchEquityLedger = async (): Promise<EquityResponse> => {
  const resp = await fetch('/api/equity-ledger', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as EquityResponse
}

export const triggerRecheck = async (): Promise<{ ok: boolean; message?: string }> => {
  const meta = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
  const token = meta || ''
  const resp = await fetch('/ce:equity-ledger/recheck', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRFToken': token },
  })
  return (await resp.json()) as { ok: boolean; message?: string }
}
