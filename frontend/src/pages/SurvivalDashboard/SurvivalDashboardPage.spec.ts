import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('../../api/survival', () => ({
  fetchSurvival: vi.fn(),
}))

import * as api from '../../api/survival'
import SurvivalDashboardPage from './SurvivalDashboardPage.vue'
import Icon from '../../components/Icon.vue'

const READY_VIEW = {
  state: 'ok' as const,
  survival_rate: 0.92,
  sample_size: 40,
  survived: 37,
  mature_count: 40,
  maturing_count: 5,
  stale: true,
  stale_count: 3,
  partial: false,
  stale_days: 12,
  has_rate: true,
  display: '92%',
  headline: '存活率良好',
  sub: '近 30 天成熟样本表现稳定',
  cohort_days: 30,
}

beforeEach(() => {
  vi.clearAllMocks()
})

function mountPage() {
  return mount(SurvivalDashboardPage)
}

describe('SurvivalDashboardPage', () => {
  it('mounts and renders the ready state after the fetch resolves', async () => {
    vi.mocked(api.fetchSurvival).mockResolvedValue(READY_VIEW)
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('存活率良好')
    expect(w.text()).toContain('92%')
  })

  it('renders the shield-check and exclamation-triangle-fill Icons with valid, known names, without console.warn', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(api.fetchSurvival).mockResolvedValue(READY_VIEW)
    const w = mountPage()
    await flushPromises()

    const icons = w.findAllComponents(Icon)
    const names = icons.map((icon) => icon.props('name'))
    expect(names).toContain('shield-check')
    expect(names).toContain('exclamation-triangle-fill')

    for (const icon of icons) {
      const svg = icon.find('svg')
      expect(svg.exists()).toBe(true)
      expect(svg.findAll('path').length).toBeGreaterThan(0)
    }

    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })
})
