// KeepAlivePage — Sprint B3 (R3) regression coverage.
//
// Two bugs fixed here:
//  1. False-ready: the internal `pageState` state machine included 'empty',
//     but the value passed to StateBlock collapsed everything non-loading/
//     non-error to 'ready', so a truly-empty result rendered the (empty)
//     scorecard table instead of the empty-text message.
//  2. Blanket-error-on-partial-failure: the initial load fetched summary AND
//     cycle-status inside one try/catch, so a cycle-status failure blanked
//     the scorecard that had already loaded successfully.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/keepAlive', () => ({
  fetchSummary: vi.fn(),
  fetchCycleStatus: vi.fn(),
  startRecheck: vi.fn(),
  pollRecheck: vi.fn(),
  cancelRecheck: vi.fn(),
  getRepublishToken: vi.fn(),
  executeRepublish: vi.fn(),
  pollRepublish: vi.fn(),
  resetExhausted: vi.fn(),
}))

import * as api from '../../api/keepAlive'
import KeepAlivePage from './KeepAlivePage.vue'

const EMPTY_SUMMARY = {
  targets: [],
  gaps: [],
  stale: false,
  stale_days: 0,
  last_recheck: null,
  is_empty: true,
  alive_count: 0,
  stripped_count: 0,
  unknown_count: 0,
  live_excluded: 0,
  gap_channel_exhausted: 0,
}

const READY_SUMMARY = {
  targets: [
    {
      target_url: 'https://example.com/a',
      live_dofollow: 3,
      stripped: 1,
      decayed: 0,
      check_failed: 0,
      strip_rate: 0.25,
      trend: 'flat',
      platforms: 'blogger',
      last_verified: '2026-07-01',
      needs_attention: false,
    },
  ],
  gaps: [],
  stale: false,
  stale_days: 0,
  last_recheck: '2026-07-01T00:00:00Z',
  is_empty: false,
  alive_count: 3,
  stripped_count: 1,
  unknown_count: 0,
  live_excluded: 0,
  gap_channel_exhausted: 0,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchCycleStatus).mockResolvedValue({ running: false, status: 'idle' })
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return mount(KeepAlivePage, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
}

describe('KeepAlivePage — empty-state fix (false-ready regression)', () => {
  it('renders the empty-text message, not the (empty) scorecard, when summary.is_empty is true', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(EMPTY_SUMMARY)
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('暂无数据')
    // The scorecard is inside StateBlock's default slot, which only renders
    // in the 'ready' branch — it must NOT render while state is 'empty'.
    expect(w.find('.ka__scorecard').exists()).toBe(false)
  })

  it('renders the scorecard (not the empty text) when data is present', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    const w = mountPage()
    await flushPromises()

    expect(w.find('.ka__scorecard').exists()).toBe(true)
    expect(w.text()).not.toContain('暂无数据。先发布一些文章')
    expect(w.text()).toContain('https://example.com/a')
  })
})

describe('KeepAlivePage — partial-failure isolation (R3 action 6/7/8)', () => {
  it('shows the scorecard from a succeeded summary fetch AND a persistent cycle-status error, without blanking the page', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    vi.mocked(api.fetchCycleStatus).mockRejectedValue(new Error('cycle-status 500'))

    const w = mountPage()
    await flushPromises()

    // Sibling data (scorecard) that loaded fine must stay visible...
    expect(w.find('.ka__scorecard').exists()).toBe(true)
    expect(w.text()).toContain('https://example.com/a')
    // ...while the failed section gets its own persistent, non-generic indicator.
    expect(w.find('.ka__cycle-error').exists()).toBe(true)
    expect(w.text()).toContain('自动保活周期状态加载失败')
    // The page must NOT collapse into the generic full-page StateBlock error view.
    expect(w.find('.state--error').exists()).toBe(false)
  })

  it('retrying the cycle-status panel clears the error indicator on success', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    vi.mocked(api.fetchCycleStatus).mockRejectedValueOnce(new Error('cycle-status 500'))

    const w = mountPage()
    await flushPromises()
    expect(w.find('.ka__cycle-error').exists()).toBe(true)

    vi.mocked(api.fetchCycleStatus).mockResolvedValue({ running: true, status: 'running' })
    await w.find('.ka__cycle-error button').trigger('click')
    await flushPromises()

    expect(w.find('.ka__cycle-error').exists()).toBe(false)
    expect(w.find('.ka__cycle').exists()).toBe(true)
  })
})

describe('KeepAlivePage — no false-ready on a failed summary fetch (no-fake-ok:true guard)', () => {
  it('a rejected summary fetch renders the error state, never the scorecard/ready UI', async () => {
    vi.mocked(api.fetchSummary).mockRejectedValue({ status: 500 })

    const w = mountPage()
    await flushPromises()

    expect(w.find('.state--error').exists()).toBe(true)
    expect(w.find('.ka__scorecard').exists()).toBe(false)
  })
})

