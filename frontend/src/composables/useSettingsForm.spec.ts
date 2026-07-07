import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsForm } from './useSettingsForm'
import { ApiError } from '../api/client'
import { useNotificationsStore } from '../stores/notifications'

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
})
