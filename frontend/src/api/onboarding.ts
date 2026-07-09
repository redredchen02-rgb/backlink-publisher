// Typed wrappers for the /api/v1/onboarding/* first-run guide endpoints
// (Plan 2026-07-09-001). Single source over OnboardingAPI. CSRF is handled
// automatically by sendJson (fresh token per mutating call, see client.ts).

import { getJson, sendJson } from './client'

export interface OnboardingStep {
  id: string
  title: string
  rationale: string
  optional: boolean
  cta: string
  done: boolean
}

export interface OnboardingStatus {
  dismissed: boolean
  all_done: boolean
  steps: OnboardingStep[]
}

export const getOnboardingStatus = (): Promise<OnboardingStatus> =>
  getJson('/onboarding/status')

export const dismissOnboarding = (): Promise<{ ok: boolean }> =>
  sendJson('POST', '/onboarding/dismiss', {})

export const resetOnboarding = (): Promise<{ ok: boolean }> =>
  sendJson('POST', '/onboarding/reset', {})
