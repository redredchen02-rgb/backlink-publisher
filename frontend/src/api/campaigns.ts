// Typed wrappers for the /api/v1/campaigns* endpoints (Plan 2026-06-18-002 U7).
// Batch-campaign creation form. Validation failures arrive as an ApiError whose
// payload carries problem+json `errors[]` (field-level). On success the page
// navigates to the (separately-migrated) /campaign/<id> progress view.

import { getJson, sendJson } from './client'

// publish_partition.main rows are [name, status, needs_reconnect] tuples.
export type PartitionMainRow = [string, Record<string, unknown>, boolean]

export interface PublishPartition {
  main: PartitionMainRow[]
  extension_count?: number
  main_count?: number
}

export interface CampaignForm {
  platforms: string[]
  publish_partition: PublishPartition | null
}

export interface CampaignCreateRequest {
  seeds: string
  platforms: string[]
  mode: string
  cap?: string
  seed_delay?: string
}

export interface CampaignCreateResult {
  campaign_id: string
}

export const getCampaignForm = (): Promise<CampaignForm> => getJson('/campaigns/form')

export const createCampaign = (body: CampaignCreateRequest): Promise<CampaignCreateResult> =>
  sendJson('POST', '/campaigns', body)
