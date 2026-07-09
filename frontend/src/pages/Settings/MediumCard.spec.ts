import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getMediumStatus: vi.fn(),
  launchMediumLogin: vi.fn(),
  probeMediumLogin: vi.fn(),
  clearMediumLogin: vi.fn(),
  clearMediumOauth: vi.fn(),
}))

import * as api from '../../api/settings'
import MediumCard from './MediumCard.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

function status(over: Partial<api.MediumBrowserStatus> = {}, oauth = false): api.MediumStatus {
  return {
    browser: {
      state: 'no_profile',
      playwright_installed: true,
      profile_has_cookies: false,
      cookies_age_days: null,
      singleton_lock_present: false,
      logged_in: false,
      ...over,
    },
    oauth_token_exists: oauth,
  }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.mocked(api.getMediumStatus).mockResolvedValue(status())
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(MediumCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

function btn(w: ReturnType<typeof mountCard>, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('MediumCard', () => {
  it('renders the browser-readiness badge and the login actions', async () => {
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="medium-badge"]').text()).toContain('浏览器配置未初始化')
    expect(btn(w, '打开浏览器登录')).toBeTruthy()
    expect(btn(w, '测试登录状态')).toBeTruthy()
    // no profile cookies yet → no clear-browser-login button
    expect(btn(w, '清除浏览器登录')).toBeFalsy()
  })

  it('launches browser login and toasts the action level as severity', async () => {
    vi.mocked(api.launchMediumLogin).mockResolvedValue({
      level: 'success', message: 'Medium 浏览器登录完成！', logged_in: true,
    })
    const w = mountCard()
    await flushPromises()
    await btn(w, '打开浏览器登录')!.trigger('click')
    await flushPromises()
    expect(api.launchMediumLogin).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
    expect(notify.toasts.at(-1)?.message).toContain('登录完成')
  })

  it('maps a danger probe outcome to an error toast', async () => {
    vi.mocked(api.probeMediumLogin).mockResolvedValue({
      level: 'danger', message: '探测失败', logged_in: null,
    })
    const w = mountCard()
    await flushPromises()
    await btn(w, '测试登录状态')!.trigger('click')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('error')
  })

  it('hides the action buttons and shows a hint when Playwright is missing', async () => {
    vi.mocked(api.getMediumStatus).mockResolvedValue(status({ state: 'not_installed', playwright_installed: false }))
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="medium-badge"]').text()).toContain('未安装 Playwright')
    expect(btn(w, '打开浏览器登录')).toBeFalsy()
    expect(w.text()).toContain('playwright install chromium')
  })

  it('offers a clear button when an OAuth token exists and revokes it via the confirm dialog', async () => {
    vi.mocked(api.getMediumStatus).mockResolvedValue(status({ state: 'logged_in', logged_in: true }, true))
    vi.mocked(api.clearMediumOauth).mockResolvedValue({ ok: true, message: 'Medium token 已清除' })
    const w = mountCard()
    await flushPromises()
    expect(w.text()).toContain('OAuth token 已存在')
    await btn(w, '清除')!.trigger('click')
    await flushPromises()
    // destructive clear now opens the shared ConfirmDialog (W2) — confirm to proceed
    const confirmBtn = btn(w, '确认清除')
    expect(confirmBtn).toBeTruthy()
    await confirmBtn!.trigger('click')
    await flushPromises()
    expect(api.clearMediumOauth).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })
})
