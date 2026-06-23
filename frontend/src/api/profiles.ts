// Typed wrappers for the /api/v1/profiles* endpoints (Plan 2026-06-18-002 U7).
//
// A profile is a named publish preset (platform / language / url_mode /
// publish_mode). Mutations return the refreshed `{ items }`, so callers can seed
// the query cache directly. The SPA consumer is the publish workbench's config
// block (ProfileSelector) — url_mode has no workbench control, so saves omit it
// and the backend defaults it.

import { getJson, sendJson } from './client'

export interface Profile {
  name: string
  platform: string
  language: string
  url_mode: string
  publish_mode: string
}

export interface ProfileList {
  items: Profile[]
}

export interface ProfileSaveRequest {
  name: string
  platform?: string
  language?: string
  url_mode?: string
  publish_mode?: string
}

export const getProfiles = (): Promise<ProfileList> => getJson('/profiles')

export const saveProfile = (body: ProfileSaveRequest): Promise<ProfileList> =>
  sendJson('POST', '/profiles/save', body)

export const deleteProfile = (name: string): Promise<ProfileList> =>
  sendJson('POST', '/profiles/delete', { name })
