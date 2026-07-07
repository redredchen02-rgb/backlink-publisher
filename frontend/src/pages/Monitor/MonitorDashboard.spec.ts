import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'

vi.mock('../../api/monitor', () => ({
  monitorSummary: vi.fn(),
  retryQueueTask: vi.fn(),
  verifyChannel: vi.fn(),
  fetchPipelineHealth: vi.fn(),
}))
vi.mock('../../api/errorReports', () => ({ updateErrorReport: vi.fn() }))
vi.mock('../../api/keepAlive', () => ({ startRecheck: vi.fn(), pollRecheck: vi.fn() }))

import * as api from '../../api/monitor'
import * as errorReportsApi from '../../api/errorReports'
import * as keepAliveApi from '../../api/keepAlive'
import { ApiError } from '../../api/client'
import MonitorDashboard from './MonitorDashboard.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>
const mountedWrappers: Array<{ unmount: () => void }> = []

function makeRouter(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'monitor', component: { template: '<div />' } }],
  })
  router.push({ path: '/', query })
  return router
}

async function mountDashboard(router = makeRouter(), attach = false) {
  await router.isReady()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const w = mount(MonitorDashboard, {
    attachTo: attach ? document.body : undefined,
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
  })
  mountedWrappers.push(w)
  await flushPromises()
  return { w, router, queryClient }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  // Default: an established install (never_run: false) — most existing tests
  // below don't care about the guidance card, so they get the "no guidance"
  // baseline unless a test overrides this mock explicitly.
  vi.mocked(api.fetchPipelineHealth).mockResolvedValue({
    healthy: true, never_run: false, never_run_reason: null, degraded_reasons: [],
  })
})

afterEach(() => {
  // Focus-management tests attach to document.body — clean up so DOM/focus
  // state doesn't leak into the next test.
  while (mountedWrappers.length) mountedWrappers.pop()!.unmount()
})

const DANGER_CARD = {
  key: 'credentials',
  title: '渠道凭证',
  severity: 'danger' as const,
  headline: '2 个渠道凭证失效',
  detail: 'medium、blogger',
  deep_link: '/settings',
  action: { label: '去设置', href: '/settings' },
}
const OK_CARD = {
  key: 'keepalive',
  title: '保活',
  severity: 'ok' as const,
  headline: '120 条链接存活',
  detail: '目标 8 · 未知 0',
  deep_link: '/ce:keep-alive',
  action: null,
}

describe('MonitorDashboard — anomaly-first aggregate', () => {
  it('renders server-ranked cards and an anomaly banner when anomalies exist', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [DANGER_CARD, OK_CARD],
      anomaly_count: 1,
      degraded: false,
    })
    const { w } = await mountDashboard()

    const cards = w.findAll('.card')
    expect(cards).toHaveLength(2)
    // Server already ranked danger first; the SPA renders in order (no re-sort).
    expect(cards[0].attributes('data-severity')).toBe('danger')
    expect(w.find('.monitor__summary').text()).toContain('今日 1 项异常')
    // Dual-stack: deep-dive is a plain <a href> (full nav out of the SPA), marked ↪.
    const deep = cards[0].find('a.card__deep')
    expect(deep.attributes('href')).toBe('/settings')
    expect(deep.text()).toContain('↪')
  })

  it('shows the "no anomalies today" banner when all cards are healthy', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD],
      anomaly_count: 0,
      degraded: false,
    })
    const { w } = await mountDashboard()
    expect(w.find('.monitor__summary').text()).toContain('今日无异常')
  })

  it('renders the StateBlock error state (role=alert) when the fetch fails', async () => {
    vi.mocked(api.monitorSummary).mockRejectedValue({ status: 500 })
    const { w } = await mountDashboard()
    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.findAll('.card')).toHaveLength(0)
  })
})

