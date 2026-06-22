import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getNotionStatus: vi.fn(),
  saveNotionToken: vi.fn(),
  clearNotionToken: vi.fn(),
}))

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import NotionCard from './NotionCard.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

function statusValue(over: Partial<api.NotionStatus> = {}): api.NotionStatus {
  return { configured: false, database_id: '', ...over }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getNotionStatus).mockResolvedValue(statusValue())
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(NotionCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

function btn(w: ReturnType<typeof mountCard>, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('NotionCard', () => {
  it('shows the unconfigured badge and hides the clear button', async () => {
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="notion-badge"]').text()).toContain('未配置')
    expect(btn(w, '清除')).toBeFalsy()
  })

  it('hydrates database_id, shows the "已配置" token placeholder and a clear button', async () => {
    vi.mocked(api.getNotionStatus).mockResolvedValue(
      statusValue({ configured: true, database_id: 'db_abc123' }),
    )
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="notion-badge"]').text()).toContain('已配置')
    expect((w.find('#nt-db').element as HTMLInputElement).value).toBe('db_abc123')
    // The secret is never pre-filled — only a hint placeholder.
    expect((w.find('#nt-token').element as HTMLInputElement).value).toBe('')
    expect((w.find('#nt-token').element as HTMLInputElement).placeholder).toContain('已配置')
    expect(btn(w, '清除')).toBeTruthy()
  })

  it('saves both fields → success toast, then clears the secret input', async () => {
    vi.mocked(api.saveNotionToken).mockResolvedValue({ ok: true, message: 'notion token 已绑定 ✓' })
    const w = mountCard()
    await flushPromises()
    await w.find('#nt-token').setValue('secret_xyz')
    await w.find('#nt-db').setValue('db_123')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveNotionToken).toHaveBeenCalledWith('secret_xyz', 'db_123')
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
    expect((w.find('#nt-token').element as HTMLInputElement).value).toBe('')
  })

  it('surfaces a 422 missing-field rejection as a warning toast', async () => {
    vi.mocked(api.saveNotionToken).mockRejectedValue(
      new ApiError('rejected', 422, { detail: 'Integration Token 不能为空' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
    expect(notify.toasts.at(-1)?.message).toContain('Integration Token')
  })

  it('clears the credential after confirm → success toast', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.mocked(api.getNotionStatus).mockResolvedValue(statusValue({ configured: true }))
    vi.mocked(api.clearNotionToken).mockResolvedValue({ ok: true, cleared: true, message: 'notion token 已清除' })
    const w = mountCard()
    await flushPromises()
    await btn(w, '清除')!.trigger('click')
    await flushPromises()
    expect(api.clearNotionToken).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })
})
