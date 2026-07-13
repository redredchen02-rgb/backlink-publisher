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

const BLOGGER = {
  slug: 'blogger',
  display_name: 'Blogger',
  auth_type: 'oauth',
  bound: true,
  identity: 'alice@example.com',
  dofollow: true,
  last_verify_result: 'ok',
  blockers: [],
}

const MEDIUM = {
  slug: 'medium',
  display_name: 'Medium',
  auth_type: 'paste_blob',
  bound: false,
  identity: null,
  dofollow: 'uncertain',
  last_verify_result: 'never',
  blockers: ['Medium 未登录'],
}

describe('ChannelsCard', () => {
  it('renders unbound channels before bound channels, with bind state, identity, dofollow and blockers', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({ channels: [BLOGGER, MEDIUM] })
    const w = mountCard()
    await flushPromises()
    const rows = w.findAll('.ch')
    expect(rows).toHaveLength(2)
    // Medium (unbound) renders first even though it's second in the API response.
    expect(rows[0].text()).toContain('Medium')
    expect(rows[0].text()).toContain('未绑定')
    expect(rows[0].text()).toContain('存疑')
    expect(rows[0].text()).toContain('Medium 未登录')
    expect(rows[1].text()).toContain('Blogger')
    expect(rows[1].text()).toContain('已绑定')
    expect(rows[1].text()).toContain('alice@example.com')
    expect(rows[1].text()).toContain('dofollow')
  })

  it('renders a top-of-card summary counter reflecting bound/total counts', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({ channels: [BLOGGER, MEDIUM] })
    const w = mountCard()
    await flushPromises()
    expect(w.find('.ch-summary').text()).toContain('1 / 2')
  })

  it('shows only the 已绑定 group when every channel is bound', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [BLOGGER, { ...MEDIUM, bound: true }],
    })
    const w = mountCard()
    await flushPromises()
    expect(w.text()).not.toContain('未绑定 ·')
    expect(w.text()).toContain('已绑定 · 2')
    expect(w.find('.ch-summary').text()).toContain('2 / 2')
  })

  it('shows only the 未绑定 group when every channel is unbound', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [MEDIUM, { ...BLOGGER, bound: false }],
    })
    const w = mountCard()
    await flushPromises()
    expect(w.text()).not.toContain('已绑定 ·')
    expect(w.text()).toContain('未绑定 · 2')
  })

  it('groups carry role="group" and aria-labelledby pointing at their own group label', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({ channels: [BLOGGER, MEDIUM] })
    const w = mountCard()
    await flushPromises()
    const groups = w.findAll('[role="group"]')
    expect(groups).toHaveLength(2)
    for (const g of groups) {
      const labelledBy = g.attributes('aria-labelledby')
      expect(labelledBy).toBeTruthy()
      expect(w.find(`#${labelledBy}`).exists()).toBe(true)
    }
  })

  it('shows the empty state when no channels are returned, with no group headers or summary', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({ channels: [] })
    const w = mountCard()
    await flushPromises()
    expect(w.find('.ch').exists()).toBe(false)
    expect(w.find('.ch-summary').exists()).toBe(false)
    expect(w.find('.group-label').exists()).toBe(false)
    expect(w.text()).toContain('无可用渠道')
  })
})
