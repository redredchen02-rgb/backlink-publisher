// Plan 2026-07-01-002 Unit 6 — tests for the 5 Vue-stack error-capture hooks.
//
// This file's own wiring/integration is what's under test; the underlying
// noise/fingerprint/dedup decision logic already has its own suite
// (tests/js/test_ui_error_capture.mjs) and is not re-tested here (per the
// plan's execution note).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent } from 'vue'
import { createPinia, defineStore, setActivePinia, type Pinia } from 'pinia'
import { QueryCache, QueryClient } from '@tanstack/vue-query'
import { flushPromises } from '@vue/test-utils'

import {
  installGlobalErrorListeners,
  installVueErrorHandler,
  reportRouterError,
  reportQueryError,
  reportMutationError,
  reportManualMutationError,
  shouldReportMutationError,
  _resetGlobalErrorListenersForTest,
  _resetCaptureStateForTest,
} from './errorCapture'
import { errorCapturePlugin } from '../stores/errorCapturePlugin'
import { _resetCsrfForTest, ApiError } from '../api/client'


interface FetchCall {
  url: string
  body: Record<string, unknown>
  keepalive: boolean | undefined
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Stub global fetch: any POST /error-reports succeeds with an incrementing id. */
function installFetchStub(): FetchCall[] {
  const calls: FetchCall[] = []
  let nextId = 1
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url: String(url),
        body: init?.body ? JSON.parse(String(init.body)) : {},
        keepalive: init?.keepalive,
      })
      return jsonResponse({ id: `f6a7b8c9-0000-4000-8000-${String(nextId++).padStart(12, '0')}` }, 201)
    }),
  )
  return calls
}

beforeEach(() => {
  setActivePinia(createPinia())
  _resetCaptureStateForTest()
  _resetGlobalErrorListenersForTest()
  // A <meta> CSRF token avoids sendJson's fallback /csrf-token network call.
  document.head.innerHTML = '<meta name="csrf-token" content="test-token">'
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  _resetCsrfForTest()
  _resetGlobalErrorListenersForTest()
  document.head.innerHTML = ''
})

// A Pinia plugin registered via `pinia.use()` only actually applies to
// stores once the pinia instance is installed on an app (`app.use(pinia)`
// flushes Pinia's internal `toBeInstalled` queue — see errorCapturePlugin
// -> pinia's own `install()`/`use()` source); `setActivePinia(pinia)` alone
// is not enough. Mirrors the real main.ts order: `pinia.use(plugin)` before
// `app.use(pinia)`.
function createPiniaWithPlugin(): Pinia {
  const pinia = createPinia()
  pinia.use(errorCapturePlugin)
  createApp({}).use(pinia)
  return pinia
}

// ── hook 2 + hook 1 boundary ─────────────────────────────────────────────────

describe('hook 2: app.config.errorHandler', () => {
  it('happy path: a setup()-thrown error is caught and produces a submitted report', async () => {
    const calls = installFetchStub()
    const Boom = defineComponent({
      setup() {
        throw new Error('boom-in-setup')
      },
      render() {
        return null
      },
    })
    const app = createApp(Boom)
    installVueErrorHandler(app)
    const el = document.createElement('div')

    expect(() => app.mount(el)).not.toThrow()
    await flushPromises()

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toContain('/error-reports')
    expect(calls[0].body.message).toBe('boom-in-setup')
    expect(calls[0].body.source).toBe('vue-error-handler')
    // keepalive:true so this submission survives a page unload racing the
    // report — the whole reason this transport was chosen over a plain
    // fetch (see the module docstring / client.ts's keepalive option).
    expect(calls[0].keepalive).toBe(true)
  })
})

