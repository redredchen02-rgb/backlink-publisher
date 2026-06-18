import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/monitor', () => ({ monitorSummary: vi.fn() }))

import * as api from '../../api/monitor'
import MonitorDashboard from './MonitorDashboard.vue'

function mountDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(MonitorDashboard, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

beforeEach(() => vi.clearAllMocks())

const DANGER_CARD = {
  key: 'credentials',
  title: '渠道凭证',
  severity: 'danger' as const,
  headline: '2 个渠道凭证失效',
  detail: 'medium、blogger',
  deep_link: '/settings',
  action: { label: '去设置', href: '/settings' },
}
const OK_CARD = {
  key: 'keepalive',
  title: '保活',
  severity: 'ok' as const,
  headline: '120 条链接存活',
  detail: '目标 8 · 未知 0',
  deep_link: '/ce:keep-alive',
  action: null,
}

describe('MonitorDashboard — anomaly-first aggregate', () => {
  it('renders server-ranked cards and an anomaly banner when anomalies exist', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [DANGER_CARD, OK_CARD],
      anomaly_count: 1,
      degraded: false,
    })
    const w = mountDashboard()
    await flushPromises()

    const cards = w.findAll('.card')
    expect(cards).toHaveLength(2)
    // Server already ranked danger first; the SPA renders in order (no re-sort).
    expect(cards[0].attributes('data-severity')).toBe('danger')
    expect(w.find('.monitor__summary').text()).toContain('今日 1 项异常')
    // Dual-stack: deep-dive is a plain <a href> (full nav out of the SPA), marked ↪.
    const deep = cards[0].find('a.card__deep')
    expect(deep.attributes('href')).toBe('/settings')
    expect(deep.text()).toContain('↪')
  })

  it('shows the "no anomalies today" banner when all cards are healthy', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD],
      anomaly_count: 0,
      degraded: false,
    })
    const w = mountDashboard()
    await flushPromises()
    expect(w.find('.monitor__summary').text()).toContain('今日无异常')
  })

  it('renders the StateBlock error state (role=alert) when the fetch fails', async () => {
    vi.mocked(api.monitorSummary).mockRejectedValue({ status: 500 })
    const w = mountDashboard()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.findAll('.card')).toHaveLength(0)
  })
})
