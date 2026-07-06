import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createRouter, createMemoryHistory, type Router } from 'vue-router'

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

import * as api from '../../api/history'
import HistoryPage from './HistoryPage.vue'
import Icon from '../../components/Icon.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useRowReportLinksStore } from '../../stores/rowReportLinks'
import { ApiError } from '../../api/client'
import { _resetCaptureStateForTest } from '../../lib/errorCapture'
import { _resetCsrfForTest } from '../../api/client'

// jsdom doesn't implement scrollIntoView — W10's highlight-on-return feature
// calls it, so stub it globally for this file (mirrors the plan's a11y
// scenario: we only assert it was invoked with the expected behavior, not
// any real scroll geometry).
Element.prototype.scrollIntoView = vi.fn()

const ROUTES = [
  { path: '/', name: 'root', component: { template: '<div />' } },
  { path: '/history', name: 'history', component: { template: '<div />' } },
  { path: '/error-reports/:id', name: 'error-report-detail', component: { template: '<div />' } },
]

function makeRouter(initialPath = '/history'): Router {
  const router = createRouter({ history: createMemoryHistory(), routes: ROUTES })
  void router.push(initialPath)
  return router
}

const PUBLISHED = { id: '7', target_url: 'https://a.com/', status: 'published', platform: 'blogger' }
const FAILED = { id: '8', target_url: 'https://b.com/', status: 'failed', platform: 'medium' }
const OTHER = { id: '9', target_url: 'https://c.com/', status: 'published', platform: 'blogger' }

let pinia: ReturnType<typeof createPinia>

// listHistoryDeletedWindow defaults to an empty window unless a test overrides it.
function mockEmptyDeletedWindow() {
  vi.mocked(api.listHistoryDeletedWindow).mockResolvedValue({ items: [] })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  mockEmptyDeletedWindow()
})

afterEach(() => {
  vi.useRealTimers()
  document.body.innerHTML = ''
})

let lastQueryClient: QueryClient
let lastRouter: Router

function mountPage(initialPath = '/history') {
  // Share the SAME pinia between the component and the test's store lookups.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  lastQueryClient = queryClient
  const router = makeRouter(initialPath)
  lastRouter = router
  return mount(HistoryPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
  })
}

/** Like `mountPage`, but awaits the router's initial navigation FIRST — the
 *  W10 highlight-on-return tests need `route.query.highlight` to already be
 *  resolved at HistoryPage's setup() time (a router push kicked off but not
 *  yet settled when a component mounts is a real vue-router timing gap: its
 *  `useRoute()` result only reflects the target location once navigation
 *  resolves, and no further reactive change is guaranteed to reach a watcher
 *  registered afterward — confirmed with a minimal repro during this unit's
 *  implementation). The other ~25 tests in this file don't depend on the
 *  initial route/query, so they keep using the synchronous `mountPage`. */
