import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({ getChannels: vi.fn() }))

import * as api from '../../api/settings'
import SettingsSidebar from './SettingsSidebar.vue'

let pinia: ReturnType<typeof createPinia>

function channel(over: Partial<api.ChannelOverviewItem> = {}): api.ChannelOverviewItem {
  return {
    slug: 's', display_name: 'S', auth_type: 'token', bound: false, identity: null,
    dofollow: null, last_verify_result: null, blockers: [], ...over,
  }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getChannels).mockResolvedValue({ channels: [] })
})

function mountNav() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SettingsSidebar, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('SettingsSidebar', () => {
  it('renders a jump link per section', async () => {
    const w = mountNav()
    await flushPromises()
    const items = w.findAll('.snav__item')
    const labels = items.map((b) => b.text())
    expect(labels).toContain('渠道总览')
    expect(labels).toContain('Notion')
    expect(labels).toContain('Blog ID 映射')
    expect(labels).toContain('AI 整合')
    expect(items.length).toBe(10)
  })

  it('summarises bound/total channels from the overview query', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [
        channel({ slug: 'a', bound: true }),
        channel({ slug: 'b', bound: false, blockers: ['未登录'] }),
        channel({ slug: 'c', bound: true }),
      ],
    })
    const w = mountNav()
    await flushPromises()
    expect(w.find('[data-test="snav-overview"]').text()).toContain('2/3')
    expect(w.text()).toContain('有阻断项')
  })

  it('scrolls to the section when a link is clicked', async () => {
    const target = document.createElement('div')
    target.id = 'sec-blogids'
    const scrollIntoView = vi.fn()
    target.scrollIntoView = scrollIntoView
    document.body.appendChild(target)
    try {
      const w = mountNav()
      await flushPromises()
      const link = w.findAll('.snav__item').find((b) => b.text() === 'Blog ID 映射')
      await link!.trigger('click')
      expect(scrollIntoView).toHaveBeenCalled()
    } finally {
      target.remove()
    }
  })
})
