import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsForm } from './useSettingsForm'
import { ApiError, _resetCsrfForTest } from '../api/client'
import { useNotificationsStore } from '../stores/notifications'
import { _resetCaptureStateForTest } from '../lib/errorCapture'

// useSettingsForm only touches plain `ref`/`reactive` + a Pinia store — none
// of that requires an active component instance, so the composable can be
// invoked directly here without a component mount helper.

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('useSettingsForm', () => {
  it('happy path: success toast + markClean, saving toggles true then false', async () => {
    const markClean = vi.fn()
    const form = useSettingsForm(markClean)
    expect(form.saving.value).toBe(false)

    const action = vi.fn().mockResolvedValue({ message: '已保存 ✓' })
    const p = form.run(action)
    expect(form.saving.value).toBe(true)
    await p
    expect(form.saving.value).toBe(false)

    expect(action).toHaveBeenCalledTimes(1)
    expect(markClean).toHaveBeenCalledTimes(1)
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)).toMatchObject({ severity: 'success', message: '已保存 ✓' })
  })

  it('falls back to successMessage when the response has no message', async () => {
    const form = useSettingsForm(vi.fn())
    await form.run(() => Promise.resolve({}), { successMessage: '默认成功文案' })
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.message).toBe('默认成功文案')
  })

  it('calls onSuccess with the result before markClean', async () => {
    const order: string[] = []
    const markClean = vi.fn(() => order.push('markClean'))
    const form = useSettingsForm(markClean)
    await form.run(() => Promise.resolve({ message: 'ok', extra: 1 }), {
      onSuccess: (r) => order.push(`onSuccess:${(r as { extra: number }).extra}`),
    })
    expect(order).toEqual(['onSuccess:1', 'markClean'])
  })

  it('422 with no fieldMap match sets formError, never toasts, never calls markClean', async () => {
    const markClean = vi.fn()
    const form = useSettingsForm(markClean)
    const action = vi.fn().mockRejectedValue(new ApiError('rejected', 422, { detail: '关键词校验失败' }))
    await form.run(action)
    expect(form.formError.value).toBe('关键词校验失败')
    expect(form.fieldErrors).toEqual({})
    expect(markClean).not.toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('422 matching a fieldMap pattern attributes it to fieldErrors, not formError', async () => {
    const form = useSettingsForm(vi.fn(), {
      client_id: /Client ID/,
      client_secret: /Client Secret/,
    })
    await form.run(() =>
      Promise.reject(new ApiError('rejected', 422, { detail: '请填写 Client Secret' })),
    )
    expect(form.fieldErrors.client_secret).toBe('请填写 Client Secret')
    expect(form.fieldErrors.client_id).toBeUndefined()
    expect(form.formError.value).toBeNull()
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('422 with a missing detail falls back to a generic message', async () => {
    const form = useSettingsForm(vi.fn())
    await form.run(() => Promise.reject(new ApiError('rejected', 422, {})))
    expect(form.formError.value).toBe('校验失败')
  })

  it('non-422 errors route through the classifyError toast, not inline state', async () => {
    const form = useSettingsForm(vi.fn())
    await form.run(() => Promise.reject(new ApiError('server exploded', 500, { detail: 'boom' })))
    expect(form.formError.value).toBeNull()
    expect(form.fieldErrors).toEqual({})
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('error')
  })

  it('clearErrors resets both error surfaces', async () => {
    const form = useSettingsForm(vi.fn())
    await form.run(() => Promise.reject(new ApiError('rejected', 422, { detail: 'x' })))
    expect(form.formError.value).toBe('x')
    form.clearErrors()
    expect(form.formError.value).toBeNull()
  })

  it('a run() re-clears stale errors from a previous failed attempt on the next call', async () => {
    const form = useSettingsForm(vi.fn())
    await form.run(() => Promise.reject(new ApiError('rejected', 422, { detail: 'first failure' })))
    expect(form.formError.value).toBe('first failure')
    await form.run(() => Promise.resolve({ message: 'ok' }))
    expect(form.formError.value).toBeNull()
  })

  it('re-entrant run() while saving is a no-op (does not double-invoke the action)', async () => {
    const form = useSettingsForm(vi.fn())
    let resolveAction: (v: { message: string }) => void = () => {}
    const action = vi.fn(
      () =>
        new Promise<{ message: string }>((resolve) => {
          resolveAction = resolve
        }),
    )
    const p1 = form.run(action)
    const p2 = form.run(action)
    expect(await p2).toBeUndefined()
    resolveAction({ message: 'done' })
    await p1
    expect(action).toHaveBeenCalledTimes(1)
  })

  // ── W13: error-reports coverage (discovery #4 / D8) ────────────────────────
  //
  // End-to-end through the REAL lib/errorCapture module (not mocked) —
  // stubs `fetch` and asserts on POST /error-reports calls, exactly like
  // HistoryPage.spec.ts's equivalent block.

  interface ReportCall {
    url: string
    body: Record<string, unknown>
  }

  function installErrorReportFetchStub(): ReportCall[] {
    const calls: ReportCall[] = []
    let nextId = 1
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : {} })
        return new Response(
          JSON.stringify({ id: `settings-report-${nextId++}` }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    return calls
  }

  describe('W13: error-reports coverage (D8)', () => {
    beforeEach(() => {
      _resetCaptureStateForTest()
      document.head.innerHTML = '<meta name="csrf-token" content="test-token">'
    })

    afterEach(() => {
      vi.unstubAllGlobals()
      _resetCsrfForTest()
      document.head.innerHTML = ''
    })

    it('a 500 save failure shows the classified toast AND submits an error-report', async () => {
      const calls = installErrorReportFetchStub()
      const form = useSettingsForm(vi.fn(), {}, 'settings.llm')
      await form.run(() => Promise.reject(new ApiError('server exploded', 500, { detail: 'boom' })))

      const notify = useNotificationsStore()
      expect(notify.toasts.at(-1)?.severity).toBe('error')
      expect(calls).toHaveLength(1)
      expect(calls[0].url).toContain('/error-reports')
      expect(calls[0].body.message).toContain('settings.llm')
    })

    it('a 422 save failure (inline validation) does NOT submit an error-report (D8)', async () => {
      const calls = installErrorReportFetchStub()
      const form = useSettingsForm(vi.fn())
      await form.run(() => Promise.reject(new ApiError('rejected', 422, { detail: '校验失败' })))

      expect(form.formError.value).toBe('校验失败')
      expect(calls).toHaveLength(0)
    })

    it('a 403 (non-422 4xx, e.g. CSRF) save failure IS reported', async () => {
      const calls = installErrorReportFetchStub()
      const form = useSettingsForm(vi.fn(), {}, 'settings.notion')
      await form.run(() => Promise.reject(new ApiError('forbidden', 403, {})))

      expect(calls).toHaveLength(1)
      expect(calls[0].body.message).toContain('settings.notion')
    })

    it('a network error (TypeError) save failure is reported', async () => {
      const calls = installErrorReportFetchStub()
      const form = useSettingsForm(vi.fn())
      await form.run(() => Promise.reject(new TypeError('Failed to fetch')))

      expect(calls).toHaveLength(1)
    })
  })
})
