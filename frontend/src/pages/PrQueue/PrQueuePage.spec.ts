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
import type { PrItem } from '../../api/prQueue'
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

/** A promise whose resolution the test controls, to force a specific interleaving. */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
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

  // B4 (backlog, found in B2's code review): load() had no request-generation
  // guard. markStatus() calls load() internally after updating a row, and two
  // DIFFERENT rows' markStatus() calls are independently triggerable (the
  // updating.has(id) guard only blocks re-clicking the SAME row) — so two
  // overlapping load() calls could resolve out of order, with the earlier
  // (now-stale) one overwriting the later one's fresher result.
  it('a load() superseded by a newer one never touches the network or shared state', async () => {
    vi.mocked(getJson).mockResolvedValue({ lite_edition: false })
    const itemA = { ...ITEM, id: 'pr1', headline: 'Item A' }
    const itemB = { ...ITEM, id: 'pr2', headline: 'Item B' }

    vi.mocked(prQueueApi.fetchPrQueue).mockResolvedValueOnce([itemA, itemB])
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('Item A')
    expect(w.text()).toContain('Item B')

    const pending = deferred<PrItem[]>()
    vi.mocked(prQueueApi.fetchPrQueue).mockReturnValueOnce(pending.promise)
    vi.mocked(prQueueApi.updatePrStatus).mockResolvedValue({ ...itemA, status: 'won' })

    // Grab both buttons *before* clicking either — the first click's load()
    // sets loading.value = true, which swaps StateBlock to its loading variant
    // and hides the table (and row B's button) until that load() completes.
    // Firing both clicks before awaiting either lets both markStatus() calls
    // start before either has re-rendered, reproducing two overlapping load()s.
    const wonButtonForA = w.findAll('tr[data-id="pr1"] button').find((b) => b.text() === '✓')!
    const skipButtonForB = w.findAll('tr[data-id="pr2"] button').find((b) => b.text() === '✕')!
    wonButtonForA.trigger('click') // markStatus(A) -> load() -- started first, now stale
    skipButtonForB.trigger('click') // markStatus(B) -> load() -- started second, now current
    await flushPromises()

    // The earlier (A) load() must recognize it's stale as soon as it can — at
    // its first checkpoint after the /app-config check — and never even call
    // fetchPrQueue(). Only the later (B) load() reaches the network, so the
    // total call count is the initial mount's call plus exactly one more —
    // not two more (which would mean both A's and B's load() both fired).
    expect(prQueueApi.fetchPrQueue).toHaveBeenCalledTimes(2)

    pending.resolve([{ ...itemB, headline: 'Fresh result from the current load' }])
    await flushPromises()

    expect(w.text()).toContain('Fresh result from the current load')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })
})