describe('MonitorDashboard — flash message bridge (Plan 2026-07-06-004 Unit 5)', () => {
  beforeEach(() => {
    vi.mocked(api.monitorSummary).mockResolvedValue({ cards: [], anomaly_count: 0, degraded: false })
  })

  it('shows a success toast for flash_type=success&flash_msg=... and clears the query', async () => {
    const router = makeRouter({ flash_type: 'success', flash_msg: '草稿已保存' })
    await mountDashboard(router)

    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(1)
    expect(notify.toasts[0].severity).toBe('success')
    expect(notify.toasts[0].message).toBe('草稿已保存')

    // Cleared — a subsequent refresh (represented by the router's current
    // location) no longer carries flash_type/flash_msg.
    expect(router.currentRoute.value.query.flash_type).toBeUndefined()
    expect(router.currentRoute.value.query.flash_msg).toBeUndefined()
  })

  it('maps flash_type=danger to an error-severity toast', async () => {
    const router = makeRouter({ flash_type: 'danger', flash_msg: '删除检查点失败' })
    await mountDashboard(router)

    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(1)
    expect(notify.toasts[0].severity).toBe('error')
  })

  it('preserves unrelated query params while clearing only flash_type/flash_msg', async () => {
    const router = makeRouter({
      flash_type: 'success', flash_msg: '已完成', other: 'keep-me',
    })
    await mountDashboard(router)

    expect(router.currentRoute.value.query.flash_type).toBeUndefined()
    expect(router.currentRoute.value.query.flash_msg).toBeUndefined()
    expect(router.currentRoute.value.query.other).toBe('keep-me')
  })

  it('does not carry a message with & / # / newline characters incorrectly — arrives intact', async () => {
    const router = makeRouter({
      flash_type: 'success',
      flash_msg: '已保存 & 完成\n第二行 # 标签',
    })
    await mountDashboard(router)

    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(1)
    // Newline stripped by the client-side sanitizer; '&'/'#' preserved as text.
    expect(notify.toasts[0].message).toContain('已保存 & 完成')
    expect(notify.toasts[0].message).toContain('第二行 # 标签')
    expect(notify.toasts[0].message).not.toContain('\n')
  })

  it('does not crash when flash_msg is present but flash_type is missing (defaults sensibly)', async () => {
    const router = makeRouter({ flash_msg: '没有类型' })
    const { w } = await mountDashboard(router)

    expect(w.exists()).toBe(true)
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(1)
    // flashTypeToSeverity defaults an empty/unknown type to 'info'.
    expect(notify.toasts[0].severity).toBe('info')
  })

  it('does not crash when flash_type is present but flash_msg is missing', async () => {
    const router = makeRouter({ flash_type: 'success' })
    const { w } = await mountDashboard(router)

    expect(w.exists()).toBe(true)
    const notify = useNotificationsStore()
    // pushFlash is a no-op for an empty message — no toast, no throw.
    expect(notify.toasts).toHaveLength(0)
  })

  it('truncates a pathologically long flash_msg rather than breaking layout', async () => {
    const router = makeRouter({ flash_type: 'warning', flash_msg: 'x'.repeat(5000) })
    await mountDashboard(router)

    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(1)
    expect(notify.toasts[0].message.length).toBeLessThanOrEqual(200)
  })

  it('does not re-show the toast on a subsequent mount once the query is cleared (refresh simulation)', async () => {
    const router = makeRouter({ flash_type: 'success', flash_msg: '已保存' })
    await mountDashboard(router)
    let notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(1)
    notify.clear()

    // Simulate a page refresh: the query string on the router's current
    // location has already been cleared by the first mount, so mounting the
    // component again against the SAME (now-flash-free) route must not
    // re-show the toast.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    mount(MonitorDashboard, {
      global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
    })
    await flushPromises()

    notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('does nothing when neither flash_type nor flash_msg is present', async () => {
    const router = makeRouter()
    await mountDashboard(router)
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })
})

// ── Unit 6: interactive dashboard (hybrid cards, actions, undo, a11y) ────────

