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
})
