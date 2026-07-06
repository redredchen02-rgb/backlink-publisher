import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/prQueue', () => ({
  fetchPrQueue: vi.fn(),
  updatePrStatus: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  getJson: vi.fn(),
}))

import * as prQueueApi from '../../api/prQueue'
import { getJson } from '../../api/client'
import PrQueuePage from './PrQueuePage.vue'

const ITEM = {
  id: 'pr1',
  status: 'pending',
  relevance_score: 80,
  headline: 'Example opportunity',
  summary: 'Summary text',
  source: 'HARO',
  deadline: '2026-07-10',
}

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(PrQueuePage, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

describe('PrQueuePage', () => {
  it('shows an "unavailable in LITE edition" empty state — not a generic error — when lite_edition is true, and never calls fetchPrQueue', async () => {
    vi.mocked(getJson).mockResolvedValue({ lite_edition: true })
    const w = mountPage()
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.text()).toContain('LITE')
    expect(w.text()).not.toContain('发生未知错误')
    // No doomed retry button — this is the 'empty' state, not 'error'.
    expect(w.findAll('button').some((b) => b.text() === '重试')).toBe(false)
    expect(prQueueApi.fetchPrQueue).not.toHaveBeenCalled()
  })

  it('renders queue items normally when lite_edition is false', async () => {
    vi.mocked(getJson).mockResolvedValue({ lite_edition: false })
    vi.mocked(prQueueApi.fetchPrQueue).mockResolvedValue([ITEM])
    const w = mountPage()
    await flushPromises()

    expect(prQueueApi.fetchPrQueue).toHaveBeenCalled()
    expect(w.find('tbody tr').exists()).toBe(true)
    expect(w.text()).toContain('Example opportunity')
  })

  it('shows the empty state (not LITE-specific copy) when the queue is genuinely empty outside LITE', async () => {
    vi.mocked(getJson).mockResolvedValue({ lite_edition: false })
    vi.mocked(prQueueApi.fetchPrQueue).mockResolvedValue([])
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('暂无 PR 机会')
    expect(w.text()).not.toContain('LITE')
  })

  it('still shows the generic error state (with retry) for a real failure unrelated to LITE gating', async () => {
    vi.mocked(getJson).mockResolvedValue({ lite_edition: false })
    vi.mocked(prQueueApi.fetchPrQueue).mockRejectedValue({ status: 500 })
    const w = mountPage()
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.findAll('button').some((b) => b.text() === '重试')).toBe(true)
  })

  // Code review (correctness/reliability/kieran-typescript, converged): the LITE
  // check must be best-effort, not a hard gate — a transient /app-config failure
  // must not block a healthy /api/pr-queue in full edition.
  it('falls open to the normal fetch when /app-config itself fails, instead of blocking a healthy queue endpoint', async () => {
    vi.mocked(getJson).mockRejectedValue(new Error('network error'))
    vi.mocked(prQueueApi.fetchPrQueue).mockResolvedValue([ITEM])
    const w = mountPage()
    await flushPromises()

    expect(prQueueApi.fetchPrQueue).toHaveBeenCalled()
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.text()).toContain('Example opportunity')
  })

  it('treats a missing lite_edition field as non-LITE (fetches normally)', async () => {
    vi.mocked(getJson).mockResolvedValue({})
    vi.mocked(prQueueApi.fetchPrQueue).mockResolvedValue([])
    const w = mountPage()
    await flushPromises()

    expect(prQueueApi.fetchPrQueue).toHaveBeenCalled()
    expect(w.text()).toContain('暂无 PR 机会')
  })
})
