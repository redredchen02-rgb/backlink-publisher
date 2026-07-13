import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('../../api/optimizationStatus', () => ({
  fetchPlatforms: vi.fn(),
  setWeight: vi.fn(),
  unlockWeight: vi.fn(),
}))

import * as api from '../../api/optimizationStatus'
import OptimizationStatusPage from './OptimizationStatusPage.vue'

const PLATFORMS = [
  {
    platform: 'medium',
    weight: 1.5,
    base: 1.0,
    delta_pct: 50,
    adjustments: 2,
    alive: 10,
    total: 12,
    drift: 0.1,
    locked: false,
  },
  {
    platform: 'velog',
    weight: 0.8,
    base: 1.0,
    delta_pct: -20,
    adjustments: 1,
    alive: 5,
    total: 8,
    drift: -0.05,
    locked: true,
  },
]

function mountPage() {
  return mount(OptimizationStatusPage)
}

describe('OptimizationStatusPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the locked marker as a StatusBadge for a locked platform', async () => {
    vi.mocked(api.fetchPlatforms).mockResolvedValue({
      ok: true,
      platforms: PLATFORMS,
      all_platforms: ['medium', 'velog'],
    })
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('🔒 已锁定')
  })

  // Inline-edit machinery previously had no coverage — clicking 设置 reveals
  // the weight input, and saving submits the entered value to the API.
  it('clicking 设置 shows the weight input, and saving calls setWeight with the entered value', async () => {
    vi.mocked(api.fetchPlatforms).mockResolvedValue({
      ok: true,
      platforms: PLATFORMS,
      all_platforms: ['medium', 'velog'],
    })
    vi.mocked(api.setWeight).mockResolvedValue({ ok: true, message: '已设置' })
    const w = mountPage()
    await flushPromises()

    expect(w.find('input[type="number"]').exists()).toBe(false)

    const settingButtons = w.findAll('button').filter((b) => b.text() === '设置')
    await settingButtons[0].trigger('click')

    const input = w.find('input[type="number"]')
    expect(input.exists()).toBe(true)
    expect((input.element as HTMLInputElement).value).toBe('1.5')

    await input.setValue('3.25')

    vi.mocked(api.fetchPlatforms).mockResolvedValue({
      ok: true,
      platforms: PLATFORMS,
      all_platforms: ['medium', 'velog'],
    })
    const saveButton = w.findAll('button').find((b) => b.text() === '保存')
    await saveButton?.trigger('click')
    await flushPromises()

    expect(api.setWeight).toHaveBeenCalledWith('medium', 3.25)
  })
})
