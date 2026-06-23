import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({ getChannels: vi.fn() }))

import * as api from '../../api/settings'
import ChannelsCard from './ChannelsCard.vue'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ChannelsCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('ChannelsCard', () => {
  it('renders a row per channel with bind state, identity, dofollow and blockers', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [
        {
          slug: 'blogger',
          display_name: 'Blogger',
          auth_type: 'oauth',
          bound: true,
          identity: 'alice@example.com',
          dofollow: true,
          last_verify_result: 'ok',
          blockers: [],
        },
        {
          slug: 'medium',
          display_name: 'Medium',
          auth_type: 'paste_blob',
          bound: false,
          identity: null,
          dofollow: 'uncertain',
          last_verify_result: 'never',
          blockers: ['Medium 未登录'],
        },
      ],
    })
    const w = mountCard()
    await flushPromises()
    const rows = w.findAll('.ch')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Blogger')
    expect(rows[0].text()).toContain('已绑定')
    expect(rows[0].text()).toContain('alice@example.com')
    expect(rows[0].text()).toContain('dofollow')
    expect(rows[1].text()).toContain('未绑定')
    expect(rows[1].text()).toContain('存疑')
    expect(rows[1].text()).toContain('Medium 未登录')
  })

  it('shows the empty state when no channels are returned', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({ channels: [] })
    const w = mountCard()
    await flushPromises()
    expect(w.find('.ch').exists()).toBe(false)
    expect(w.text()).toContain('无可用渠道')
  })
})
