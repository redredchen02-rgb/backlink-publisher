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

  it('surfaces a 422 missing-creds rejection as a warning toast', async () => {
    vi.mocked(api.saveBloggerOauth).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '请填写 Client ID 和 Client Secret' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
    expect(notify.toasts.at(-1)?.message).toContain('Client ID')
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

  it('revokes authorization after confirm → success toast', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.mocked(api.getBloggerStatus).mockResolvedValue(statusValue({ authorized: true }))
    vi.mocked(api.revokeBlogger).mockResolvedValue({ ok: true, message: 'Blogger 授权已撤销' })
    const w = mountCard()
    await flushPromises()
    await btn(w, '撤销授权')!.trigger('click')
    await flushPromises()
    expect(api.revokeBlogger).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })
})