describe('KeepAlivePage — recheck polling (Plan 2026-07-02-001 U5)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('starting a recheck polls, then returns to idle and reloads the scorecard once completed', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    vi.mocked(api.startRecheck).mockResolvedValue({ status: 'started', job_id: 'job-1' })
    vi.mocked(api.pollRecheck)
      .mockResolvedValueOnce({ status: 'running', progress: 1, total: 3 })
      .mockResolvedValueOnce({ status: 'completed', progress: 3, total: 3 })

    const w = mountPage()
    await flushPromises()

    await w.find('.btn-primary').trigger('click') // 巡检
    await flushPromises()
    expect(api.pollRecheck).toHaveBeenCalledTimes(1)
    expect(w.find('.ka__progress').exists()).toBe(true)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(api.pollRecheck).toHaveBeenCalledTimes(2)
    // Terminal status must return to idle and reload the scorecard (2nd fetchSummary call).
    expect(w.find('.ka__progress').exists()).toBe(false)
    expect(api.fetchSummary).toHaveBeenCalledTimes(2)
  })

  it('a failed poll tick backs off instead of retrying at the base 2s rate', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    vi.mocked(api.startRecheck).mockResolvedValue({ status: 'started', job_id: 'job-1' })
    vi.mocked(api.pollRecheck)
      .mockResolvedValueOnce({ status: 'running', progress: 1, total: 3 })
      .mockRejectedValueOnce(new Error('network blip'))
      .mockResolvedValue({ status: 'running', progress: 2, total: 3 })

    const w = mountPage()
    await flushPromises()
    await w.find('.btn-primary').trigger('click')
    await flushPromises()
    expect(api.pollRecheck).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(2000) // tick 2: fails
    await flushPromises()
    expect(api.pollRecheck).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(2000) // base interval alone must not be enough
    await flushPromises()
    expect(api.pollRecheck).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(2000) // now at 4000ms since the failure
    await flushPromises()
    expect(api.pollRecheck).toHaveBeenCalledTimes(3)
  })

  it('starting a new recheck after a completed one does not show the previous job\'s stale progress (code review finding)', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    vi.mocked(api.startRecheck)
      .mockResolvedValueOnce({ status: 'started', job_id: 'job-1' })
      .mockResolvedValueOnce({ status: 'started', job_id: 'job-2' })
    vi.mocked(api.pollRecheck)
      .mockResolvedValueOnce({ status: 'completed', progress: 3, total: 3 })
      .mockResolvedValueOnce({ status: 'running', progress: 0, total: 5 })

    const w = mountPage()
    await flushPromises()

    await w.find('.btn-primary').trigger('click') // job-1
    await flushPromises() // job-1 completes immediately, back to idle

    await w.find('.btn-primary').trigger('click') // job-2
    // Before job-2's own poll result arrives, the panel must show a fresh
    // 0/0, not job-1's stale "3/3" left over from keepPreviousData.
    expect(w.text()).toContain('0/0')
    expect(w.text()).not.toContain('3/3')
    await flushPromises()
  })
})

describe('KeepAlivePage — republish polling (Plan 2026-07-02-001 U5)', () => {
  const WITH_GAP = {
    ...READY_SUMMARY,
    gaps: [{
      target_url: 'https://example.com/b', platform: 'medium',
      publish_ts: '2026-06-01', stripped_ts: '2026-06-30',
    }],
  }

  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('confirming republish polls, then shows the result state once completed', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(WITH_GAP)
    // getRepublishToken's declared RepublishResult type omits `token`, but the
    // real response (and the component's own call-site cast) includes it.
    vi.mocked(api.getRepublishToken).mockResolvedValue(
      { ok: true, token: 'tok-1' } as Awaited<ReturnType<typeof api.getRepublishToken>> & { token: string },
    )
    vi.mocked(api.executeRepublish).mockResolvedValue({ ok: true, job_id: 'job-2' })
    vi.mocked(api.pollRepublish)
      .mockResolvedValueOnce({ status: 'running', message: '发布中' })
      .mockResolvedValueOnce({ status: 'completed', message: '完成' })

    const w = mountPage()
    await flushPromises()

    await w.find('#selectAll').setValue(true)
    await w.find('.btn-outline-primary').trigger('click') // 重新发布 (N) -> startConfirm
    await flushPromises()

    await w.find('.btn-danger').trigger('click') // 确认重新发布 -> doRepublish
    await flushPromises()
    expect(api.pollRepublish).toHaveBeenCalledTimes(1)
    expect(w.find('.ka__progress').exists()).toBe(true)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(api.pollRepublish).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('重新发布已完成')
  })
})
