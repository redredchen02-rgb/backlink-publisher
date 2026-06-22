import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getVelogStatus: vi.fn(),
  velogLogin: vi.fn(),
}))

import * as api from '../../api/settings'
import VelogCard from './VelogCard.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getVelogStatus).mockResolvedValue({
    state: 'err', label: '未绑定', guide: '运行: velog-login', cookies_path: '', count: 0, cap: 5,
  })
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(VelogCard, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

function btn(w: ReturnType<typeof mountCard>, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('VelogCard', () => {
  it('renders the status badge + guide and a bind button when unbound', async () => {
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="velog-badge"]').text()).toContain('未绑定')
    expect(w.find('[data-test="velog-guide"]').text()).toContain('velog-login')
    expect(btn(w, '绑定 velog')).toBeTruthy()
  })

  it('shows quota + rebind label and hides the guide when bound', async () => {
    vi.mocked(api.getVelogStatus).mockResolvedValue({
      state: 'ok', label: '已绑定', guide: '', cookies_path: '/c/velog-cookies.json', count: 2, cap: 5,
    })
    const w = mountCard()
    await flushPromises()
    expect(w.text()).toContain('今日已发 2 / 5')
    expect(w.find('[data-test="velog-guide"]').exists()).toBe(false)
    expect(btn(w, '重新绑定')).toBeTruthy()
  })

  it('spawns the login window and toasts success', async () => {
    vi.mocked(api.velogLogin).mockResolvedValue({
      ok: true, message: '已启动 velog 登录窗口', error_code: null, log_path: '/c/velog.log',
    })
    const w = mountCard()
    await flushPromises()
    await btn(w, '绑定 velog')!.trigger('click')
    await flushPromises()
    expect(api.velogLogin).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('surfaces a failed spawn (ok:false) as a warning toast, not an error', async () => {
    vi.mocked(api.velogLogin).mockResolvedValue({
      ok: false, message: 'Playwright 未安装。', error_code: 'playwright_not_installed', log_path: '/c/velog.log',
    })
    const w = mountCard()
    await flushPromises()
    await btn(w, '绑定 velog')!.trigger('click')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
    expect(notify.toasts.at(-1)?.message).toContain('Playwright')
  })
})
