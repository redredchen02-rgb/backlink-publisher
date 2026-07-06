import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createMemoryHistory, createRouter } from 'vue-router'

vi.mock('../../api/monitor', () => ({ monitorSummary: vi.fn() }))

import * as api from '../../api/monitor'
import MonitorDashboard from './MonitorDashboard.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

function makeRouter(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', name: 'monitor', component: { template: '<div />' } }],
  })
  router.push({ path: '/', query })
  return router
}

async function mountDashboard(router = makeRouter()) {
  await router.isReady()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const w = mount(MonitorDashboard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
  })
  await flushPromises()
  return { w, router }
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
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
