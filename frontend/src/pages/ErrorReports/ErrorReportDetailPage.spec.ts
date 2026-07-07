import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../../api/errorReports', () => ({
  getErrorReport: vi.fn(),
  updateErrorReport: vi.fn(),
  listErrorReports: vi.fn(),
}))

import * as api from '../../api/errorReports'
import ErrorReportDetailPage from './ErrorReportDetailPage.vue'
import ErrorReportsPage from './ErrorReportsPage.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useRowReportLinksStore } from '../../stores/rowReportLinks'

const BASE_REPORT = {
  id: 'report-1',
  status: 'open' as const,
  severity: 'error',
  source: 'vue-error-handler',
  occurrences: 2,
  created_at: '2026-07-01T10:00:00Z',
  last_seen_at: '2026-07-01T12:00:00Z',
  message: 'TypeError: x is not a function',
  stack: 'at foo (app.js:1:1)',
  url: 'https://example.test/app/publish',
}

let pinia: ReturnType<typeof createPinia>

function makeRouter(initialPath = '/error-reports/report-1') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/error-reports', name: 'error-reports', component: { template: '<div />' } },
      {
        path: '/error-reports/:id',
        name: 'error-report-detail',
        component: { template: '<div />' },
      },
      { path: '/history', name: 'history', component: { template: '<div />' } },
    ],
  })
  router.push(initialPath)
  return router
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

async function mountDetail(queryClient?: QueryClient, router?: ReturnType<typeof makeRouter>) {
  const qc = queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const r = router ?? makeRouter()
  await r.isReady()
  const w = mount(ErrorReportDetailPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient: qc }], r] },
  })
  return { w, qc, router: r }
}

