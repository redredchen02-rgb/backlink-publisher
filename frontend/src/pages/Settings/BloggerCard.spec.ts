import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getBloggerStatus: vi.fn(),
  saveBloggerOauth: vi.fn(),
  revokeBlogger: vi.fn(),
}))

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import BloggerCard from './BloggerCard.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useSettingsDirtyStore } from '../../stores/settingsDirty'

let pinia: ReturnType<typeof createPinia>

function statusValue(over: Partial<api.BloggerStatus> = {}): api.BloggerStatus {
  return {
    authorized: false,
    client_id: '',
    client_secret_set: false,
    callback_uri: 'http://localhost:8888/settings/blogger/oauth-callback',
    ...over,
  }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  // csrfToken() reads this <meta> synchronously (no fetch needed in jsdom).
  document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  vi.mocked(api.getBloggerStatus).mockResolvedValue(statusValue())
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(BloggerCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

function mountCardWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(BloggerCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
  return { wrapper, queryClient }
}

function btn(w: ReturnType<typeof mountCard>, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('BloggerCard', () => {
  it('shows the callback URI + unauthorized badge and hides revoke when not authorized', async () => {
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="blogger-badge"]').text()).toContain('未授权')
    expect(w.text()).toContain('oauth-callback')
    expect(btn(w, '撤销授权')).toBeFalsy()
  })

  it('hydrates client_id, shows a "已设置" secret placeholder and a revoke button when authorized', async () => {
    vi.mocked(api.getBloggerStatus).mockResolvedValue(
      statusValue({ authorized: true, client_id: 'cid.apps', client_secret_set: true }),
    )
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="blogger-badge"]').text()).toContain('已授权')
    expect((w.find('#bg-cid').element as HTMLInputElement).value).toBe('cid.apps')
    expect((w.find('#bg-secret').element as HTMLInputElement).placeholder).toContain('已设置')
    expect(btn(w, '撤销授权')).toBeTruthy()
  })

  it('saves credentials → success toast, then clears the secret input', async () => {
    vi.mocked(api.saveBloggerOauth).mockResolvedValue({ ok: true, message: '凭据已确认绑定' })
    const w = mountCard()
    await flushPromises()
    await w.find('#bg-cid').setValue('my-cid.apps')
    await w.find('#bg-secret').setValue('GOCSPX-secret')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveBloggerOauth).toHaveBeenCalledWith('my-cid.apps', 'GOCSPX-secret')
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
    expect((w.find('#bg-secret').element as HTMLInputElement).value).toBe('')
  })

  it('W6: a 422 mentioning Client Secret renders inline under that field, not a global toast', async () => {
    vi.mocked(api.saveBloggerOauth).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '请填写 Client Secret' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="err-client-secret"]').text()).toContain('Client Secret')
    expect(w.find('[data-test="blogger-form-error"]').exists()).toBe(false)
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('W6: a 422 with an unattributable detail renders the shared form-error banner', async () => {
    vi.mocked(api.saveBloggerOauth).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '未知校验错误' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="blogger-form-error"]').text()).toBe('未知校验错误')
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('Google login submits a full-page form to the legacy oauth-start route with CSRF', async () => {
    const submit = vi.fn()
    const proto = HTMLFormElement.prototype as unknown as { submit: () => void }
    const orig = proto.submit
    proto.submit = submit
    try {
      const w = mountCard()
      await flushPromises()
      await w.find('#bg-cid').setValue('cid.apps')
      await btn(w, '使用 Google 帐号登入')!.trigger('click')
      await flushPromises()
      expect(submit).toHaveBeenCalled()
      const form = document.querySelector('form[action="/settings/blogger/oauth-start"]') as HTMLFormElement
      expect(form).toBeTruthy()
      const fd = new FormData(form)
      expect(fd.get('csrf_token')).toBe('test-csrf')
      expect(fd.get('client_id')).toBe('cid.apps')
    } finally {
      proto.submit = orig
    }
  })

  it('revokes authorization after confirming in the shared ConfirmDialog → success toast', async () => {
    // W3: native window.confirm was migrated to ConfirmDialog — same semantics
    // (confirm → revoke), now rendered as an in-page modal.
    vi.mocked(api.getBloggerStatus).mockResolvedValue(statusValue({ authorized: true }))
    vi.mocked(api.revokeBlogger).mockResolvedValue({ ok: true, message: 'Blogger 授权已撤销' })
    const w = mountCard()
    await flushPromises()

    await btn(w, '撤销授权')!.trigger('click')
    const dialog = w.find('[role="dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.text()).toContain('下次发布前需重新登入')
    expect(api.revokeBlogger).not.toHaveBeenCalled() // nothing happens before confirm

    await btn(w, '确认撤销')!.trigger('click')
    await flushPromises()
    expect(api.revokeBlogger).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
    expect(w.find('[role="dialog"]').exists()).toBe(false)
  })

  it('cancelling the revoke dialog performs no revoke (window.confirm(false) semantics)', async () => {
    vi.mocked(api.getBloggerStatus).mockResolvedValue(statusValue({ authorized: true }))
    const w = mountCard()
    await flushPromises()

    await btn(w, '撤销授权')!.trigger('click')
    expect(w.find('[role="dialog"]').exists()).toBe(true)
    await btn(w, '取消')!.trigger('click')
    expect(w.find('[role="dialog"]').exists()).toBe(false)
    expect(api.revokeBlogger).not.toHaveBeenCalled()
  })

  it('REGRESSION (W2): unsaved client_id edit survives a non-focus query-data change', async () => {
    const { wrapper: w, queryClient } = mountCardWithClient()
    await flushPromises()
    await w.find('#bg-cid').setValue('typed-cid.apps')

    queryClient.setQueryData(['settings', 'blogger-status'], statusValue({ client_id: 'server-cid.apps' }))
    await flushPromises()

    expect((w.find('#bg-cid').element as HTMLInputElement).value).toBe('typed-cid.apps')
  })

  it('marks the card dirty while editing and clean again after a successful save', async () => {
    vi.mocked(api.saveBloggerOauth).mockResolvedValue({ ok: true, message: 'ok' })
    const w = mountCard()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(false)

    await w.find('#bg-cid').setValue('typing…')
    expect(dirtyStore.anyDirty).toBe(true)
    expect(dirtyStore.dirtyLabels).toContain('Blogger')

    await w.find('form').trigger('submit')
    await flushPromises()
    expect(dirtyStore.anyDirty).toBe(false)
  })
})
