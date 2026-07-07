import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

vi.mock('../../api/history', () => ({
  listHistory: vi.fn(),
  listHistoryDeletedWindow: vi.fn(),
  deleteHistory: vi.fn(),
  undeleteHistory: vi.fn(),
  bulkDeleteHistory: vi.fn(),
  bulkRecheckHistory: vi.fn(),
  purgeFailedHistory: vi.fn(),
  recheckHistory: vi.fn(),
}))

vi.mock('../../lib/errorCapture', () => ({
  reportManualMutationError: vi.fn().mockResolvedValue(null),
}))

import * as api from '../../api/history'
import * as errorCapture from '../../lib/errorCapture'
import HistoryPage from './HistoryPage.vue'
import Icon from '../../components/Icon.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useRowReportLinksStore } from '../../stores/rowReportLinks'

const PUBLISHED = { id: '7', target_url: 'https://a.com/', status: 'published', platform: 'blogger' }
const FAILED = { id: '8', target_url: 'https://b.com/', status: 'failed', platform: 'medium' }

let pinia: ReturnType<typeof createPinia>
let router: Router

function makeRouter() {
  const r = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/history', name: 'history', component: { template: '<div />' } },
      { path: '/error-reports/:id', name: 'error-report-detail', component: { template: '<div />' } },
    ],
  })
  return r
}

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.listHistoryDeletedWindow).mockResolvedValue({ items: [] })
  vi.mocked(errorCapture.reportManualMutationError).mockResolvedValue(null)
  router = makeRouter()
  await router.push('/history')
})