describe('hook 1 vs hook 2 boundary: window.unhandledrejection', () => {
  it('happy path: a native (non-Vue-scheduled) rejection is caught by window.unhandledrejection, NOT app.config.errorHandler', async () => {
    const calls = installFetchStub()

    const app = createApp({})
    installVueErrorHandler(app)
    const originalHandler = app.config.errorHandler!
    const errorHandlerSpy = vi.fn(originalHandler)
    app.config.errorHandler = errorHandlerSpy as typeof originalHandler

    installGlobalErrorListeners()

    // Simulate a genuinely native rejection (e.g. from a plain
    // addEventListener/setTimeout callback Vue never scheduled) — jsdom
    // doesn't auto-dispatch this from a truly-unhandled promise, so the
    // event is constructed directly, mirroring how the legacy capture
    // engine's own test suite exercises this listener.
    const event = new Event('unhandledrejection') as PromiseRejectionEvent
    Object.defineProperty(event, 'reason', { value: new Error('native rejection'), writable: true })
    window.dispatchEvent(event)
    await flushPromises()

    expect(calls).toHaveLength(1)
    expect(calls[0].body.message).toBe('native rejection')
    expect(calls[0].body.source).toBe('vue-unhandled-rejection')
    // The boundary: this failure surface never reaches app.config.errorHandler.
    expect(errorHandlerSpy).not.toHaveBeenCalled()
  })
})

// ── hook 5: Pinia $onAction onError ──────────────────────────────────────────

describe('hook 5: Pinia $onAction onError (vuejs/pinia#576 regression)', () => {
  it('edge case: a store action rejection is caught by the plugin even when the caller catches it (so it never reaches window.unhandledrejection)', async () => {
    const calls = installFetchStub()
    createPiniaWithPlugin()

    const useDemoStore = defineStore('demo', () => {
      async function boom(): Promise<void> {
        throw new Error('store action failed')
      }
      return { boom }
    })
    const store = useDemoStore()

    const windowRejectionSpy = vi.fn()
    window.addEventListener('unhandledrejection', windowRejectionSpy)
    installGlobalErrorListeners()

    // The caller catches the rejection itself — this specific case is
    // guaranteed to never surface as window.unhandledrejection, which is
    // exactly the vuejs/pinia#576 gap the plugin exists to cover.
    await store.boom().catch(() => {
      /* handled by caller — proves window never sees this rejection */
    })
    await flushPromises()

    expect(windowRejectionSpy).not.toHaveBeenCalled()
    expect(calls).toHaveLength(1)
    expect(calls[0].body.message).toContain('store action failed')
    expect(calls[0].body.message).toContain('demo.boom')
    expect(calls[0].body.source).toBe('vue-pinia-action-error')
  })

  it('security: a store action carrying a secret argument reports only the store id + action name + message, never the args', async () => {
    const calls = installFetchStub()
    createPiniaWithPlugin()

    const useSettingsStore = defineStore('settingsDemo', () => {
      async function saveLlmConfig(body: { api_key: string }): Promise<void> {
        void body
        throw new Error('save failed')
      }
      return { saveLlmConfig }
    })
    const store = useSettingsStore()

    await store.saveLlmConfig({ api_key: 'sk-supersecret123' }).catch(() => {})
    await flushPromises()

    expect(calls).toHaveLength(1)
    const raw = JSON.stringify(calls[0].body)
    // Positive: the action name IS captured (not a blanket field wipe).
    expect(calls[0].body.message).toContain('settingsDemo.saveLlmConfig')
    expect(calls[0].body.message).toContain('save failed')
    // Negative, paired with the positive assertion above: the secret
    // argument value never reaches the submitted payload.
    expect(raw).not.toContain('sk-supersecret123')
    expect(raw).not.toContain('api_key')
  })
})

// ── hook 4: QueryCache / MutationCache onError ──────────────────────────────

describe('hook 4a: QueryCache onError', () => {
  it("edge case: a useQuery fetcher's throw is caught by QueryCache.onError and submitted, not lost", async () => {
    const calls = installFetchStub()
    const client = new QueryClient({
      queryCache: new QueryCache({
        onError: (error, query) => reportQueryError(error, query.queryKey),
      }),
    })

    await expect(
      client.fetchQuery({
        queryKey: ['demo-query'],
        queryFn: () => {
          throw new Error('query blew up')
        },
      }),
    ).rejects.toThrow()
    await flushPromises()

    expect(calls).toHaveLength(1)
    expect(calls[0].body.message).toContain('query blew up')
    expect(calls[0].body.message).toContain('demo-query')
    expect(calls[0].body.source).toBe('vue-query-error')
  })
})

