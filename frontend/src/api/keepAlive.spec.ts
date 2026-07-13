// keepAlive API client — republish request/response contract (audit finding [01]).
//
// The SPA keep-alive republish flow was dead end-to-end because keepAlive.ts was
// written against a contract the backend does not implement:
//   GET  /ce:keep-alive/republish-token -> {confirm_token, targets, seeds, ...}
//        (NOT {ok, token})
//   POST /ce:keep-alive/republish       <- {targets: string[], confirm_token}
//        (NOT {token, gap_keys}); success -> {status:'started', job_id} (202)
// These tests lock the API client to the real backend shapes.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { executeRepublish, getRepublishToken } from './keepAlive'

beforeEach(() => {
  // Present a CSRF meta so _csrf() resolves without a second fetch.
  document.head.innerHTML = '<meta name="csrf-token" content="csrf-x">'
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.head.innerHTML = ''
})

describe('keepAlive API — republish contract', () => {
  it('getRepublishToken returns the confirm_token / targets / seeds payload', async () => {
    const payload = {
      confirm_token: 'nonce-1',
      gap_fingerprint: 'fp',
      targets: ['https://example.com/a'],
      seed_count: 1,
      seeds: [{ target_url: 'https://example.com/a', platform: 'blogger' }],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload }))

    const tok = await getRepublishToken()

    expect(tok.confirm_token).toBe('nonce-1')
    expect(tok.targets).toEqual(['https://example.com/a'])
    expect(tok.seeds).toEqual([{ target_url: 'https://example.com/a', platform: 'blogger' }])
  })

  it('executeRepublish POSTs {targets, confirm_token} — not {token, gap_keys}', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 202, json: async () => ({ status: 'started', job_id: 'job-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    const result = await executeRepublish(['https://example.com/a', 'https://example.com/b'], 'nonce-1')

    const call = fetchMock.mock.calls.find(
      (c) => String(c[0]) === '/ce:keep-alive/republish',
    )
    expect(call, 'must POST to /ce:keep-alive/republish').toBeTruthy()
    expect(String(call![1].method).toUpperCase()).toBe('POST')
    const body = JSON.parse(call![1].body as string)
    expect(body).toEqual({
      targets: ['https://example.com/a', 'https://example.com/b'],
      confirm_token: 'nonce-1',
    })
    expect(body.token).toBeUndefined()
    expect(body.gap_keys).toBeUndefined()
    expect(result.job_id).toBe('job-1')
  })
})
