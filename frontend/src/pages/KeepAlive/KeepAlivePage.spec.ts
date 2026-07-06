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

describe('KeepAlivePage — empty-state fix (false-ready regression)', () => {
  it('renders the empty-text message, not the (empty) scorecard, when summary.is_empty is true', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(EMPTY_SUMMARY)
    const w = mount(KeepAlivePage)
    await flushPromises()

    expect(w.text()).toContain('暂无数据')
    // The scorecard is inside StateBlock's default slot, which only renders
    // in the 'ready' branch — it must NOT render while state is 'empty'.
    expect(w.find('.ka__scorecard').exists()).toBe(false)
  })

  it('renders the scorecard (not the empty text) when data is present', async () => {
    vi.mocked(api.fetchSummary).mockResolvedValue(READY_SUMMARY)
    const w = mount(KeepAlivePage)
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

    const w = mount(KeepAlivePage)
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

    const w = mount(KeepAlivePage)
    await flushPromises()
    expect(w.find('.ka__cycle-error').exists()).toBe(true)

    vi.mocked(api.fetchCycleStatus).mockResolvedValue({ running: true, status: 'running' })
    await w.find('.ka__cycle-error button').trigger('click')
    await flushPromises()

    expect(w.find('.ka__cycle-error').exists()).toBe(false)
    expect(w.find('.ka__cycle').exists()).toBe(true)
  })
})

describe('KeepAlivePage — republish state machine through the shared ConfirmDialog (W3 acceptance)', () => {
  // The S4 confirm step now renders via components/ConfirmDialog.vue instead of
  // the bespoke .ka__confirm-overlay. Flow semantics must be unchanged:
  // selecting → confirming (token fetched) → publishing → result.
  // NOTE: the page builds gap keys as `${target_url}:${platform}` and later
  // re-splits on ':' — a URL with a scheme ('https://…') would split wrong.
  // That is pre-existing page behavior outside W3's scope; the fixture uses a
  // colon-free target_url so these tests assert the state-machine semantics.
  const GAPPED_SUMMARY = {
    ...READY_SUMMARY,
    gaps: [
      {
        target_url: 'example.com/a',
        platform: 'blogger',
        publish_ts: '2026-06-01',
        stripped_ts: '2026-07-01',
      },
    ],
  }

  async function mountWithSelectedGap() {
    vi.mocked(api.fetchSummary).mockResolvedValue(GAPPED_SUMMARY)
    const w = mount(KeepAlivePage)
    await flushPromises()
    // S3: select the gap
    await w.find('input[type="checkbox"][id="example.com/a:blogger"]').setValue(true)
    return w
  }

  it('walks idle→selecting→confirming→publishing→result with unchanged semantics', async () => {
    vi.mocked(api.getRepublishToken).mockResolvedValue({ ok: true, token: 'tok-1' } as never)
    vi.mocked(api.executeRepublish).mockResolvedValue({ ok: true, job_id: 'job-9' } as never)
    vi.mocked(api.pollRepublish).mockResolvedValue({ status: 'completed' } as never)

    const w = await mountWithSelectedGap()
    expect(w.find('[role="dialog"]').exists()).toBe(false)

    // S3 → S4: 重新发布 fetches the token and opens the confirm dialog
    const openBtn = w.findAll('button').find((b) => b.text().startsWith('重新发布 ('))!
    await openBtn.trigger('click')
    await flushPromises()
    expect(api.getRepublishToken).toHaveBeenCalled()

    const dialog = w.find('[role="dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.text()).toContain('不可撤销')
    expect(dialog.text()).toContain('example.com/a')
    // D3: irreversible-op confirm label carries the affected count
    const confirmBtn = w.findAll('button').find((b) => b.text().includes('确认重新发布'))!
    expect(confirmBtn.text()).toContain('1 条')

    // S4 → S5: confirm executes the republish with the token and closes the dialog
    await confirmBtn.trigger('click')
    await flushPromises()
    expect(api.executeRepublish).toHaveBeenCalledWith('tok-1', [
      JSON.stringify({ target_url: 'example.com/a', platform: 'blogger' }),
    ])
    expect(w.find('[role="dialog"]').exists()).toBe(false)

    // S5 → S6/S7: poll completed → result banner
    expect(w.text()).toContain('重新发布已完成')
  })

  it('cancelling the confirm dialog returns to gap selection without publishing', async () => {
    vi.mocked(api.getRepublishToken).mockResolvedValue({ ok: true, token: 'tok-1' } as never)

    const w = await mountWithSelectedGap()
    const openBtn = w.findAll('button').find((b) => b.text().startsWith('重新发布 ('))!
    await openBtn.trigger('click')
    await flushPromises()
    expect(w.find('[role="dialog"]').exists()).toBe(true)

    await w.findAll('button').find((b) => b.text() === '取消')!.trigger('click')
    await flushPromises()

    expect(w.find('[role="dialog"]').exists()).toBe(false)
    expect(api.executeRepublish).not.toHaveBeenCalled()
    // Back on the selection UI, selection intact
    expect(w.findAll('button').some((b) => b.text().startsWith('重新发布 (1)'))).toBe(true)
  })

  it('a failed executeRepublish surfaces via flashMessage and returns to idle (pre-W3 semantics)', async () => {
    vi.mocked(api.getRepublishToken).mockResolvedValue({ ok: true, token: 'tok-1' } as never)
    vi.mocked(api.executeRepublish).mockResolvedValue({ ok: false, message: '发布通道不可用' } as never)

    const w = await mountWithSelectedGap()
    await w.findAll('button').find((b) => b.text().startsWith('重新发布 ('))!.trigger('click')
    await flushPromises()
    await w.findAll('button').find((b) => b.text().includes('确认重新发布'))!.trigger('click')
    await flushPromises()

    // Error goes to the page flash message — NOT kept inside the dialog
    expect(w.find('[role="dialog"]').exists()).toBe(false)
    expect(w.text()).toContain('发布通道不可用')
  })
})

describe('KeepAlivePage — no false-ready on a failed summary fetch (no-fake-ok:true guard)', () => {
  it('a rejected summary fetch renders the error state, never the scorecard/ready UI', async () => {
    vi.mocked(api.fetchSummary).mockRejectedValue({ status: 500 })

    const w = mount(KeepAlivePage)
    await flushPromises()

    expect(w.find('.state--error').exists()).toBe(true)
    expect(w.find('.ka__scorecard').exists()).toBe(false)
  })
})