async function mountPageAt(initialPath: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  lastQueryClient = queryClient
  const router = createRouter({ history: createMemoryHistory(), routes: ROUTES })
  await router.push(initialPath)
  lastRouter = router
  // attachTo: document.body — the highlight feature's scroll-to-row step
  // uses `document.querySelector`, which finds nothing in @vue/test-utils'
  // default detached render tree.
  return mount(HistoryPage, {
    attachTo: document.body,
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
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

    await w.find('.row-actions button:first-child').trigger('click') // 重核
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

    await w.find('.row-actions button:last-child').trigger('click')
    await flushPromises()

    expect(notify.toasts[0].severity).toBe('error')
    expect(notify.toasts[0].message).toContain('服务器出错了')
    expect(notify.toasts[0].message).not.toContain('stacktrace')
  })

  // ── W5: undo UX ───────────────────────────────────────────────────────────

  it('happy path: delete 1 row shows "deleted · undo" inline, then undo restores it', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()

    expect(api.deleteHistory).not.toHaveBeenCalled()
    await w.find('.row-actions button:last-child').trigger('click') // 删除
    await flushPromises()

    expect(api.deleteHistory).toHaveBeenCalledWith('7')
    // Row stays in the DOM (not removed-then-bounced-back, D5) with undo affordance.
    expect(w.findAll('tbody tr')).toHaveLength(1)
    expect(w.text()).toContain('已删除')
    expect(w.text()).toContain('撤销')
    expect(w.text()).toContain('https://a.com/') // original row content still visible

    vi.mocked(api.undeleteHistory).mockResolvedValue({ items: [PUBLISHED] })
    await w.find('.undo-link').trigger('click')
    await flushPromises()

    expect(api.undeleteHistory).toHaveBeenCalledWith('7')
    expect(w.text()).not.toContain('撤销窗口内')
    // Restored: normal action buttons are back, no leftover error toast.
    const notify = useNotificationsStore()
    expect(notify.toasts.some((t) => t.severity === 'error')).toBe(false)
    expect(w.find('.row-actions button:last-child').exists()).toBe(true)
  })

  it('edge case: undo window times out and the row disappears from view', async () => {
    vi.useFakeTimers()
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()

    await w.find('.row-actions button:last-child').trigger('click')
    await flushPromises()
    expect(w.findAll('tbody tr')).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(15_000)
    await flushPromises()

    expect(w.findAll('tbody tr')).toHaveLength(0)
  })

  it('edge case: a manual refetch within the undo window keeps the row visible with no flicker', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()

    await w.find('.row-actions button:last-child').trigger('click')
    await flushPromises()
    expect(w.findAll('tbody tr')).toHaveLength(1)
    expect(w.text()).toContain('已删除')

    // Simulate the deleted-window read path (server truth) still returning
    // the row on a refetch/invalidate that happens mid-window.
    vi.mocked(api.listHistoryDeletedWindow).mockResolvedValue({
      items: [{ ...PUBLISHED, deleted_at: new Date().toISOString() }],
    })
    vi.mocked(api.listHistory).mockResolvedValue({ items: [] })
    await lastQueryClient.invalidateQueries({ queryKey: ['history'] })
    await flushPromises()

    // Row is still present throughout — no removal, no bounce-back.
    expect(w.findAll('tbody tr')).toHaveLength(1)
    expect(w.text()).toContain('已删除')
  })

  it('edge case: bulk-delete reports accurate deleted/skipped counts', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED, OTHER] })
    vi.mocked(api.bulkDeleteHistory).mockResolvedValue({
      items: [FAILED],
      message: '已删除 2 条历史记录，1 条已跳过（不存在或已删除）',
      deleted: 2,
      skipped: 1,
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    const checkboxes = w.findAll('tbody tr input[type="checkbox"]')
    await checkboxes[0].setValue(true)
    await checkboxes[2].setValue(true)
    await w.find('.bulk-delete').trigger('click')
    await flushPromises()

    expect(api.bulkDeleteHistory).toHaveBeenCalledWith(['7', '9'])
    expect(
      notify.toasts.some((t) => t.message.includes('已删除 2 条历史记录') && t.message.includes('1 条已跳过')),
    ).toBe(true)
  })

  it('edge case: refetch removing a selected (non-soft-deleted) row auto-prunes selection', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, OTHER] })
    const w = mountPage()
    await flushPromises()

    const checkboxes = w.findAll('tbody tr input[type="checkbox"]')
    await checkboxes[0].setValue(true) // select PUBLISHED
    await checkboxes[1].setValue(true) // select OTHER
    expect(w.find('.bulk-delete').text()).toContain('(2)')

    // Another session hard-removed OTHER entirely (not soft-deleted — it's
    // simply gone from both the live list and the deleted-window list).
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    await lastQueryClient.invalidateQueries({ queryKey: ['history'] })
    await flushPromises()

    expect(w.findAll('tbody tr')).toHaveLength(1)
    expect(w.find('.bulk-delete').text()).toContain('(1)')
  })

  it('mutual exclusion: row A busy does not block row B; bulk buttons lock while any row is busy', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, OTHER] })
    let resolveDeleteA!: (v: { items: typeof PUBLISHED[] }) => void
    const pendingA = new Promise<{ items: typeof PUBLISHED[] }>((res) => {
      resolveDeleteA = res
    })
    vi.mocked(api.deleteHistory).mockImplementation((id: string) =>
      id === '7' ? pendingA : Promise.resolve({ items: [PUBLISHED] }),
    )
    const w = mountPage()
    await flushPromises()

    const rows = w.findAll('tbody tr')
    await rows[0].find('.row-actions button:last-child').trigger('click') // delete row A (7), in-flight

    // Row A's own buttons are disabled while its delete is in flight.
    expect((rows[0].find('.row-actions button:last-child').element as HTMLButtonElement).disabled).toBe(true)

    // Row B (9) can still act — recheck/delete stay enabled.
    const rowBDeleteBtn = w.findAll('tbody tr')[1].find('.row-actions button:last-child')
    expect((rowBDeleteBtn.element as HTMLButtonElement).disabled).toBe(false)

    // Bulk buttons lock while ANY row op is in flight.
    expect((w.find('.bulk-delete').element as HTMLButtonElement).disabled).toBe(true)

    resolveDeleteA({ items: [OTHER] })
    await flushPromises()
    expect((w.find('.bulk-delete').element as HTMLButtonElement).disabled).toBe(true) // still no selection
  })

  it('mutual exclusion: bulk operation in progress locks the whole table', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, OTHER] })
    let resolveBulk!: (v: { items: typeof PUBLISHED[] }) => void
    const pending = new Promise<{ items: typeof PUBLISHED[] }>((res) => {
      resolveBulk = res
    })
    vi.mocked(api.bulkDeleteHistory).mockReturnValue(pending)
    const w = mountPage()
    await flushPromises()

    await w.find('tbody tr input[type="checkbox"]').setValue(true)
    await w.find('.bulk-delete').trigger('click')

    for (const cb of w.findAll('tbody tr input[type="checkbox"]')) {
      expect((cb.element as HTMLInputElement).disabled).toBe(true)
    }
    for (const btn of w.findAll('.row-actions button')) {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    }

    resolveBulk({ items: [] })
    await flushPromises()
  })

  it('rapid repeated clicks on the same delete button only trigger one API call', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    let resolveDelete!: (v: { items: typeof PUBLISHED[] }) => void
    const pending = new Promise<{ items: typeof PUBLISHED[] }>((res) => {
      resolveDelete = res
    })
    vi.mocked(api.deleteHistory).mockReturnValue(pending)
    const w = mountPage()
    await flushPromises()

    const btn = w.find('.row-actions button:last-child')
    await btn.trigger('click')
    await btn.trigger('click')
    await btn.trigger('click')

    expect(api.deleteHistory).toHaveBeenCalledTimes(1)
    resolveDelete({ items: [] })
    await flushPromises()
  })

  it('purge-failed is the one irreversible op: goes through ConfirmDialog with a frozen count', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
    vi.mocked(api.purgeFailedHistory).mockResolvedValue({
      items: [PUBLISHED],
      message: '已清除 1 条失败记录',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    const purgeBtn = w.findAll('.history__actions button').find((b) => b.text().includes('清除失败'))!
    await purgeBtn.trigger('click')
    await w.vm.$nextTick()

    expect(w.find('[role="dialog"]').exists()).toBe(true)
    expect(w.text()).toContain('确认清除（1 条）')

    const confirmBtn = w.find('.cdlg__confirm')
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(api.purgeFailedHistory).toHaveBeenCalledTimes(1)
    expect(notify.toasts.some((t) => t.message.includes('已清除 1 条失败记录'))).toBe(true)
    expect(w.find('[role="dialog"]').exists()).toBe(false)
  })

  // ── W13: mutation error-report coverage (discovery #4 / D7 option b / D8) ──
  //
  // End-to-end through the REAL lib/errorCapture module (not mocked) —
  // stubs `fetch` and asserts on POST /error-reports calls, exactly like
  // errorCapture.spec.ts's own hook tests, so this proves the full path:
  // HistoryPage's catch block -> reportManualMutationError -> D8 filter ->
  // captureAndSubmit -> sendJson('/error-reports').

  interface ReportCall {
    url: string
    body: Record<string, unknown>
  }

  function installErrorReportFetchStub(): ReportCall[] {
    const calls: ReportCall[] = []
    let nextId = 1
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : {} })
        return new Response(
          JSON.stringify({ id: `hist-report-${nextId++}` }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    return calls
  }

  describe('W13: error-reports coverage for hand-written mutations', () => {
    beforeEach(() => {
      _resetCaptureStateForTest()
      document.head.innerHTML = '<meta name="csrf-token" content="test-token">'
    })

    afterEach(() => {
      vi.unstubAllGlobals()
      _resetCsrfForTest()
      document.head.innerHTML = ''
    })

    it('a 500 delete failure shows the classified toast AND submits an error-report', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.deleteHistory).mockRejectedValue(new ApiError('server exploded', 500, { detail: 'boom' }))
      const w = mountPage()
      const notify = useNotificationsStore()
      await flushPromises()

      await w.find('.row-actions button:last-child').trigger('click')
      await flushPromises()

      expect(notify.toasts.some((t) => t.severity === 'error' && t.message.includes('服务器出错了'))).toBe(
        true,
      )
      expect(calls).toHaveLength(1)
      expect(calls[0].url).toContain('/error-reports')
      expect(calls[0].body.message).toContain('history.delete')
    })

    it('a 422 delete failure shows the toast but does NOT submit an error-report (D8)', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.deleteHistory).mockRejectedValue(new ApiError('rejected', 422, { detail: '校验失败详情' }))
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:last-child').trigger('click')
      await flushPromises()

      expect(calls).toHaveLength(0)
    })

    it('a 403 (non-422 4xx, e.g. CSRF) delete failure IS reported — not swallowed as "just a 4xx"', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.deleteHistory).mockRejectedValue(new ApiError('forbidden', 403, {}))
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:last-child').trigger('click')
      await flushPromises()

      expect(calls).toHaveLength(1)
    })

    it('a network error (TypeError) on recheck is reported with the correct call-site context', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.recheckHistory).mockRejectedValue(new TypeError('Failed to fetch'))
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:first-child').trigger('click') // 重核
      await flushPromises()

      expect(calls).toHaveLength(1)
      expect(calls[0].body.message).toContain('history.recheck')
    })

    it('an aged-out undo (404) is reported, not treated as a silent expected outcome', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:last-child').trigger('click') // delete -> undo window
      await flushPromises()

      vi.mocked(api.undeleteHistory).mockRejectedValue(new ApiError('not found', 404, {}))
      await w.find('.undo-link').trigger('click')
      await flushPromises()

      expect(calls).toHaveLength(1)
      expect(calls[0].body.message).toContain('history.undelete')
    })
  })

  // ── W10: cross-page deep-link ───────────────────────────────────────────

  describe('W10: 查看报告 deep-link (row -> error-report)', () => {
    beforeEach(() => {
      _resetCaptureStateForTest()
      document.head.innerHTML = '<meta name="csrf-token" content="test-token">'
    })

    afterEach(() => {
      vi.unstubAllGlobals()
      _resetCsrfForTest()
      document.head.innerHTML = ''
    })

    it('happy path: a delete failure surfaces a "查看报告" link on that exact row, linking to the real report id', async () => {
      installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      vi.mocked(api.deleteHistory).mockRejectedValue(new ApiError('server exploded', 500, {}))
      const w = mountPage()
      await flushPromises()

      // Only row 7 (PUBLISHED) has its delete button clicked/fail — row 8 never did.
      await w.findAll('tbody tr')[0].find('.row-actions button:last-child').trigger('click')
      await flushPromises()

      const rowReportLinks = useRowReportLinksStore()
      const reportId = rowReportLinks.reportIdForRow('7')
      expect(reportId).toBeTruthy()
      expect(rowReportLinks.reportIdForRow('8')).toBeUndefined()

      const link = w.find('a.row-report-link')
      expect(link.exists()).toBe(true)
      expect(link.attributes('href')).toBe(`/error-reports/${reportId}`)
    })

    it('a row whose action never failed shows no "查看报告" link (no fabricated correspondence)', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      const w = mountPage()
      await flushPromises()

      // FAILED here means the ORIGINAL PUBLISH failed — unrelated to any UI
      // mutation error-report; asserting this never gets a fabricated link.
      expect(w.find('a.row-report-link').exists()).toBe(false)
    })

    it('a subsequent successful delete clears the stale "查看报告" link for that row', async () => {
      installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.deleteHistory).mockRejectedValueOnce(new ApiError('server exploded', 500, {}))
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:last-child').trigger('click')
      await flushPromises()
      expect(w.find('a.row-report-link').exists()).toBe(true)

      vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
      await w.find('.row-actions button:last-child').trigger('click')
      await flushPromises()

      expect(w.find('a.row-report-link').exists()).toBe(false)
    })

    it('a 422 delete failure does not create a "查看报告" link (D8: not incident-class)', async () => {
      installErrorReportFetchStub()
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      vi.mocked(api.deleteHistory).mockRejectedValue(new ApiError('rejected', 422, {}))
      const w = mountPage()
      await flushPromises()

      await w.find('.row-actions button:last-child').trigger('click')
      await flushPromises()

      expect(w.find('a.row-report-link').exists()).toBe(false)
    })
  })

  describe('W10: highlight-on-return from an error-report\'s "回到来源"', () => {
    it('happy path: ?highlight=<id> scrolls to and highlights the matching row, with an sr-only announcement', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
      const w = await mountPageAt('/history?highlight=8')
      await flushPromises()

      const scrollSpy = vi.mocked(Element.prototype.scrollIntoView)
      expect(scrollSpy).toHaveBeenCalled()

      const row = w.findAll('tbody tr').find((r) => r.attributes('data-row-id') === '8')!
      expect(row.classes()).toContain('row--highlight')
      expect(w.text()).toContain('已定位到目标记录')

      // The query param is stripped so a refresh/back doesn't re-trigger it.
      expect(lastRouter.currentRoute.value.query.highlight).toBeUndefined()
    })

    it('edge case: a highlight target no longer in the list shows a non-silent "not in list" notice', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      const w = await mountPageAt('/history?highlight=does-not-exist')
      await flushPromises()

      expect(w.find('.highlight-missing').exists()).toBe(true)
      expect(w.text()).toContain('该项目已不在列表中')
    })

    it('the "not in list" notice can be dismissed', async () => {
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      const w = await mountPageAt('/history?highlight=does-not-exist')
      await flushPromises()

      expect(w.find('.highlight-missing').exists()).toBe(true)
      await w.find('.highlight-missing__dismiss').trigger('click')
      expect(w.find('.highlight-missing').exists()).toBe(false)
    })

    it('a11y: reduced motion uses an instant (non-smooth) scroll', async () => {
      const matchMediaSpy = vi.fn().mockReturnValue({ matches: true })
      vi.stubGlobal('matchMedia', matchMediaSpy)
      vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
      const w = await mountPageAt('/history?highlight=7')
      await flushPromises()

      const scrollSpy = vi.mocked(Element.prototype.scrollIntoView)
      expect(scrollSpy).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'auto' }))
      expect(w.exists()).toBe(true)
      vi.unstubAllGlobals()
    })
  })
})
