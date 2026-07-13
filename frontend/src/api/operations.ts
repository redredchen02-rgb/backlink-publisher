// Async operation API — Plan 2026-07-09 (U1).
//
// Thin wrappers over /api/v1/operations/*. The WebUI submits a pipeline
// operation (publish / publish-chain / plan / validate) and gets an op_id
// immediately; the work runs server-side in a background worker, and the SPA
// polls getOperation() for stage + progress. Mirrors the campaign polling
// surface (api/campaign.ts) but is generic across all op kinds.

import { getJson, sendJson } from './client'

export type OperationKind = 'plan' | 'validate' | 'publish' | 'publish_chain'
export type OperationStatusValue =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'canceled'

export interface OperationStatus {
  op_id: string
  kind: OperationKind
  status: OperationStatusValue
  stage: string
  stages: string[]
  progress_pct: number
  detail: string
  result: {
    state: string
    n_ok: number
    n_failed: number
    failure_detail?: string
    results: Record<string, unknown>[]
  } | null
  error: string | null
  created_at: string
  updated_at: string
  running: boolean
  done: boolean
}

export interface OperationList {
  operations: OperationStatus[]
  count: number
}

/** Enqueue an op; returns its id (HTTP 202). */
export const createOperation = (
  payload: Record<string, unknown>,
): Promise<{ op_id: string; kind: string }> =>
  sendJson('POST', '/operations', payload)

/** Poll a single op's current state. */
export const getOperation = (opId: string): Promise<OperationStatus> =>
  getJson(`/operations/${opId}`)

/** List recent operations (newest first). */
export const listOperations = (
  limit = 50,
): Promise<OperationList> => getJson(`/operations?limit=${limit}`)

/** Request cancellation of a running op. */
export const cancelOperation = (
  opId: string,
): Promise<{ op_id: string; status: string; canceled: boolean }> =>
  sendJson('POST', `/operations/${opId}/cancel`, {})
