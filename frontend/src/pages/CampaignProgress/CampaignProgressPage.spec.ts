import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { campaignId: 'c1' } }),
  useRouter: () => ({ push }),
}))

vi.mock('../../api/campaign', () => ({
  fetchCampaignStatus: vi.fn(),
}))

import * as api from '../../api/campaign'
import CampaignProgressPage from './CampaignProgressPage.vue'

const RUNNING = {
  campaign_id: 'c1', progress_pct: 0.4, running: true, done: false, seeds: [],
}
const DONE = {
  campaign_id: 'c1', progress_pct: 1, running: false, done: true, seeds: [],
}

let queryClient: QueryClient

beforeEach(() => {
  vi.clearAllMocks()
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
})

function mountPage() {
  return mount(CampaignProgressPage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

describe('CampaignProgressPage', () => {
  it('renders progress once the status fetch resolves', async () => {
    vi.mocked(api.fetchCampaignStatus).mockResolvedValue(RUNNING)
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('40%')
    expect(w.text()).toContain('进行中')
  })

  it('shows the error state when the fetch fails', async () => {
    vi.mocked(api.fetchCampaignStatus).mockRejectedValue(new Error('未找到该任务'))
    const w = mountPage()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('goBack navigates to /batch-campaign', async () => {
    vi.mocked(api.fetchCampaignStatus).mockResolvedValue(RUNNING)
    const w = mountPage()
    await flushPromises()
    await w.find('button').trigger('click')
    expect(push).toHaveBeenCalledWith('/batch-campaign')
  })
})

describe('CampaignProgressPage polling (Plan 2026-07-02-001 U5)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('polls again after intervalMs while running', async () => {
    vi.mocked(api.fetchCampaignStatus).mockResolvedValue(RUNNING)
    mountPage()
    await vi.advanceTimersByTimeAsync(0)
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000)
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(2)
  })

  it('stops polling once the campaign reports done', async () => {
    vi.mocked(api.fetchCampaignStatus).mockResolvedValue(DONE)
    mountPage()
    await vi.advanceTimersByTimeAsync(0)
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(10_000)
    // No further calls -- the very first result was already terminal.
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(1)
  })

  it('a failed poll tick does not silently hang -- backs off instead of retrying at the base rate', async () => {
    vi.mocked(api.fetchCampaignStatus)
      .mockResolvedValueOnce(RUNNING)
      .mockRejectedValueOnce(new Error('network blip'))
      .mockResolvedValue(RUNNING)
    mountPage()

    await vi.advanceTimersByTimeAsync(0) // tick 1: success
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000) // tick 2: fails
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(2)

    // Base interval (2000ms) must not be enough after a failure -- backoff
    // doubled it to 4000ms.
    await vi.advanceTimersByTimeAsync(2000)
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(2000) // now at 4000ms since tick 2
    expect(api.fetchCampaignStatus).toHaveBeenCalledTimes(3)
  })
})
