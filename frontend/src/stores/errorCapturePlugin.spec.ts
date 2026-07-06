// Plan 2026-07-01-002 Unit 6 — errorCapturePlugin.ts unit tests.
//
// Focused on the plugin's own wiring contract (it calls store.$onAction and
// forwards store id + action name + error into errorCapture.ts's
// reportPiniaActionError — never the action's args). The end-to-end
// capture -> fingerprint -> submit -> toast path (including the
// vuejs/pinia#576 regression scenario) is covered by errorCapture.spec.ts;
// this file verifies the plugin in isolation via a mocked reportPiniaActionError.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp } from 'vue'
import { createPinia, defineStore, type Pinia } from 'pinia'

vi.mock('../lib/errorCapture', () => ({
  reportPiniaActionError: vi.fn(),
}))

import { reportPiniaActionError } from '../lib/errorCapture'
import { errorCapturePlugin } from './errorCapturePlugin'

// A Pinia plugin registered via `pinia.use()` is only actually applied to
// stores once the pinia instance is installed on an app: `app.use(pinia)`
// flushes Pinia's internal `toBeInstalled` queue into its active-plugins
// list (see pinia's `install()`/`use()` source) — `setActivePinia(pinia)`
// alone (the pattern this codebase's other store specs use, e.g.
// notifications.spec.ts) is NOT enough for plugin-registration tests
// specifically, since those stores don't use plugins. This mirrors the real
// main.ts order: `pinia.use(errorCapturePlugin)` is called before
// `app.use(pinia)`.
function createPiniaWithPlugin(): Pinia {
  const pinia = createPinia()
  pinia.use(errorCapturePlugin)
  createApp({}).use(pinia)
  return pinia
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('errorCapturePlugin', () => {
  it('happy path: a rejected action forwards the store id + action name + error to reportPiniaActionError', async () => {
    createPiniaWithPlugin()

    const useDemoStore = defineStore('demo', () => {
      async function fail(): Promise<void> {
        throw new Error('boom')
      }
      return { fail }
    })
    const store = useDemoStore()

    await store.fail().catch(() => {})

    expect(reportPiniaActionError).toHaveBeenCalledTimes(1)
    const [storeId, actionName, error] = vi.mocked(reportPiniaActionError).mock.calls[0]
    expect(storeId).toBe('demo')
    expect(actionName).toBe('fail')
    expect(error).toBeInstanceOf(Error)
    expect((error as Error).message).toBe('boom')
  })

  it('paired: a successful action never calls reportPiniaActionError', async () => {
    createPiniaWithPlugin()

    const useDemoStore = defineStore('demoOk', () => {
      async function succeed(): Promise<string> {
        return 'fine'
      }
      return { succeed }
    })
    const store = useDemoStore()

    await store.succeed()

    expect(reportPiniaActionError).not.toHaveBeenCalled()
  })

  it('security: the action call args are never passed to reportPiniaActionError, only the store id/name/error', async () => {
    createPiniaWithPlugin()

    const useSettingsStore = defineStore('settingsDemo', () => {
      async function saveLlmConfig(body: { api_key: string }): Promise<void> {
        void body
        throw new Error('save failed')
      }
      return { saveLlmConfig }
    })
    const store = useSettingsStore()

    await store.saveLlmConfig({ api_key: 'sk-topsecret' }).catch(() => {})

    expect(reportPiniaActionError).toHaveBeenCalledTimes(1)
    const call = vi.mocked(reportPiniaActionError).mock.calls[0]
    // Exactly 3 arguments — storeId, actionName, error — never a 4th
    // "args"/"variables" parameter.
    expect(call).toHaveLength(3)
    expect(call[0]).toBe('settingsDemo')
    expect(call[1]).toBe('saveLlmConfig')
    expect(JSON.stringify(call)).not.toContain('sk-topsecret')
  })

  it('applies to every store registered under the pinia instance it is installed on, not just one', async () => {
    createPiniaWithPlugin()

    const useStoreA = defineStore('storeA', () => {
      async function fail(): Promise<void> {
        throw new Error('a-failed')
      }
      return { fail }
    })
    const useStoreB = defineStore('storeB', () => {
      async function fail(): Promise<void> {
        throw new Error('b-failed')
      }
      return { fail }
    })

    await useStoreA().fail().catch(() => {})
    await useStoreB().fail().catch(() => {})

    expect(reportPiniaActionError).toHaveBeenCalledTimes(2)
    const storeIds = vi.mocked(reportPiniaActionError).mock.calls.map((c) => c[0])
    expect(storeIds).toEqual(['storeA', 'storeB'])
  })
})
