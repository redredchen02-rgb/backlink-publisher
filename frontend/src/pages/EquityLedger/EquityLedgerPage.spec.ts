import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('../../api/equityLedger', () => ({
  fetchEquityLedger: vi.fn(),
  triggerRecheck: vi.fn(),
}))

import * as api from '../../api/equityLedger'
import EquityLedgerPage from './EquityLedgerPage.vue'

const ROWS = [
  {
    target_url: 'https://a.example.com/post-1',
    main_domain: 'a.example.com',
    platform: 'medium',
    status: 'live',
    first_seen: '2026-01-01',
    last_checked: '2026-07-01',
    dofollow: true,
    live: true,
    relevance_score: 0.8,
  },
  {
    target_url: 'https://b.example.com/post-2',
    main_domain: 'b.example.com',
    platform: 'velog',
    status: 'weak',
    first_seen: '2026-01-02',
    last_checked: '2026-07-02',
    dofollow: false,
    live: true,
    relevance_score: 0.5,
  },
]

function mountPage() {
  return mount(EquityLedgerPage)
}

describe('EquityLedgerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Finding 1: DataTable's `items` are post-filter rows. When search/filter
  // excludes every row but the underlying dataset is non-empty, the table
  // must not claim the dataset itself is empty -- that contradicts the stats
  // bar (driven by unfiltered `rows`), which still shows non-zero counts.
  it('shows the filter-specific empty message (not the dataset-empty message) when a search excludes all rows from a non-empty dataset', async () => {
    vi.mocked(api.fetchEquityLedger).mockResolvedValue({ ok: true, rows: ROWS })
    const w = mountPage()
    await flushPromises()

    // Sanity: dataset is non-empty, stats bar shows the real total.
    expect(w.text()).toContain('总计')
    expect(w.text()).toContain('2')

    await w.find('input[type="search"]').setValue('no-such-match-xyz')
    await flushPromises()

    expect(w.text()).toContain('没有符合筛选条件的记录')
    expect(w.text()).not.toContain('暂无权益数据。')
  })

  it('renders a fallback dash when first_seen/last_checked are missing (optional fields)', async () => {
    vi.mocked(api.fetchEquityLedger).mockResolvedValue({
      ok: true,
      rows: [
        {
          target_url: 'https://c.example.com/post-3',
          main_domain: 'c.example.com',
          platform: 'medium',
          status: 'live',
          first_seen: undefined,
          last_checked: undefined,
          dofollow: true,
          live: true,
          relevance_score: 0.3,
        },
      ],
    })
    const w = mountPage()
    await flushPromises()

    const cells = w.findAll('td.col-date')
    expect(cells).toHaveLength(2)
    expect(cells[0].text()).toBe('—')
    expect(cells[1].text()).toBe('—')
  })

  it('shows the dataset-empty message (not the filter message) when the dataset itself is empty', async () => {
    vi.mocked(api.fetchEquityLedger).mockResolvedValue({ ok: true, rows: [] })
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('暂无权益数据。')
    expect(w.text()).not.toContain('没有符合筛选条件的记录')
  })

  // Finding 2: the toolbar/stat-counts section must restore the original
  // `blockState === 'ready'` semantics (hidden during loading and on error),
  // not the migration's `rows.length > 0` gate which stayed visible through
  // errors as long as a prior successful load had populated `rows`.
  it('hides the filter toolbar and stats bar while an error is set (even with stale non-empty rows from a prior load), and shows them again after a successful reload', async () => {
    // First load succeeds so `rows` is populated and stays populated -- the
    // component never clears `rows` on a subsequent failure. This is the
    // exact scenario the migration's `v-if="rows.length > 0"` gate got wrong:
    // it would keep showing the toolbar/stats from stale data even while an
    // error banner is also on screen. `!loading && !error && rows.length > 0`
    // must hide them instead.
    vi.mocked(api.fetchEquityLedger).mockResolvedValueOnce({ ok: true, rows: ROWS })
    const w = mountPage()
    await flushPromises()
    expect(w.find('.equity__filters').exists()).toBe(true)
    expect(w.find('.equity__stats').exists()).toBe(true)

    vi.mocked(api.fetchEquityLedger).mockRejectedValueOnce(new Error('boom'))
    await w.find('button.btn-outline-secondary').trigger('click') // 刷新
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.find('.equity__filters').exists()).toBe(false)
    expect(w.find('.equity__stats').exists()).toBe(false)

    vi.mocked(api.fetchEquityLedger).mockResolvedValueOnce({ ok: true, rows: ROWS })
    await w.find('button.btn-outline-secondary').trigger('click') // 刷新, succeeds again
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.find('.equity__filters').exists()).toBe(true)
    expect(w.find('.equity__stats').exists()).toBe(true)
  })

  // Manual revert check (documented, not automated): reverting the toolbar
  // gate back to `v-if="rows.length > 0"` while `rows` still holds the stale
  // ROWS from the first successful load would make `.equity__filters` /
  // `.equity__stats` reappear even though `error` is set after the failed
  // refresh -- i.e. the middle assertion block above is exactly what catches
  // that regression (confirmed manually by temporarily reverting the gate
  // and observing the assertions fail).
})
