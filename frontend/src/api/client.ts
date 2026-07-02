// Plan 2026-06-18-002 U3 — API client (ported from webui_app/static/js/lib/api.js).
//
// Preserves the anti-rot REASONS, mapped to the SPA:
//  - CSRF token is never cached in a persisted store (a rotated token would 403);
//    held only in a module-local var and force-refreshed on any 403.
//  - In the legacy server-rendered page the token came from <meta name="csrf-token">
//    read per call; the SPA has no server-rendered meta, so it reads the token
//    from the /api/v1/csrf-token endpoint (still single-origin, still per-session).
//  - All calls are same-origin relative '/api/...' paths (dev Vite proxy mirrors
//    the prod reverse-origin), so no CORS and the session cookie rides along.

const API_BASE = '/api/v1'

let _csrf: string | null = null

/** Read a server-rendered <meta> token if present, else fetch + hold it. */
export async function csrfToken(force = false): Promise<string> {
  if (!force) {
    const meta = document
      .querySelector('meta[name="csrf-token"]')
      ?.getAttribute('content')
    if (meta) return meta
    if (_csrf) return _csrf
  }
  const resp = await fetch(`${API_BASE}/csrf-token`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw await toError(resp)
  _csrf = (await resp.json()).csrf_token as string
  return _csrf
}

export class ApiError extends Error {
  status: number
  payload: unknown
  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

async function toError(resp: Response): Promise<ApiError> {
  let payload: unknown = null
  try {
    payload = await resp.json()
  } catch {
    /* non-JSON body */
  }
  const detail =
    (payload && typeof payload === 'object' && 'detail' in payload
      ? String((payload as Record<string, unknown>).detail)
      : '') || `HTTP ${resp.status}`
  return new ApiError(detail, resp.status, payload)
}

/** GET a JSON resource under /api/v1. */
export async function getJson<T = unknown>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (!resp.ok) throw await toError(resp)
  return (await resp.json()) as T
}

export interface SendJsonOptions {
  /** Passed straight through to `fetch`'s `keepalive` option — lets a
   *  request started right before page unload (e.g. Unit 6's error-capture
   *  submission) still complete. Not used by any existing caller, so the
   *  default (`false`/omitted) preserves today's behavior exactly. */
  keepalive?: boolean
}

/** Send a mutating JSON request with a fresh CSRF token; retry once on 403. */
export async function sendJson<T = unknown>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
  options?: SendJsonOptions,
): Promise<T> {
  const doSend = async (token: string): Promise<Response> =>
    fetch(`${API_BASE}${path}`, {
      method,
      credentials: 'same-origin',
      keepalive: options?.keepalive ?? false,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-CSRFToken': token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })

  let resp = await doSend(await csrfToken())
  if (resp.status === 403) {
    // Token may have rotated — drop the cached one and retry once with a fresh.
    _csrf = null
    resp = await doSend(await csrfToken(true))
  }
  if (!resp.ok) throw await toError(resp)
  return (await resp.json()) as T
}

/** Test seam: reset the in-memory token (never persisted anyway). */
export function _resetCsrfForTest(): void {
  _csrf = null
}