describe('hook 4b: MutationCache onError', () => {
  it('security: a mutation carrying a secret variable reports only the mutation key + message, never variables', async () => {
    const calls = installFetchStub()
    const client = new QueryClient()
    const mutation = client.getMutationCache().build(client, {
      mutationKey: ['saveLlmConfig'],
      mutationFn: async (vars: { api_key: string }) => {
        void vars
        throw new Error('mutation save failed')
      },
    })
    client.getMutationCache().config.onError = (error, _variables, _onMutateResult, m) =>
      reportMutationError(error, m.options.mutationKey)

    await expect(mutation.execute({ api_key: 'sk-anothersecret456' })).rejects.toThrow()
    await flushPromises()

    expect(calls).toHaveLength(1)
    const raw = JSON.stringify(calls[0].body)
    // Positive: the mutation key IS captured.
    expect(calls[0].body.message).toContain('saveLlmConfig')
    expect(calls[0].body.message).toContain('mutation save failed')
    // Negative, paired with the positive assertion above.
    expect(raw).not.toContain('sk-anothersecret456')
    expect(raw).not.toContain('api_key')
  })
})

// ── D8: mutation error-report routing (plan 2026-07-06-005 W13) ────────────

describe('D8 routing: shouldReportMutationError', () => {
  it('excludes ONLY the enumerated expected validation code, 422', () => {
    expect(shouldReportMutationError(new ApiError('rejected', 422, {}))).toBe(false)
  })

  it.each([400, 403, 404, 409, 401, 419])(
    'reports every OTHER 4xx (%d) — CSRF/invariant/aged-out-undo signals are incident-class, not silently excluded',
    (status) => {
      expect(shouldReportMutationError(new ApiError('rejected', status, {}))).toBe(true)
    },
  )

  it('reports 5xx', () => {
    expect(shouldReportMutationError(new ApiError('boom', 500, {}))).toBe(true)
  })

  it('reports network errors (TypeError) — not an ApiError at all', () => {
    expect(shouldReportMutationError(new TypeError('Failed to fetch'))).toBe(true)
  })

  it('reports AbortError (timeout)', () => {
    expect(shouldReportMutationError(new DOMException('The operation was aborted', 'AbortError'))).toBe(
      true,
    )
  })
})

describe('D8 applied to hook 4b: reportMutationError', () => {
  it('a mutation failing with 422 does NOT submit a report', async () => {
    const calls = installFetchStub()
    reportMutationError(new ApiError('rejected', 422, { detail: 'x' }), ['history', 'delete'])
    await flushPromises()
    expect(calls).toHaveLength(0)
  })

  it('a mutation failing with 403 (non-422 4xx) DOES submit a report', async () => {
    const calls = installFetchStub()
    reportMutationError(new ApiError('forbidden', 403, {}), ['history', 'delete'])
    await flushPromises()
    expect(calls).toHaveLength(1)
    expect(calls[0].body.source).toBe('vue-mutation-error')
  })

  it('a mutation failing with 500 DOES submit a report', async () => {
    const calls = installFetchStub()
    reportMutationError(new ApiError('server exploded', 500, {}), ['history', 'delete'])
    await flushPromises()
    expect(calls).toHaveLength(1)
  })
})

