import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchPrQueue, updatePrStatus } from './prQueue'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  document.head.innerHTML = ''
})

describe('fetchPrQueue', () => {
  it('returns items on a healthy response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: true, items: [{ id: 'a', status: 'pending' }] })),
    )
    expect(await fetchPrQueue()).toEqual([{ id: 'a', status: 'pending' }])
  })

  it('throws on a non-ok HTTP status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 500)))
    await expect(fetchPrQueue()).rejects.toThrow('HTTP 500')
  })

  it('throws when the payload reports ok: false', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ok: false, items: [] })))
    await expect(fetchPrQueue()).rejects.toThrow('API returned not ok')
  })

  // B3 (backlog, found in B2's code review): fetchPrQueue/updatePrStatus used
  // to call fetch() directly with no AbortController, so a hung backend left
  // the caller waiting forever with no escape. Pin that a timeout/abort
  // mechanism now exists, without needing to fake-timer-advance the real 15s
  // window (client.spec.ts's own tests for the equivalent client.ts behavior
  // take the same approach — they pin the reaction to an AbortError, not the
  // literal timer duration).
  it('passes an AbortSignal to fetch so a hung request can be cancelled', async () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) =>
      jsonResponse({ ok: true, items: [] }),
    )
    vi.stubGlobal('fetch', fetchMock)
    await fetchPrQueue()
    const [, init] = fetchMock.mock.calls[0]
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })

  it('propagates an AbortError instead of hanging when the request times out', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new DOMException('The operation was aborted', 'AbortError')
      }),
    )
    await expect(fetchPrQueue()).rejects.toMatchObject({ name: 'AbortError' })
  })

  // Fake-timer version of the above: the previous test pins the *reaction* to
  // an AbortError by throwing one synthetically, without ever exercising the
  // real setTimeout/ctrl.abort() wiring inside _fetchWithTimeout. This test
  // mocks fetch to hang until the AbortSignal it was given actually fires,
  // then advances the fake 15s timer and asserts the real timeout/abort path
  // is what produces the rejection.
  it('actually fires the real 15s timeout, aborting the in-flight request via the real AbortController wiring', async () => {
    vi.useFakeTimers()
    try {
      const fetchMock = vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted', 'AbortError'))
            })
          }),
      )
      vi.stubGlobal('fetch', fetchMock)

      const promise = fetchPrQueue()
      vi.advanceTimersByTime(15000)

      await expect(promise).rejects.toMatchObject({ name: 'AbortError' })
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('updatePrStatus', () => {
  it('returns the updated item on success', async () => {
    document.head.innerHTML = '<meta name="csrf-token" content="tok">'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: true, item: { id: 'a', status: 'won' } })),
    )
    expect(await updatePrStatus('a', 'won')).toEqual({ id: 'a', status: 'won' })
  })

  it('throws the server-provided error message when ok: false', async () => {
    document.head.innerHTML = '<meta name="csrf-token" content="tok">'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ok: false, error: 'invalid transition' })),
    )
    await expect(updatePrStatus('a', 'won')).rejects.toThrow('invalid transition')
  })

  it('passes an AbortSignal to the status-update fetch too', async () => {
    document.head.innerHTML = '<meta name="csrf-token" content="tok">'
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) =>
      jsonResponse({ ok: true, item: { id: 'a', status: 'won' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    await updatePrStatus('a', 'won')
    const [, init] = fetchMock.mock.calls[0]
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })

  // _csrf()'s network-fallback branch: when no <meta name="csrf-token"> is
  // present (document.head is left empty here, unlike every test above),
  // _csrf() must call _fetchWithTimeout('/api/v1/csrf-token', ...) itself.
  it('falls back to the /api/v1/csrf-token network fetch when no <meta> tag is present, and proceeds with the returned token', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/csrf-token') {
        return jsonResponse({ csrf_token: 'network-token' })
      }
      expect((init?.headers as Record<string, string>)['X-CSRFToken']).toBe('network-token')
      return jsonResponse({ ok: true, item: { id: 'a', status: 'won' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    expect(await updatePrStatus('a', 'won')).toEqual({ id: 'a', status: 'won' })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/csrf-token', expect.anything())
  })

  it('propagates a rejection from the CSRF network fallback instead of proceeding', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/v1/csrf-token') {
          throw new Error('csrf fetch failed')
        }
        return jsonResponse({ ok: true, item: { id: 'a', status: 'won' } })
      }),
    )
    await expect(updatePrStatus('a', 'won')).rejects.toThrow('csrf fetch failed')
  })
})
