// Plan 2026-06-18-002 U3 — API client (ported from webui_app/static/js/lib/api.js).
//
// Preserves the anti-rot REASONS:
//  - CSRF token is never cached in a persisted store (a rotated token would 403);
//    held only in a module-local var and force-refreshed on any 403.
//  - In the legacy server-rendered page the token came from <meta name="csrf-token">
//    read per call; the SPA has no server-rendered meta, so it reads the token
//    from the /api/v1/csrf-token endpoint (still single-origin, still per-session).
//  - All calls are same-origin relative '/api/...' paths (dev Vite proxy mirrors
//    the prod reverse-origin), so no CORS and the session cookie rides along.
//
// Enhancements (Phase 3+ T3.3):
//  - AbortController-based timeout (default 15 s)
//  - Request deduplication: concurrent GETs to the same path share one fetch
//  - Retry on network error (1 retry, not on 4xx/5xx — those are true errors)

const API_BASE = '/api/v1'

// ── CSRF token ────────────────────────────────────────────────────────────────

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

// ── Error types ───────────────────────────────────────────────────────────────

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

// ── Timeout helper ────────────────────────────────────────────────────────────

const DEFAULT_TIMEOUT_MS = 15_000

function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  return fetch(url, { ...init, signal: ctrl.signal }).finally(() =>
    clearTimeout(timer),
  )
}

// ── Request deduplication (GET only — mutations must not be deduped) ──────────

interface PendingPromise<T> {
  promise: Promise<T>
  timestamp: number
}

/** In-flight GET promises keyed by path — shared across concurrent callers. */
const _inflight = new Map<string, PendingPromise<unknown>>()

/** Max age (ms) for a cached in-flight promise before a new call re-fetches. */
const _INFLIGHT_TTL = 5_000

function dedupKey(path: string, init?: RequestInit): string {
  // Use the path + a hash of non-default init options.
  // For simple GETs with no custom headers this is just `GET:<path>`.
  if (!init || Object.keys(init).length === 0) return `GET:${path}`
  const stable = JSON.stringify(init, Object.keys(init).sort())
  return `GET:${path}:${stable}`
}

/** Wrap a GET fetch with deduplication. */
async function dedupedGet<T>(
  path: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<T> {
  const key = dedupKey(path, init)

  // Check existing in-flight that hasn't expired.
  const pending = _inflight.get(key)
  if (pending && Date.now() - pending.timestamp < _INFLIGHT_TTL) {
    return pending.promise as Promise<T>
  }

  const promise = fetchWithTimeout(`${API_BASE}${path}`, init, timeoutMs).then(
    async (resp) => {
      if (!resp.ok) throw await toError(resp)
      return (await resp.json()) as T
    },
  )

  _inflight.set(key, { promise, timestamp: Date.now() })

  // Clean up on settle. The caller (returned below) owns rejection handling;
  // this branch must swallow it too or a rejected `promise` produces an
  // unhandled rejection here since `.finally()` re-throws.
  promise
    .finally(() => {
      if (_inflight.get(key)?.promise === promise) {
        _inflight.delete(key)
      }
    })
    .catch(() => {})

  return promise
}

// ── Retry helper (network errors only) ────────────────────────────────────────

const MAX_RETRIES = 1
const RETRY_DELAY_MS = 300

async function withRetry<T>(
  fn: () => Promise<T>,
  retries = MAX_RETRIES,
): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn()
    } catch (err) {
      // Only retry on network/infrastructure errors (Timeout, TypeError, etc.)
      // NOT on ApiError (4xx/5xx) — those are true server responses.
      const isNetworkErr =
        err instanceof TypeError ||
        (err instanceof DOMException && err.name === 'AbortError')
      if (!isNetworkErr || attempt >= retries) throw err
      await new Promise((r) => setTimeout(r, RETRY_DELAY_MS))
      if (process.env.NODE_ENV === 'development') {
        console.debug(`[api] retrying after error:`, (err as Error).message)
      }
    }
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/** GET a JSON resource under /api/v1 with timeout + deduplication + retry. */
export async function getJson<T = unknown>(
  path: string,
  options?: { timeoutMs?: number; noDedup?: boolean },
): Promise<T> {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const init: RequestInit = {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  }

  const doFetch = () =>
    options?.noDedup
      ? (fetchWithTimeout(`${API_BASE}${path}`, init, timeoutMs).then(
          async (resp) => {
            if (!resp.ok) throw await toError(resp)
            return (await resp.json()) as T
          },
        ) as Promise<T>)
      : dedupedGet<T>(path, init, timeoutMs)

  return withRetry(doFetch)
}

export interface SendJsonOptions {
  /** Passed straight through to `fetch`'s `keepalive` option — lets a
   *  request started right before page unload (e.g. Unit 6's error-capture
   *  submission) still complete. Not used by any existing caller, so the
   *  default (`false`/omitted) preserves today's behavior exactly. */
  keepalive?: boolean
  /** Overrides `DEFAULT_TIMEOUT_MS` for this call. */
  timeoutMs?: number
}

/** Send a mutating JSON request with a fresh CSRF token; retry once on 403. */
export async function sendJson<T = unknown>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
  options?: SendJsonOptions,
): Promise<T> {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS

  const doSend = async (token: string): Promise<Response> =>
    fetchWithTimeout(`${API_BASE}${path}`, {
      method,
      credentials: 'same-origin',
      keepalive: options?.keepalive ?? false,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-CSRFToken': token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    }, timeoutMs)

  const doSendWithCsrf = async (): Promise<T> => {
    let resp = await doSend(await csrfToken())
    if (resp.status === 403) {
      // Token may have rotated — drop the cached one and retry once with a fresh.
      _csrf = null
      resp = await doSend(await csrfToken(true))
    }
    if (!resp.ok) throw await toError(resp)
    return (await resp.json()) as T
  }

  return withRetry(doSendWithCsrf)
}

/** Test seam: reset the in-memory token (never persisted anyway). */
export function _resetCsrfForTest(): void {
  _csrf = null
  _inflight.clear()
}
