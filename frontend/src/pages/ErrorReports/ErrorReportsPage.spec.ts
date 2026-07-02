import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../../api/errorReports', () => ({
  listErrorReports: vi.fn(),
}))

import * as api from '../../api/errorReports'
import type { ErrorReportItem } from '../../api/errorReports'
import ErrorReportsPage from './ErrorReportsPage.vue'

const OPEN_REPORT: ErrorReportItem = {
  id: 'report-1',
  status: 'open',
  severity: 'error',
  source: 'vue-error-handler',
  occurrences: 3,
  message: 'TypeError: x is not a function',
  last_seen_at: '2026-07-01T12:00:00Z',
}
const RESOLVED_REPORT: ErrorReportItem = {
  id: 'report-2',
  status: 'resolved',
  severity: 'warning',
  source: 'manual',
  occurrences: 1,
  message: 'Manually reported issue',
  last_seen_at: '2026-06-30T09:00:00Z',
}

let pinia: ReturnType<typeof createPinia>

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/error-reports', name: 'error-reports', component: { template: '<div />' } },
      {
        path: '/error-reports/:id',
        name: 'error-report-detail',
        component: { template: '<div>detail</div>' },
      },
    ],
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

async function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = makeRouter()
  router.push('/error-reports')
  await router.isReady()
  const w = mount(ErrorReportsPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
  })
  return { w, router }
}

describe('ErrorReportsPage', () => {
  it('renders a mocked API list response', async () => {
    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [OPEN_REPORT, RESOLVED_REPORT], total: 2 })
    const { w } = await mountPage()
    await flushPromises()

    expect(w.findAll('tbody tr')).toHaveLength(2)
    expect(w.text()).toContain('TypeError: x is not a function')
    expect(w.text()).toContain('共 2 条')
  })

  it('clicking a report navigates to /error-reports/:id', async () => {
    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [OPEN_REPORT], total: 1 })
    const { w, router } = await mountPage()
    await flushPromises()

    await w.find('a.detail-link').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/error-reports/report-1')
  })

  it('shows "尚无任何错误报告" when the dataset is genuinely empty, not a stuck spinner', async () => {
    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [], total: 0 })
    const { w } = await mountPage()
    await flushPromises()

    expect(w.text()).toContain('尚无任何错误报告')
    expect(w.find('[aria-busy="true"]').exists()).toBe(false)
    // Paired: this generic empty text must NOT be conflated with the
    // filtered-to-zero message.
    expect(w.text()).not.toContain('没有符合目前筛选条件的错误报告')
  })

  it('shows the StateBlock error state (not the empty state) when the list GET fails', async () => {
    vi.mocked(api.listErrorReports).mockRejectedValue({ status: 500 })
    const { w } = await mountPage()
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.text()).not.toContain('尚无任何错误报告')
  })

  it('filtering down to zero results shows the distinct "no matches" empty state with a clear-filters action', async () => {
    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [OPEN_REPORT], total: 1 })
    const { w } = await mountPage()
    await flushPromises()

    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [], total: 0 })
    await w.find('select[aria-label="按状态筛选"]').setValue('resolved')
    await flushPromises()

    expect(w.text()).toContain('没有符合目前筛选条件的错误报告')
    // Paired: distinct from the "genuinely empty dataset" copy.
    expect(w.text()).not.toContain('尚无任何错误报告')
    expect(w.findAll('button').some((b) => b.text() === '清除筛选')).toBe(true)
  })

  it('clearing filters after a zero-match filter restores the full list', async () => {
    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [OPEN_REPORT], total: 1 })
    const { w } = await mountPage()
    await flushPromises()

    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [], total: 0 })
    await w.find('select[aria-label="按状态筛选"]').setValue('resolved')
    await flushPromises()

    vi.mocked(api.listErrorReports).mockResolvedValue({ items: [OPEN_REPORT], total: 1 })
    const clearBtn = w.findAll('button').find((b) => b.text() === '清除筛选')!
    await clearBtn.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('TypeError: x is not a function')
  })

  it('renders an HTML-looking message as literal text, never parsed markup (XSS regression guard)', async () => {
    vi.mocked(api.listErrorReports).mockResolvedValue({
      items: [{ ...OPEN_REPORT, message: '<script>alert(1)</script><b>bold</b>' }],
      total: 1,
    })
    const { w } = await mountPage()
    await flushPromises()

    expect(w.find('script').exists()).toBe(false)
    expect(w.find('b').exists()).toBe(false)
    expect(w.text()).toContain('<script>alert(1)</script><b>bold</b>')
  })
})