const ERROR_REPORT_ITEM = {
  id: 'er-1',
  item_type: 'error_report' as const,
  status: 'open',
  headline: 'TypeError: x is not a function',
  detail: '2026-07-05T10:00:00Z',
  severity: 'error',
  occurrences: 3,
}
const ERROR_REPORTS_CARD = {
  key: 'error_reports',
  title: '错误回报',
  severity: 'warning' as const,
  headline: '1 条待处理',
  detail: '共 1 笔开放中的错误回报',
  deep_link: '/error-reports',
  action: null,
  items: [ERROR_REPORT_ITEM],
}

const QUEUE_ITEM = {
  id: 'q-1',
  item_type: 'queue_task' as const,
  status: 'failed',
  headline: 'https://example.com/post',
  detail: 'timeout',
}
const SCHEDULE_QUEUE_CARD = {
  key: 'schedule_queue',
  title: '排程/队列',
  severity: 'warning' as const,
  headline: '1 项待处理',
  detail: '卡住排程 0 · 待重试 0 · 重试失败 1 · 即将发布 0',
  deep_link: '/schedule',
  action: null,
  items: [QUEUE_ITEM],
}

function findButtonByText(w: ReturnType<typeof mount>, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('MonitorDashboard — hybrid cards expand/collapse (Plan 2026-07-06-004 Unit 6)', () => {
  it('renders collapsed by default; toggle expands to show the server-sent items', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [ERROR_REPORTS_CARD], anomaly_count: 1, degraded: false,
    })
    const { w } = await mountDashboard()

    expect(w.find('.card__items').exists()).toBe(false)
    const toggle = w.find('.card__toggle')
    expect(toggle.exists()).toBe(true)
    expect(toggle.text()).toContain('1')

    await toggle.trigger('click')
    expect(w.find('.card__items').exists()).toBe(true)
    expect(w.text()).toContain(ERROR_REPORT_ITEM.headline)
  })

  it('the 4 original aggregate-only cards never render a toggle or items list', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [DANGER_CARD, OK_CARD], anomaly_count: 1, degraded: false,
    })
    const { w } = await mountDashboard()
    expect(w.find('.card__toggle').exists()).toBe(false)
    expect(w.find('.card__items').exists()).toBe(false)
  })
})

describe('MonitorDashboard — mark-resolved (terminal, with undo)', () => {
  it('happy path: busy while in flight, removes the item and offers undo on success', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [ERROR_REPORTS_CARD], anomaly_count: 1, degraded: false,
    })
    let resolvePatch!: (v: errorReportsApi.ErrorReportItem) => void
    vi.mocked(errorReportsApi.updateErrorReport).mockReturnValue(
      new Promise((res) => { resolvePatch = res }),
    )
    const { w } = await mountDashboard()
    await w.find('.card__toggle').trigger('click')

    const btn = findButtonByText(w, '标记已解决')!
    await btn.trigger('click')
    await w.vm.$nextTick()
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    expect(btn.text()).toContain('处理中')

    resolvePatch({ ...ERROR_REPORT_ITEM, status: 'resolved' })
    await flushPromises()

    expect(errorReportsApi.updateErrorReport).toHaveBeenCalledWith('er-1', { status: 'resolved' })
    expect(w.find('.card-item').exists()).toBe(false) // removed from the expanded list

    const notify = useNotificationsStore()
    const toast = notify.toasts.find((t) => t.undoAction)
    expect(toast).toBeTruthy()
    expect(toast!.undoAction!.label).toBe('撤销')
  })

  it('undo re-PATCHes status=open and re-inserts the item without waiting for a poll', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [ERROR_REPORTS_CARD], anomaly_count: 1, degraded: false,
    })
    vi.mocked(errorReportsApi.updateErrorReport)
      .mockResolvedValueOnce({ ...ERROR_REPORT_ITEM, status: 'resolved' })
      .mockResolvedValueOnce({ ...ERROR_REPORT_ITEM, status: 'open' })
    const { w } = await mountDashboard()
    await w.find('.card__toggle').trigger('click')

    await findButtonByText(w, '标记已解决')!.trigger('click')
    await flushPromises()
    expect(w.find('.card-item').exists()).toBe(false)

    const notify = useNotificationsStore()
    const toast = notify.toasts.find((t) => t.undoAction)!
    toast.undoAction!.onClick()
    await flushPromises()
    await w.vm.$nextTick()

    expect(errorReportsApi.updateErrorReport).toHaveBeenLastCalledWith('er-1', { status: 'open' })
    expect(w.find('.card-item').exists()).toBe(true)
    expect(w.text()).toContain(ERROR_REPORT_ITEM.headline)
  })

  it('a failed mark-resolved leaves the item in place with an inline error, button re-enabled', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [ERROR_REPORTS_CARD], anomaly_count: 1, degraded: false,
    })
    vi.mocked(errorReportsApi.updateErrorReport).mockRejectedValue(new ApiError('服务暂时不可用', 502, {}))
    const { w } = await mountDashboard()
    await w.find('.card__toggle').trigger('click')

    const btn = findButtonByText(w, '标记已解决')!
    await btn.trigger('click')
    await flushPromises()

    expect(w.find('.card-item').exists()).toBe(true) // never removed on failure
    expect((btn.element as HTMLButtonElement).disabled).toBe(false) // clickable again
    expect(w.find('.field-error').exists()).toBe(true)
  })
})

