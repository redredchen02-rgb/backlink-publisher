// Campaign progress API — Plan P13 B3 (SPA migration).

export interface CampaignSeed {
  idx: number
  text_preview?: string
  status: string
  draft_count?: number
  published_count?: number
  error?: string
}

export interface CampaignStatus {
  campaign_id: string
  status?: string
  progress_pct: number
  mode?: string
  running: boolean
  done: boolean
  seeds: CampaignSeed[]
  result_summary?: Record<string, unknown>
  error?: string
}

export const fetchCampaignStatus = async (
  campaignId: string,
): Promise<CampaignStatus> => {
  const resp = await fetch(`/api/campaign/${campaignId}/status`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) {
    if (resp.status === 404) throw new Error('未找到该任务')
    throw new Error(`HTTP ${resp.status}`)
  }
  return (await resp.json()) as CampaignStatus
}
