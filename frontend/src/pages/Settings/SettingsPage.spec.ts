import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getKeywordPools: vi.fn(),
  saveKeywordPools: vi.fn(),
  getScheduleSettings: vi.fn(),
  saveScheduleSettings: vi.fn(),
}))

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import SettingsPage from './SettingsPage.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getKeywordPools).mockResolvedValue({
    targets: ['https://x.com'],
    pools: { 'https://x.com': ['alpha', 'beta'] },
  })
  vi.mocked(api.getScheduleSettings).mockResolvedValue({
    min_interval_hours: 4,
    jitter_minutes: 30,
  })
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SettingsPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('SettingsPage — global config', () => {
  it('hydrates the keyword editor and the schedule form from GET', async () => {
    const w = mountPage()
    await flushPromises()
    const ta = w.find('textarea')
    expect(ta.exists()).toBe(true)
    expect((ta.element as HTMLTextAreaElement).value).toBe('alpha\nbeta')
    const num = w.find('input[type="number"]')
    expect((num.element as HTMLInputElement).value).toBe('4')
  })

  it('saves keyword pools → success toast, sending trimmed non-empty lines', async () => {
    vi.mocked(api.saveKeywordPools).mockResolvedValue({ ok: true, message: '关键词已保存' })
    const w = mountPage()
    await flushPromises()
    await w.find('textarea').setValue('alpha\n  gamma  \n\n')
    await w.findAll('form')[0].trigger('submit')
    await flushPromises()
    expect(api.saveKeywordPools).toHaveBeenCalledWith({ 'https://x.com': ['alpha', 'gamma'] })
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('surfaces a 422 keyword rejection as a warning toast carrying the detail', async () => {
    vi.mocked(api.saveKeywordPools).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '关键词过长（>60字符）: XXX…' }),
    )
    const w = mountPage()
    await flushPromises()
    await w.findAll('form')[0].trigger('submit')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
    expect(notify.toasts.at(-1)?.message).toContain('关键词过长')
  })

  it('saves schedule settings → success toast', async () => {
    vi.mocked(api.saveScheduleSettings).mockResolvedValue({ ok: true, message: '排程设定已保存' })
    const w = mountPage()
    await flushPromises()
    await w.findAll('form')[1].trigger('submit')
    await flushPromises()
    expect(api.saveScheduleSettings).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })
})
