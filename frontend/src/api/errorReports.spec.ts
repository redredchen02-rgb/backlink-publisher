import { afterEach, describe, expect, it, vi } from 'vitest'
import { _resetCsrfForTest } from './client'
import {
  deleteErrorReport,
  getErrorReport,
  listErrorReports,
  updateErrorReport,
} from './errorReports'

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

describe('listErrorReports', () => {
  it('calls GET /error-reports with no query string when no filters are given', async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await listErrorReports()

    expect(result).toEqual({ items: [], total: 0 })
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/error-reports')
  })

  it('serializes only the provided filters into the query string', async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listErrorReports({ status: 'open', severity: 'error', limit: 20, offset: 40 })

    const [url] = fetchMock.mock.calls[0]
    const parsed = new URL(url, 'http://localhost')
    expect(parsed.pathname).toBe('/api/v1/error-reports')
    expect(parsed.searchParams.get('status')).toBe('open')
    expect(parsed.searchParams.get('severity')).toBe('error')
    expect(parsed.searchParams.get('limit')).toBe('20')
    expect(parsed.searchParams.get('offset')).toBe('40')
    // Paired: an omitted filter (source) never appears as an empty param.
    expect(parsed.searchParams.has('source')).toBe(false)
  })

  it('omits empty-string filter values rather than sending them as blank params', async () => {
    const fetchMock = vi.fn(async (_url: string) => jsonResponse({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    await listErrorReports({ status: '', severity: 'warning' })

    const [url] = fetchMock.mock.calls[0]
    const parsed = new URL(url, 'http://localhost')
    expect(parsed.searchParams.has('status')).toBe(false)
    expect(parsed.searchParams.get('severity')).toBe('warning')
  })
})

describe('getErrorReport', () => {
  it('GETs the single-report detail endpoint by id', async () => {
    const report = { id: 'abc-123', status: 'open' }
    const fetchMock = vi.fn(async (_url: string) => jsonResponse(report))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getErrorReport('abc-123')

    expect(result).toEqual(report)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/error-reports/abc-123')
  })

  it('rejects with the RFC 9457 detail when the id is not found', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ title: 'Error report not found', status: 404, detail: 'no such id' }, 404),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(getErrorReport('missing')).rejects.toMatchObject({ status: 404 })
  })
})

describe('updateErrorReport', () => {
  it('PATCHes description and status together', async () => {
    const updated = { id: 'abc-123', status: 'resolved', user_description: 'fixed it' }
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/csrf-token')) return jsonResponse({ csrf_token: 't1' })
      expect(init?.method).toBe('PATCH')
      expect(JSON.parse(String(init?.body))).toEqual({
        description: 'fixed it',
        status: 'resolved',
      })
      return jsonResponse(updated)
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await updateErrorReport('abc-123', { description: 'fixed it', status: 'resolved' })
    expect(result).toEqual(updated)
  })
})

describe('deleteErrorReport', () => {
  it('DELETEs the report by id', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/csrf-token')) return jsonResponse({ csrf_token: 't1' })
      expect(init?.method).toBe('DELETE')
      return jsonResponse({ ok: true, id: 'abc-123' })
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await deleteErrorReport('abc-123')
    expect(result).toEqual({ ok: true, id: 'abc-123' })
  })
})
