// Survival dashboard API — Plan P13 B1 (SPA migration).
// Calls the JSON twin endpoint at /api/survival (P13 addition).

export interface SurvivalView {
  state: 'ok' | 'insufficient' | 'empty'
  survival_rate: number | null
  sample_size: number
  survived: number
  mature_count: number
  maturing_count: number
  stale: boolean
  stale_count: number
  partial: boolean
  stale_days: number | null
  has_rate: boolean
  display: string
  headline: string
  sub: string
  cohort_days: number
  unavailable?: boolean
}

export const fetchSurvival = async (): Promise<SurvivalView> => {
  const resp = await fetch('/api/survival', {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as SurvivalView
}
