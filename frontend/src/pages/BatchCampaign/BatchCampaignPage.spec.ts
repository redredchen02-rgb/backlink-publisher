import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/campaigns', () => ({
  getCampaignForm: vi.fn(),
  createCampaign: vi.fn(),
}))

import * as api from '../../api/campaigns'
import type { CampaignForm } from '../../api/campaigns'
import { ApiError } from '../../api/client'
import BatchCampaignPage from './BatchCampaignPage.vue'

const FLAT_FORM: CampaignForm = { platforms: ['blogger', 'velog'], publish_partition: null }
const PARTITION_FORM: CampaignForm = {
  platforms: ['blogger', 'velog', 'medium'],
  publish_partition: {
    main: [
      ['blogger', {}, false],
      ['velog', {}, true], // needs reconnect → disabled
    ],
    extension_count: 1,
  },
}

let pinia: ReturnType<typeof createPinia>
const origLocation = window.location

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getCampaignForm).mockResolvedValue(FLAT_FORM)
  // Stub navigation so window.location.href assignment doesn't hit jsdom.
  Object.defineProperty(window, 'location', { value: { href: '' }, writable: true, configurable: true })
})
afterEach(() => {
  Object.defineProperty(window, 'location', { value: origLocation, writable: true, configurable: true })
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(BatchCampaignPage, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

function checkboxFor(w: VueWrapper, name: string) {
  return w.findAll('label.platform').find((l) => l.text().includes(name))!.find('input')
}

describe('BatchCampaignPage', () => {
  it('renders the flat platform list when no partition is available', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('label.platform')).toHaveLength(2)
    expect(w.text()).toContain('blogger')
  })

  it('renders partition.main and disables platforms that need reconnect', async () => {
    vi.mocked(api.getCampaignForm).mockResolvedValue(PARTITION_FORM)
    const w = mountPage()
    await flushPromises()
    expect((checkboxFor(w, 'velog').element as HTMLInputElement).disabled).toBe(true)
    expect((checkboxFor(w, 'blogger').element as HTMLInputElement).disabled).toBe(false)
    expect(w.text()).toContain('拓展区')
  })

  it('submits a valid campaign and navigates to the progress page', async () => {
    vi.mocked(api.createCampaign).mockResolvedValue({ campaign_id: 'camp-9' })
    const w = mountPage()
    await flushPromises()

    await w.find('textarea').setValue('{"seed_text": "x"}')
    await checkboxFor(w, 'blogger').setValue(true)
    await w.find('form.campaign-form').trigger('submit')
    await flushPromises()

    expect(api.createCampaign).toHaveBeenCalledWith(
      expect.objectContaining({ seeds: '{"seed_text": "x"}', platforms: ['blogger'], mode: 'draft' }),
    )
    expect(window.location.href).toBe('/campaign/camp-9')
  })

  it('renders inline field errors from a 422 problem+json', async () => {
    vi.mocked(api.createCampaign).mockRejectedValue(
      new ApiError('invalid', 422, {
        errors: [
          { field: 'seeds', message: '至少输入一条 seed（每行一条 JSON）' },
          { field: 'platforms', message: '至少选择一个平台' },
        ],
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('form.campaign-form').trigger('submit')
    await flushPromises()

    const errs = w.findAll('.field-error').map((e) => e.text())
    expect(errs.some((t) => t.includes('至少输入一条 seed'))).toBe(true)
    expect(errs).toContain('至少选择一个平台')
  })
})