afterEach(() => {
  vi.useRealTimers()
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(HistoryPage, {
    global: { plugins: [pinia, router, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('HistoryPage', () => {
  it('renders rows after the list fetch resolves', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('tbody tr')).toHaveLength(2)
    expect(w.text()).toContain('https://a.com/')
  })

  it('shows the empty state when there is no history', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('还没有发布记录')
    expect(w.findAll('tbody tr')).toHaveLength(0)
  })

  it('shows the StateBlock error state (role=alert) when the list fetch fails', async () => {
    vi.mocked(api.listHistory).mockRejectedValue({ status: 500 })
    const w = mountPage()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('recheck surfaces the server message as a toast', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.recheckHistory).mockResolvedValue({
      items: [PUBLISHED],
      message: '已重新核实：状态 → published',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    await w.find('.row-actions button:nth-child(1)').trigger('click') // 重核
    await flushPromises()

    expect(api.recheckHistory).toHaveBeenCalledWith('7')
    expect(notify.toasts.some((t) => t.message.includes('已重新核实'))).toBe(true)
  })

  it('renders the box-arrow-up-right Icon for row links with a valid, known icon name', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(api.listHistory).mockResolvedValue({
      items: [{ ...PUBLISHED, article_urls: ['https://c.com/article'] }],
    })
    const w = mountPage()
    await flushPromises()

    const icons = w.findAllComponents(Icon)
    expect(icons.length).toBeGreaterThan(0)
    for (const icon of icons) {
      const svg = icon.find('svg')
      expect(svg.exists()).toBe(true)
      expect(svg.findAll('path').length).toBeGreaterThan(0)
    }
    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('bulk-recheck button stays disabled with no selection', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    const w = mountPage()
    await flushPromises()

    const btn = w.find('.bulk-recheck')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('an action failure surfaces a classifyError toast (no raw server text)', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.deleteHistory).mockRejectedValue({ status: 500, detail: 'stacktrace' })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    await w.find('.row-actions button:nth-child(2)').trigger('click') // 删除
    await flushPromises()

    expect(notify.toasts[0].severity).toBe('error')
    expect(notify.toasts[0].message).toContain('服务器出错了')
    expect(notify.toasts[0].message).not.toContain('stacktrace')
  })

  it('fetches with limit/offset=0 on mount (Plan 2026-07-02-001 U5)', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
    mountPage()
    await flushPromises()
    expect(api.listHistory).toHaveBeenCalledWith({ limit: 50, offset: 0 })
  })

  it('clicking next page fetches the next offset and clears the selection', async () => {
    vi.mocked(api.listHistory)
      .mockResolvedValueOnce({ items: [PUBLISHED], total: 120, limit: 50, offset: 0 })
      .mockResolvedValueOnce({ items: [FAILED], total: 120, limit: 50, offset: 50 })
    const w = mountPage()
    await flushPromises()

    await w.find('tbody tr input[type="checkbox"]').setValue(true) // select the only row
    expect(w.findAll('.data-table__pager button')).toHaveLength(2)

    const [, next] = w.findAll('.data-table__pager button')
    await next.trigger('click')
    await flushPromises()

    expect(api.listHistory).toHaveBeenCalledWith({ limit: 50, offset: 50 })
    // Selection made on page 1 must not survive the page change.
    expect(w.find('.bulk-delete').text()).toContain('(0)')
  })

  // ── W5: undo UX ───────────────────────────────────────────────────────────
  describe('W5 undo UX', () => {
    it('happy path: delete shows "已删除 · 撤销" inline (not removed), then undo restores the row', async () => {
      vi.mocked(api.listHistory)
        .mockResolvedValueOnce({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
        .mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:nth-child(2)').trigger('click') // 删除
      await flushPromises()

      expect(api.deleteHistory).toHaveBeenCalledWith('7')
      // Row stays in the DOM (not removed, D5) with the undo affordance.
      expect(w.findAll('tbody tr')).toHaveLength(1)
      expect(w.text()).toContain('已删除')
      expect(w.text()).toContain('撤销')

      vi.mocked(api.undeleteHistory).mockResolvedValue({ items: [] })
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
      vi.mocked(api.listHistoryDeletedWindow).mockResolvedValue({ items: [] })

      await w.find('.undo-link').trigger('click')
      await flushPromises()

      expect(api.undeleteHistory).toHaveBeenCalledWith('7')
      expect(w.text()).not.toContain('撤销窗口内')
      expect(w.text()).not.toContain('已删除')
    })

    it('edge case: the undo window times out and the row disappears from view', async () => {
      vi.useFakeTimers()
      // Real backend semantics: the live list excludes a soft-deleted row
      // immediately (not just after the client-side undo window elapses) --
      // so the FIRST call sees it, every call after the delete does not.
      vi.mocked(api.listHistory)
        .mockResolvedValueOnce({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
        .mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:nth-child(2)').trigger('click') // 删除
      await flushPromises()
      expect(w.text()).toContain('已删除')

      await vi.advanceTimersByTimeAsync(15_001)
      await flushPromises()

      expect(w.findAll('tbody tr')).toHaveLength(0)
    })

    it('a manual refetch within the undo window keeps the pending row visible (no flicker, D5)', async () => {
      vi.mocked(api.listHistory).mockResolvedValueOnce({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      const w = mountPage()
      await flushPromises()

      // After delete, subsequent refetches of the LIVE list no longer
      // contain the row (server excludes soft-deleted rows), and the
      // deleted-window query now reports it as server-truth-pending.
      vi.mocked(api.listHistory).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
      vi.mocked(api.listHistoryDeletedWindow).mockResolvedValue({
        items: [{ ...PUBLISHED, deleted_at: new Date().toISOString() }],
      })

      await w.find('.row-actions button:nth-child(2)').trigger('click')
      await flushPromises()
      expect(w.text()).toContain('已删除')

      // A further refetch of the live list (e.g. a background query
      // invalidation) must not make the row flicker away -- `deletedItems`
      // (server truth) still backs it via `pendingIds`/`rowSnapshots`.
      await w.vm.$nextTick()
      await flushPromises()
      expect(w.text()).toContain('已删除')
    })

    it('remount mid-undo-window: the server-discovered pending row resumes with its remaining time, not a fresh 15s', async () => {
      vi.useFakeTimers()
      const deletedAt = new Date(Date.now() - 10_000).toISOString() // 10s elapsed, 5s left
      vi.mocked(api.listHistory).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
      vi.mocked(api.listHistoryDeletedWindow).mockResolvedValue({
        items: [{ ...PUBLISHED, deleted_at: deletedAt }],
      })
      const w = mountPage()
      await flushPromises()
      expect(w.text()).toContain('已删除')

      await vi.advanceTimersByTimeAsync(4_000)
      await flushPromises()
      expect(w.text()).toContain('已删除') // still within its remaining ~5s

      await vi.advanceTimersByTimeAsync(2_000)
      await flushPromises()
      expect(w.findAll('tbody tr')).toHaveLength(0) // finalized after remaining time elapses
    })

    it('an aged-out undo (404) is reported via W13 and finalizes the row immediately, not treated as a silent expected outcome', async () => {
      vi.mocked(api.listHistory)
        .mockResolvedValueOnce({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
        .mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:nth-child(2)').trigger('click') // -> undo window
      await flushPromises()

      vi.mocked(api.undeleteHistory).mockRejectedValue({ status: 404, error_class: 'not_found' })
      await w.find('.undo-link').trigger('click')
      await flushPromises()

      expect(errorCapture.reportManualMutationError).toHaveBeenCalledWith(
        { status: 404, error_class: 'not_found' },
        'history.undelete',
      )
      expect(w.findAll('tbody tr')).toHaveLength(0)
    })
  })

  // ── D6: rowBusy / bulkBusy mutual exclusion ────────────────────────────────
  describe('D6 busy mutual exclusion', () => {
    it('a single-row op only disables that row, not the pager/checkboxes/other rows (D6)', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED], total: 120, limit: 50, offset: 0 })
      let resolveDelete!: (v: { items: never[] }) => void
      vi.mocked(api.deleteHistory).mockReturnValue(new Promise((resolve) => { resolveDelete = resolve }))
      const w = mountPage()
      await flushPromises()

      const rows = w.findAll('tbody tr')
      await rows[0].find('.row-actions button:nth-child(2)').trigger('click') // delete row A
      await flushPromises()

      // Row A's own delete button is disabled while in flight...
      expect((rows[0].find('.row-actions button:nth-child(2)').element as HTMLButtonElement).disabled).toBe(true)
      // ...but row B's buttons, the pager, and checkboxes are NOT (D6: a
      // single-row op does not lock the whole table).
      expect((rows[1].find('.row-actions button:nth-child(2)').element as HTMLButtonElement).disabled).toBe(false)
      expect((w.find('tbody tr input[type="checkbox"]').element as HTMLInputElement).disabled).toBe(false)
      const [, next] = w.findAll('.data-table__pager button')
      expect((next.element as HTMLButtonElement).disabled).toBe(false)

      resolveDelete({ items: [] })
      await flushPromises()
    })

    it('a bulk op locks the whole table (checkboxes + pager) via DataTable\'s disabled prop', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED], total: 120, limit: 50, offset: 0 })
      let resolveBulk!: (v: { items: never[] }) => void
      vi.mocked(api.bulkDeleteHistory).mockReturnValue(new Promise((resolve) => { resolveBulk = resolve }))
      const w = mountPage()
      await flushPromises()

      await w.find('tbody tr input[type="checkbox"]').setValue(true)
      await w.find('.bulk-delete').trigger('click')
      await flushPromises()

      expect((w.find('tbody tr input[type="checkbox"]').element as HTMLInputElement).disabled).toBe(true)
      const [, next] = w.findAll('.data-table__pager button')
      expect((next.element as HTMLButtonElement).disabled).toBe(true)

      resolveBulk({ items: [] })
      await flushPromises()
      expect((next.element as HTMLButtonElement).disabled).toBe(false)
    })

    it('rapid repeated clicks on the same delete button dispatch exactly one API call', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
      let resolveDelete!: (v: { items: never[] }) => void
      vi.mocked(api.deleteHistory).mockReturnValue(new Promise((resolve) => { resolveDelete = resolve }))
      const w = mountPage()
      await flushPromises()

      const btn = w.find('.row-actions button:nth-child(2)')
      await btn.trigger('click')
      await btn.trigger('click')
      await btn.trigger('click')
      await flushPromises()

      expect(api.deleteHistory).toHaveBeenCalledTimes(1)
      resolveDelete({ items: [] })
      await flushPromises()
    })
  })

  describe('bulk actions', () => {
    it('bulk-deletes the selected rows', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      vi.mocked(api.bulkDeleteHistory).mockResolvedValue({ items: [], message: '已删除 1 条历史记录' })
      const w = mountPage()
      await flushPromises()

      await w.find('tbody tr input[type="checkbox"]').setValue(true) // select first row
      await w.find('.bulk-delete').trigger('click')
      await flushPromises()

      expect(api.bulkDeleteHistory).toHaveBeenCalledWith(['7'])
    })

    it('bulk-rechecks the selected rows (U3)', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      vi.mocked(api.bulkRecheckHistory).mockResolvedValue({
        items: [PUBLISHED, FAILED],
        message: '已核实 1 条：1 升为已发布，0 标为失败，0 跳过',
      })
      const w = mountPage()
      const notify = useNotificationsStore()
      await flushPromises()

      await w.find('tbody tr input[type="checkbox"]').setValue(true) // select first row
      await w.find('.bulk-recheck').trigger('click')
      await flushPromises()

      expect(api.bulkRecheckHistory).toHaveBeenCalledWith(['7'])
      expect(notify.toasts.some((t) => t.message.includes('已核实'))).toBe(true)
    })

    it('a successful bulk action only deselects the ids it actually submitted (code review)', async () => {
      vi.mocked(api.listHistory)
        .mockResolvedValueOnce({ items: [PUBLISHED, FAILED] })
        .mockResolvedValueOnce({ items: [FAILED] })
      let resolveDelete!: (v: { items: typeof PUBLISHED[]; message?: string }) => void
      const pending = new Promise<{ items: typeof PUBLISHED[]; message?: string }>((res) => {
        resolveDelete = res
      })
      vi.mocked(api.bulkDeleteHistory).mockReturnValue(pending)
      const w = mountPage()
      await flushPromises()

      const checkboxes = w.findAll('tbody tr input[type="checkbox"]')
      await checkboxes[0].setValue(true) // select PUBLISHED (id 7)
      await w.find('.bulk-delete').trigger('click') // in-flight, still holding [7]

      await checkboxes[1].setValue(true) // reselect FAILED (id 8) mid-flight

      resolveDelete({ items: [FAILED] }) // id 7 deleted server-side
      await flushPromises()

      expect(api.bulkDeleteHistory).toHaveBeenCalledWith(['7'])
      const remainingCheckbox = w.find('tbody tr input[type="checkbox"]')
      expect((remainingCheckbox.element as HTMLInputElement).checked).toBe(true)
    })

    it('deleting the last row on the last page clamps back to the previous page', async () => {
      vi.mocked(api.listHistory)
        .mockResolvedValueOnce({ items: [PUBLISHED], total: 101, limit: 50, offset: 0 })
        .mockResolvedValueOnce({ items: [FAILED], total: 101, limit: 50, offset: 100 })
      const w = mountPage()
      await flushPromises()

      const [, next] = w.findAll('.data-table__pager button')
      await next.trigger('click') // -> offset 50
      await flushPromises()
      const [, next2] = w.findAll('.data-table__pager button')
      await next2.trigger('click') // -> offset 100
      await flushPromises()

      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      vi.mocked(api.listHistory).mockResolvedValueOnce({
        items: [], total: 100, limit: 50, offset: 100,
      }).mockResolvedValueOnce({
        items: [PUBLISHED], total: 100, limit: 50, offset: 50,
      })

      await w.find('.row-actions button:nth-child(2)').trigger('click') // 删除
      await flushPromises()

      const calls = vi.mocked(api.listHistory).mock.calls
      expect(calls[calls.length - 1]).toEqual([{ limit: 50, offset: 50 }])
    })
  })

  // ── W13: mutation error reporting ──────────────────────────────────────────
  describe('W13 mutation error reporting', () => {
    it('a delete failure is reported via reportManualMutationError (D8)', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      const err = { status: 500 }
      vi.mocked(api.deleteHistory).mockRejectedValue(err)
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:nth-child(2)').trigger('click')
      await flushPromises()

      expect(errorCapture.reportManualMutationError).toHaveBeenCalledWith(err, 'history.delete')
    })

    it('once a report id resolves, the row surfaces a "查看报告" deep-link', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.recheckHistory).mockRejectedValue({ status: 500 })
      vi.mocked(errorCapture.reportManualMutationError).mockResolvedValue('report-123')
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:nth-child(1)').trigger('click') // 重核 (fails)
      await flushPromises()

      const link = w.find('a.row-report-link')
      expect(link.exists()).toBe(true)
      expect(link.attributes('href')).toContain('/error-reports/report-123')
    })

    it('bulk-delete failure reports once for the whole batch and links every id (one HTTP call covers all)', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      const err = { status: 500 }
      vi.mocked(api.bulkDeleteHistory).mockRejectedValue(err)
      vi.mocked(errorCapture.reportManualMutationError).mockResolvedValue('report-999')
      const w = mountPage()
      await flushPromises()

      const checkboxes = w.findAll('tbody tr input[type="checkbox"]')
      await checkboxes[0].setValue(true)
      await checkboxes[1].setValue(true)
      await w.find('.bulk-delete').trigger('click')
      await flushPromises()

      expect(errorCapture.reportManualMutationError).toHaveBeenCalledWith(err, 'history.bulk-delete')
      const rowReportLinks = useRowReportLinksStore()
      expect(rowReportLinks.reportIdForRow('7')).toBe('report-999')
      expect(rowReportLinks.reportIdForRow('8')).toBe('report-999')
    })
  })

  // ── W10: cross-page deep-link ──────────────────────────────────────────────
  describe('W10 cross-page deep-link', () => {
    it('highlights the row named by ?highlight= and strips the query param', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      await router.push('/history?highlight=8')
      const w = mountPage()
      await flushPromises()
      await flushPromises()

      expect(w.text()).toContain('已定位到目标记录')
      expect(router.currentRoute.value.query.highlight).toBeUndefined()
      const row = w.find('tr[data-id="8"]')
      expect(row.classes()).toContain('row--highlight')
    })

    it('shows a dismissible "not in list" banner when the highlighted row is missing', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      await router.push('/history?highlight=does-not-exist')
      const w = mountPage()
      await flushPromises()
      await flushPromises()

      expect(w.text()).toContain('该项目已不在列表中')
      await w.find('.highlight-missing__dismiss').trigger('click')
      await flushPromises()
      expect(w.find('.highlight-missing').exists()).toBe(false)
    })
  })
})
