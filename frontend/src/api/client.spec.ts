import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, _resetCsrfForTest, csrfToken, getJson, sendJson } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  _resetCsrfForTest()
  document.head.innerHTML = ''
})

describe('csrfToken', () => {
  it('prefers a server-rendered <meta> token without a network call', async () => {
    document.head.innerHTML = '<meta name="csrf-token" content="from-meta">'
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect(await csrfToken()).toBe('from-meta')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('falls back to the /api/v1/csrf-token endpoint when no meta', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ csrf_token: 'from-endpoint' })))
    expect(await csrfToken()).toBe('from-endpoint')
  })
})

describe('getJson', () => {
  it('returns parsed JSON on 200', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'ok' })))
    expect(await getJson('/health')).toEqual({ status: 'ok' })
  })

  it('throws ApiError carrying status + problem detail on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ title: 'Not Found', status: 404, detail: 'nope' }, 404)),
    )
    await expect(getJson('/missing')).rejects.toMatchObject({ status: 404 })
    await expect(getJson('/missing')).rejects.toBeInstanceOf(ApiError)
  })
})

describe('withRetry pinning (network errors only — R3 action 9)', () => {
  // client.ts's withRetry only retries TypeError/AbortError (real network/
  // infra failures); ApiError (a real 4xx/5xx server response) must NOT be
  // retried, or a genuine failure could be masked as "still loading" for an
  // extra round-trip. These pin the existing isNetworkErr behavior.

  it('retries once on a TypeError (network failure) and succeeds on the second attempt', async () => {
    let calls = 0
    const fetchMock = vi.fn(async () => {
      calls += 1
      if (calls === 1) throw new TypeError('Failed to fetch')
      return jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await getJson('/health', { noDedup: true })

    expect(result).toEqual({ ok: true })
    expect(calls).toBe(2)
  })

  it('retries once on an AbortError (timeout) and succeeds on the second attempt', async () => {
    let calls = 0
    const fetchMock = vi.fn(async () => {
      calls += 1
      if (calls === 1) throw new DOMException('The operation was aborted', 'AbortError')
      return jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await getJson('/health', { noDedup: true })

    expect(result).toEqual({ ok: true })
    expect(calls).toBe(2)
  })

  it('does NOT retry a 4xx/5xx ApiError — a real server response fails immediately', async () => {
    let calls = 0
    const fetchMock = vi.fn(async () => {
      calls += 1
      return jsonResponse({ detail: 'server exploded' }, 500)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getJson('/health', { noDedup: true })).rejects.toBeInstanceOf(ApiError)
    expect(calls).toBe(1) // no retry attempted
  })

  it('does NOT retry a 4xx client error either', async () => {
    let calls = 0
    const fetchMock = vi.fn(async () => {
      calls += 1
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getJson('/missing', { noDedup: true })).rejects.toBeInstanceOf(ApiError)
    expect(calls).toBe(1)
  })
})

describe('sendJson CSRF retry', () => {
  it('attaches X-CSRFToken and retries once with a fresh token on 403', async () => {
    const seen: string[] = []
    let tokenSeq = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/csrf-token')) {
        tokenSeq += 1
        return jsonResponse({ csrf_token: `t${tokenSeq}` })
      }
      seen.push(String((init?.headers as Record<string, string>)['X-CSRFToken']))
      // first POST 403s (rotated token), second succeeds
      return seen.length === 1 ? jsonResponse({ ok: false }, 403) : jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await sendJson('POST', '/pipeline/plan', { url: 'x' })
    expect(result).toEqual({ ok: true })
    expect(seen).toEqual(['t1', 't2']) // refreshed token on retry
  })
})

describe('sendJson noRetry (code-review finding, 2026-07-02)', () => {
  // A client-side network error/timeout doesn't prove the server never
  // processed a non-idempotent mutation (e.g. /pipeline/publish). noRetry
  // must skip the network-error auto-retry entirely, while still allowing
  // the (unrelated) CSRF-403 retry to fire when the server actually responds.

  it('does NOT retry on a network-level TypeError when noRetry is set', async () => {
    let calls = 0
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith('/csrf-token')) return jsonResponse({ csrf_token: 't1' })
      calls += 1
      throw new TypeError('Failed to fetch')
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      sendJson('POST', '/pipeline/publish', { plans: [], platform: 'x' }, { noRetry: true }),
    ).rejects.toBeInstanceOf(TypeError)
    expect(calls).toBe(1) // no retry attempted
  })

  it('still retries once on a 403 (CSRF rotation) even with noRetry set', async () => {
    const seen: string[] = []
    let tokenSeq = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/csrf-token')) {
        tokenSeq += 1
        return jsonResponse({ csrf_token: `t${tokenSeq}` })
      }
      seen.push(String((init?.headers as Record<string, string>)['X-CSRFToken']))
      return seen.length === 1 ? jsonResponse({ ok: false }, 403) : jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await sendJson(
      'POST',
      '/pipeline/publish',
      { plans: [], platform: 'x' },
      { noRetry: true },
    )
    expect(result).toEqual({ ok: true })
    expect(seen).toEqual(['t1', 't2'])
  })
})