describe('reportManualMutationError — HistoryPage/Settings hand-written catch blocks', () => {
  it('a 500 from a manual catch block is reported (History delete example)', async () => {
    const calls = installFetchStub()
    reportManualMutationError(new ApiError('server exploded', 500, {}), 'history.delete')
    await flushPromises()
    expect(calls).toHaveLength(1)
    expect(calls[0].body.message).toContain('history.delete')
  })

  it('a 422 from a manual catch block is NOT reported (Settings inline-validation example)', async () => {
    const calls = installFetchStub()
    reportManualMutationError(new ApiError('rejected', 422, { detail: 'x' }), 'settings.save')
    await flushPromises()
    expect(calls).toHaveLength(0)
  })

  it('a 403 (CSRF) from a manual catch block is reported, not treated as an expected 4xx', async () => {
    const calls = installFetchStub()
    reportManualMutationError(new ApiError('forbidden', 403, {}), 'history.bulk-delete')
    await flushPromises()
    expect(calls).toHaveLength(1)
  })

  it('a 404 (aged-out undo) from a manual catch block is reported', async () => {
    const calls = installFetchStub()
    reportManualMutationError(new ApiError('not found', 404, {}), 'history.undelete')
    await flushPromises()
    expect(calls).toHaveLength(1)
  })

  it('a network error (TypeError) from a manual catch block is reported', async () => {
    const calls = installFetchStub()
    reportManualMutationError(new TypeError('Failed to fetch'), 'history.recheck')
    await flushPromises()
    expect(calls).toHaveLength(1)
  })

  // Plan 2026-07-06-005 W10 — HistoryPage's rowReportLinks correlation relies
  // on this resolving with the LITERAL submitted report id (or null), never a
  // guess. See stores/rowReportLinks.ts's docstring.
  it('resolves with the submitted report id on success — stores/rowReportLinks.ts wires a row to this exact value', async () => {
    installFetchStub()
    const reportId = await reportManualMutationError(new ApiError('server exploded', 500, {}), 'history.delete')
    expect(typeof reportId).toBe('string')
    expect(reportId).toBeTruthy()
  })

  it('resolves with null when the D8 filter excludes the error (422) — never a fabricated id', async () => {
    installFetchStub()
    const reportId = await reportManualMutationError(new ApiError('rejected', 422, {}), 'settings.save')
    expect(reportId).toBeNull()
  })
})

// ── hook 3: router.onError ───────────────────────────────────────────────────

describe('hook 3: router.onError', () => {
  it('integration: a router-guard error produces a report with a source tag distinct from a component render error', async () => {
    const calls = installFetchStub()

    // Component render error (hook 2), for comparison.
    const Boom = defineComponent({
      setup() {
        throw new Error('render-side failure')
      },
      render() {
        return null
      },
    })
    const app = createApp(Boom)
    installVueErrorHandler(app)
    app.mount(document.createElement('div'))

    // Router-guard error (hook 3) — a genuinely different message so it
    // isn't folded by the in-tab dedup tracker.
    reportRouterError(new Error('navigation guard failure'))
    await flushPromises()

    expect(calls).toHaveLength(2)
    const sources = calls.map((c) => c.body.source)
    expect(sources).toContain('vue-error-handler')
    expect(sources).toContain('vue-router-error')
    expect(new Set(sources).size).toBe(2) // genuinely distinct, not double-counted under one tag
  })
})

// ── self-origin filter (shared error-capture-core.js guard) ─────────────────

describe('self-origination guard', () => {
  it('edge case: an error whose stack points at this capture module itself is filtered and never submitted', async () => {
    const calls = installFetchStub()
    const selfError = Object.assign(new Error('capture bug'), {
      stack: 'Error: capture bug\n    at reportRouterError (frontend/src/lib/errorCapture.ts:200:5)',
    })

    reportRouterError(selfError)
    await flushPromises()

    expect(calls).toHaveLength(0)
  })

  it('paired: a superficially similar error from a DIFFERENT module IS submitted', async () => {
    const calls = installFetchStub()
    const otherError = Object.assign(new Error('capture bug'), {
      stack: 'Error: capture bug\n    at doThing (frontend/src/pages/Publish/PublishWorkbench.vue:200:5)',
    })

    reportRouterError(otherError)
    await flushPromises()

    expect(calls).toHaveLength(1)
  })
})