describe('MonitorDashboard — retry (non-terminal, no undo)', () => {
  it('happy path: keeps the item visible and updates its status text (never a false completion)', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [SCHEDULE_QUEUE_CARD], anomaly_count: 1, degraded: false,
    })
    vi.mocked(api.retryQueueTask).mockResolvedValue({
      ok: true, flash_type: 'success', flash_msg: '任务已重新排入队列，等待后台处理', message: '...',
    })
    const { w, queryClient } = await mountDashboard()
    await w.find('.card__toggle').trigger('click')

    const btn = findButtonByText(w, '重试')!
    await btn.trigger('click')
    await flushPromises()

    expect(api.retryQueueTask).toHaveBeenCalledWith('q-1')
    expect(w.find('.card-item').exists()).toBe(true) // NOT removed — retry is not terminal
    expect(w.text()).toContain('任务已重新排入队列')
    expect(findButtonByText(w, '撤销')).toBeUndefined() // retry has no undo

    // A later poll tick where the server's own get_runnable() STILL includes
    // this task (still 'pending') must not cause a disappear/reappear
    // flicker — the item was never locally removed, so this is a plain
    // cache replace, not a re-add.
    await queryClient.refetchQueries({ queryKey: ['monitor-summary'] })
    await flushPromises()
    expect(w.find('.card-item').exists()).toBe(true)
  })

  it('error path: retry on an already-vanished task shows inline text, not a false success', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [SCHEDULE_QUEUE_CARD], anomaly_count: 1, degraded: false,
    })
    vi.mocked(api.retryQueueTask).mockRejectedValue(
      new ApiError('任务不存在，可能已被处理', 404, { error_class: 'not_found' }),
    )
    const { w } = await mountDashboard()
    await w.find('.card__toggle').trigger('click')

    await findButtonByText(w, '重试')!.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('任务不存在，可能已被处理')
    expect(w.find('.card-item').exists()).toBe(true) // still there — no false "重试成功"
  })
})

