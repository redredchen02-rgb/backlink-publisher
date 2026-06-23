import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/schedule', () => ({ listScheduled: vi.fn() }))

import * as api from '../../api/schedule'
import SchedulePage from './SchedulePage.vue'

const ROW = {
  id: 's1',
  title: 'Hello',
  target_url: 'https://a.com/',
  platform: 'velog',
  scheduled_at: '2026-06-20T09:00',
  created_at: '2026-06-18 10:00',
  status: 'scheduled',
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SchedulePage, { global: { plugins: [createPinia(), [VueQueryPlugin, { queryClient }]] } })
}

describe('SchedulePage', () => {
  it('renders a row per scheduled draft', async () => {
    vi.mocked(api.listScheduled).mockResolvedValue({ items: [ROW] })
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('tbody tr')).toHaveLength(1)
    expect(w.text()).toContain('Hello')
    expect(w.text()).toContain('velog')
  })

  it('shows the empty state when nothing is scheduled', async () => {
    vi.mocked(api.listScheduled).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('暂无计划发布')
  })

  it('shows the error state when the fetch fails', async () => {
    vi.mocked(api.listScheduled).mockRejectedValue({ status: 500 })
    const w = mountPage()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })
})
