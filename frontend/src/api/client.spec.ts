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

describe('sendJson keepalive option', () => {
  it('passes keepalive:true through to fetch when requested (Plan 2026-07-01-002 U6)', async () => {
    document.head.innerHTML = '<meta name="csrf-token" content="tok">'
    let seenKeepalive: boolean | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        seenKeepalive = init?.keepalive
        return jsonResponse({ ok: true })
      }),
    )
    await sendJson('POST', '/error-reports', { message: 'x' }, { keepalive: true })
    expect(seenKeepalive).toBe(true)
  })

  it('paired: an ordinary sendJson call with no options passes keepalive:false, unchanged from before this option existed', async () => {
    document.head.innerHTML = '<meta name="csrf-token" content="tok">'
    let seenKeepalive: boolean | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        seenKeepalive = init?.keepalive
        return jsonResponse({ ok: true })
      }),
    )
    await sendJson('POST', '/pipeline/plan', { url: 'x' })
    expect(seenKeepalive).toBe(false)
  })
})