describe('MonitorDashboard — credential re-verify', () => {
  it('failure shows an inline error on that specific channel only; other channels unaffected', async () => {
    const credCard = { ...DANGER_CARD, failed_channels: ['medium', 'blogger'] }
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [credCard], anomaly_count: 1, degraded: false,
    })
    vi.mocked(api.verifyChannel).mockImplementation(async (channel: string) => {
      if (channel === 'medium') {
        return {
          ok: false, identity: null, last_verified_at: null,
          last_verify_result: 'token_expired',
          blockers: ['Medium session expired — reconnect via Settings.'],
          dofollow: null,
        }
      }
      return {
        ok: true, identity: 'me', last_verified_at: null,
        last_verify_result: 'ok', blockers: [], dofollow: true,
      }
    })
    const { w } = await mountDashboard()

    const mediumBtn = w.findAll('button').find((b) => b.text().includes('medium'))!
    const bloggerBtn = w.findAll('button').find((b) => b.text().includes('blogger'))!

    await mediumBtn.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('Medium session expired')
    expect((bloggerBtn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('success shows a toast and refreshes the aggregate (sync, per Unit 3)', async () => {
    const credCard = { ...DANGER_CARD, failed_channels: ['medium'] }
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [credCard], anomaly_count: 1, degraded: false,
    })
    vi.mocked(api.verifyChannel).mockResolvedValue({
      ok: true, identity: 'me', last_verified_at: null,
      last_verify_result: 'ok', blockers: [], dofollow: true,
    })
    const { w } = await mountDashboard()

    const btn = w.findAll('button').find((b) => b.text().includes('medium'))!
    await btn.trigger('click')
    await flushPromises()

    const notify = useNotificationsStore()
    expect(notify.toasts.some((t) => t.message.includes('验证成功'))).toBe(true)
    expect(vi.mocked(api.monitorSummary).mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})

describe('MonitorDashboard — keep-alive trigger recheck', () => {
  it('starts a job and shows success once the poll reports completed', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: false,
    })
    vi.mocked(keepAliveApi.startRecheck).mockResolvedValue({ status: 'started', job_id: 'job-1' })
    vi.mocked(keepAliveApi.pollRecheck).mockResolvedValue({ status: 'completed', message: '巡检完成' })

    const { w } = await mountDashboard()
    const btn = w.findAll('button').find((b) => b.text().includes('触发巡检'))!
    await btn.trigger('click')
    await flushPromises()
    await flushPromises()

    const notify = useNotificationsStore()
    expect(notify.toasts.some((t) => t.message === '巡检完成')).toBe(true)
    expect(btn.text()).toContain('触发巡检') // busy cleared, back to idle label
  })

  it('shows an info toast when already running (no job_id returned)', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: false,
    })
    vi.mocked(keepAliveApi.startRecheck).mockResolvedValue({ status: 'running', message: '巡检已在进行中' })
    const { w } = await mountDashboard()

    const btn = w.findAll('button').find((b) => b.text().includes('触发巡检'))!
    await btn.trigger('click')
    await flushPromises()

    const notify = useNotificationsStore()
    expect(notify.toasts.some((t) => t.message === '巡检已在进行中')).toBe(true)
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('MonitorDashboard — degraded state is visually distinct (R11/R18)', () => {
  it('degraded=true renders a distinguishing note, separate from the zero-anomaly ok state', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: true,
    })
    const { w } = await mountDashboard()

    expect(w.find('.ok').exists()).toBe(true)
    const note = w.find('.degraded-note')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('不可用')
  })

  it('degraded=false shows no distinguishing note', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: false,
    })
    const { w } = await mountDashboard()
    expect(w.find('.degraded-note').exists()).toBe(false)
  })
})

describe('MonitorDashboard — focus management after item removal (accessibility)', () => {
  it('moves focus to the next sibling item action button when one remains', async () => {
    const item2 = { ...ERROR_REPORT_ITEM, id: 'er-2', headline: 'second error' }
    const card = { ...ERROR_REPORTS_CARD, items: [ERROR_REPORT_ITEM, item2] }
    vi.mocked(api.monitorSummary).mockResolvedValue({ cards: [card], anomaly_count: 1, degraded: false })
    vi.mocked(errorReportsApi.updateErrorReport).mockResolvedValue({ ...ERROR_REPORT_ITEM, status: 'resolved' })

    const { w } = await mountDashboard(makeRouter(), true)
    await w.find('.card__toggle').trigger('click')

    const findResolveButtons = () => w.findAll('button').filter((b) => b.text() === '标记已解决')
    expect(findResolveButtons()).toHaveLength(2)

    await findResolveButtons()[0].trigger('click')
    await flushPromises()
    await w.vm.$nextTick()

    const remaining = findResolveButtons()
    expect(remaining).toHaveLength(1)
    expect(document.activeElement).toBe(remaining[0].element)
  })

  it('falls back to the card head when no sibling remains — never to <body>', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [ERROR_REPORTS_CARD], anomaly_count: 1, degraded: false,
    })
    vi.mocked(errorReportsApi.updateErrorReport).mockResolvedValue({ ...ERROR_REPORT_ITEM, status: 'resolved' })

    const { w } = await mountDashboard(makeRouter(), true)
    await w.find('.card__toggle').trigger('click')

    await findButtonByText(w, '标记已解决')!.trigger('click')
    await flushPromises()
    await w.vm.$nextTick()

    const head = w.find('.card__head')
    expect(document.activeElement).toBe(head.element)
    expect(document.activeElement).not.toBe(document.body)
  })
})