describe('ErrorReportDetailPage', () => {
  it('renders full report detail, including user_description when present', async () => {
    vi.mocked(api.getErrorReport).mockResolvedValue({
      ...BASE_REPORT,
      user_description: 'Happened right after clicking Save',
    })
    const { w } = await mountDetail()
    await flushPromises()

    expect(w.text()).toContain('TypeError: x is not a function')
    expect(w.text()).toContain('at foo (app.js:1:1)')
    expect(w.text()).toContain('用户补充说明')
    expect(w.text()).toContain('Happened right after clicking Save')
  })

  it('does NOT render the user_description section when absent (paired negative)', async () => {
    vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT })
    const { w } = await mountDetail()
    await flushPromises()

    expect(w.text()).not.toContain('用户补充说明')
  })

  it('renders stack/message containing HTML-looking characters as literal text (XSS guard)', async () => {
    vi.mocked(api.getErrorReport).mockResolvedValue({
      ...BASE_REPORT,
      message: '<script>alert(1)</script>',
      user_description: '<b>bold</b> and <img src=x onerror=alert(1)>',
    })
    const { w } = await mountDetail()
    await flushPromises()

    expect(w.find('script').exists()).toBe(false)
    expect(w.find('b').exists()).toBe(false)
    expect(w.find('img').exists()).toBe(false)
    expect(w.text()).toContain('<script>alert(1)</script>')
    expect(w.text()).toContain('<b>bold</b> and <img src=x onerror=alert(1)>')
  })

  it('the "add detail" action PATCHes description via updateErrorReport (persistent R2 path)', async () => {
    vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT })
    vi.mocked(api.updateErrorReport).mockResolvedValue({
      ...BASE_REPORT,
      user_description: 'Steps: click Save twice quickly',
    })
    const { w } = await mountDetail()
    await flushPromises()

    await w.find('textarea').setValue('Steps: click Save twice quickly')
    await w.find('.add-detail button').trigger('click')
    await flushPromises()

    expect(api.updateErrorReport).toHaveBeenCalledWith('report-1', {
      description: 'Steps: click Save twice quickly',
    })
    expect(w.text()).toContain('Steps: click Save twice quickly')
  })

  it('blocks an empty "add detail" submission without calling the API', async () => {
    vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT })
    const { w } = await mountDetail()
    await flushPromises()

    await w.find('.add-detail button').trigger('click')
    await flushPromises()

    expect(api.updateErrorReport).not.toHaveBeenCalled()
    expect(w.find('.field-error').exists()).toBe(true)
  })

  it('shows the StateBlock error state for a 404 (not found), not a stuck loading spinner', async () => {
    vi.mocked(api.getErrorReport).mockRejectedValue({ status: 404, detail: 'not found' })
    const { w } = await mountDetail()
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('marking a report resolved surfaces a success toast', async () => {
    vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT })
    vi.mocked(api.updateErrorReport).mockResolvedValue({ ...BASE_REPORT, status: 'resolved' })
    const { w } = await mountDetail()
    const notify = useNotificationsStore()
    await flushPromises()

    const resolveBtn = w.findAll('.status-buttons button').find((b) => b.text() === '标记已解决')!
    await resolveBtn.trigger('click')
    await flushPromises()

    expect(api.updateErrorReport).toHaveBeenCalledWith('report-1', { status: 'resolved' })
    expect(notify.toasts.some((t) => t.severity === 'success')).toBe(true)
  })

  it('integration: resolving from the detail page is reflected on the list page via shared cache invalidation, without a full reload', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    // First call (list page's initial fetch) returns the still-open report;
    // the second call (triggered by invalidateQueries after the PATCH)
    // returns it resolved.
    vi.mocked(api.listErrorReports)
      .mockResolvedValueOnce({ items: [{ ...BASE_REPORT, status: 'open' }], total: 1 })
      .mockResolvedValueOnce({ items: [{ ...BASE_REPORT, status: 'resolved' }], total: 1 })
    vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT, status: 'open' })
    vi.mocked(api.updateErrorReport).mockResolvedValue({ ...BASE_REPORT, status: 'resolved' })

    const listRouter = makeRouter('/error-reports')
    await listRouter.isReady()
    const listWrapper = mount(ErrorReportsPage, {
      global: { plugins: [pinia, [VueQueryPlugin, { queryClient: qc }], listRouter] },
    })
    await flushPromises()
    expect(listWrapper.find('.status[data-status="open"]').exists()).toBe(true)

    const { w: detailWrapper } = await mountDetail(qc, makeRouter('/error-reports/report-1'))
    await flushPromises()

    const resolveBtn = detailWrapper
      .findAll('.status-buttons button')
      .find((b) => b.text() === '标记已解决')!
    await resolveBtn.trigger('click')
    await flushPromises()

    // No re-mount / manual refetch call here — the shared QueryClient's
    // invalidateQueries triggered the list page's own background refetch.
    expect(listWrapper.find('.status[data-status="resolved"]').exists()).toBe(true)
  })

  // ── W10: "回到来源" (back to source) ─────────────────────────────────────
  describe('W10 back-to-source', () => {
    it('tier 1: a session-known row correlation navigates to the row route with ?highlight=', async () => {
      vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT })
      const { w, router } = await mountDetail()
      const rowReportLinks = useRowReportLinksStore()
      rowReportLinks.link('history', '7', 'report-1')
      await flushPromises()

      const btn = w.find('.back-to-source__btn')
      expect(btn.exists()).toBe(true)
      expect(btn.text()).toContain('回到来源并定位记录')

      await btn.trigger('click')
      await flushPromises()

      expect(router.currentRoute.value.name).toBe('history')
      expect(router.currentRoute.value.query.highlight).toBe('7')
    })

    it('tier 2: no session correlation falls back to the captured same-origin url', async () => {
      vi.mocked(api.getErrorReport).mockResolvedValue({
        ...BASE_REPORT,
        url: `${window.location.origin}/app/history?foo=bar`,
      })
      const { w, router } = await mountDetail()
      await flushPromises()

      const btn = w.find('.back-to-source__btn')
      expect(btn.text()).toContain('回到来源页面')
      await btn.trigger('click')
      await flushPromises()

      expect(router.currentRoute.value.fullPath).toBe('/app/history?foo=bar')
    })

    it('neither tier available (cross-origin/missing url): the button is hidden, not pointing somewhere wrong', async () => {
      vi.mocked(api.getErrorReport).mockResolvedValue({ ...BASE_REPORT, url: 'https://evil.example/x' })
      const { w } = await mountDetail()
      await flushPromises()

      expect(w.find('.back-to-source__btn').exists()).toBe(false)
      expect(w.text()).toContain('暂无法定位来源页面')
    })
  })
})