// ── Never-run guidance card (Plan 2026-07-06-005 W15 / D13) ─────────────────
// The guidance card reads a SEPARATE data source (fetchPipelineHealth(),
// legacy bare /health — see api/monitor.ts) than the anomaly cards above
// (monitorSummary(), /api/v1/monitor/summary). The two queries are
// independent, so these tests vary each one on its own.

describe('MonitorDashboard — never-run guidance card', () => {
  it('happy path: never_run + no other faults shows the guidance card, no degraded styling', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: false,
    })
    vi.mocked(api.fetchPipelineHealth).mockResolvedValue({
      healthy: true, never_run: true, never_run_reason: 'pipeline:never_run', degraded_reasons: [],
    })
    const { w } = await mountDashboard()

    const guidance = w.find('.guidance-card')
    expect(guidance.exists()).toBe(true)
    expect(guidance.text()).toContain('下一步：执行第一次发布')
    // Actionable link to the publish workbench, not a dead-end.
    const action = guidance.find('.guidance-card__action')
    expect(action.attributes('href')).toBe('/publish')
    // Not styled/labeled as a degraded/failure warning.
    expect(w.find('.degraded-note').exists()).toBe(false)
    expect(guidance.find('[data-severity="danger"]').exists()).toBe(false)
  })

  it('edge case: never_run coincides with a real fault — both the guidance card and the fault card show (D13: guidance never masks a real error)', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [DANGER_CARD], anomaly_count: 1, degraded: false,
    })
    vi.mocked(api.fetchPipelineHealth).mockResolvedValue({
      healthy: false, never_run: true, never_run_reason: 'pipeline:never_run',
      degraded_reasons: ['channel:medium:expired'],
    })
    const { w } = await mountDashboard()

    expect(w.find('.guidance-card').exists()).toBe(true)
    const dangerCard = w.find('.card[data-severity="danger"]')
    expect(dangerCard.exists()).toBe(true)
    expect(dangerCard.text()).toContain('渠道凭证失效')
  })

  it('regression: never_run=false (has publish history) never shows the guidance card', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: false,
    })
    vi.mocked(api.fetchPipelineHealth).mockResolvedValue({
      healthy: true, never_run: false, never_run_reason: null, degraded_reasons: [],
    })
    const { w } = await mountDashboard()
    expect(w.find('.guidance-card').exists()).toBe(false)
  })

  it('edge case: the health call fails — no guidance card, but the rest of the dashboard is unaffected (fail-open)', async () => {
    vi.mocked(api.monitorSummary).mockResolvedValue({
      cards: [OK_CARD], anomaly_count: 0, degraded: false,
    })
    vi.mocked(api.fetchPipelineHealth).mockRejectedValue(new Error('network error'))
    const { w } = await mountDashboard()

    expect(w.find('.guidance-card').exists()).toBe(false)
    // The primary dashboard (driven entirely by monitorSummary) still renders
    // normally — the failed, independent health query must not regress it.
    expect(w.findAll('.card')).toHaveLength(1)
    expect(w.find('.monitor__summary').text()).toContain('今日无异常')
  })
})
