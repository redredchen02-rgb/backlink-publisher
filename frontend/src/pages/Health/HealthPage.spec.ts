// HealthPage — Plan 2026-07-02-001 U6.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/health', () => ({
  fetchHealthSummary: vi.fn(),
  fetchScorecardLinks: vi.fn(),
  recheckLink: vi.fn(),
  pausePlatform: vi.fn(),
  reverifyPlatform: vi.fn(),
  circuitResetPlatform: vi.fn(),
}))

import * as api from '../../api/health'
import HealthPage from './HealthPage.vue'
import { useNotificationsStore } from '../../stores/notifications'

function panel<T>(data: T, degraded = false) {
  return { data, degraded }
}

const BASE_SUMMARY = {
  projection: {
    events_inserted: 0, sources_projected: 0, latest_event_utc: null,
    gap: false, gap_reason: null, degraded: false, degraded_reason: null,
  },
  health: {
    window_days: 30, since_utc: '2026-06-01T00:00:00+00:00',
    success: { targets: 10, confirmed: 8, pct: 0.8 },
    per_adapter: [], errors: [], broken: [],
  },
  agg_degraded: false,
  panels: {
    canary: panel([{ platform: 'blogger', status: 'ok', consecutive_failures: 0, consecutive_oks: 5, quarantined: false, last_ok_at: null, last_drift_at: null }]),
    forward_path: panel([]),
    reconciliation_gaps: panel({}),
    recheck_decay: panel({}),
    channel_scorecard: panel([{ channel: 'blogger' }]),
    geo_panel: panel({}),
    pipeline_summary: panel({}),
    storage_health: panel({ events_db_mb: 12.5, events_rows: 100, events_db_warn: false }),
    platform_health: panel({
      blogger: {
        platform: 'blogger', last_success_at: null, last_failure_at: null,
        last_error_msg: null, consecutive_failures: 0, circuit_tripped: false,
        circuit_tripped_at: null, paused: false,
      },
    }),
    autopilot_alerts: panel([]),
    weights_snapshot: panel(null),
    decay_alerts: panel([]),
    gsc_indexation: panel([]),
    gsc_ranking: panel([]),
    publish_index_latency: panel([]),
    index_rate_by_channel: panel([]),
    impression_analysis: panel([]),
    ranking_lift_analysis: panel([]),
    referral_conversion: panel([]),
    cost_metrics: panel({}),
    decisions_by_platform: panel([]),
    publish_metrics: panel({
      success_rate: { targets: 10, confirmed: 8, pct: 0.8 },
      coverage: null, readiness: null, policy_mode: 'observe', enforce_channels: [],
    }),
  },
}

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(HealthPage, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

describe('HealthPage', () => {
  it('renders hero stats, scorecard, canary, and platform table on happy path', async () => {
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(BASE_SUMMARY as any)
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('80.0%') // success rate
    expect(w.text()).toContain('blogger')
    expect(w.text()).not.toContain('数据不可用')
  })

  it('shows a degraded tag for a panel whose degraded flag is true', async () => {
    const summary = {
      ...BASE_SUMMARY,
      panels: { ...BASE_SUMMARY.panels, canary: panel([], true) },
    }
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(summary as any)
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('数据不可用')
  })

  it('shows the projection degraded banner', async () => {
    const summary = {
      ...BASE_SUMMARY,
      projection: { ...BASE_SUMMARY.projection, degraded: true, degraded_reason: 'RuntimeError' },
    }
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(summary as any)
    const w = mountPage()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.text()).toContain('RuntimeError')
  })

  it('shows the error state when the summary fetch fails', async () => {
    vi.mocked(api.fetchHealthSummary).mockRejectedValue({ status: 500 })
    const w = mountPage()
    await flushPromises()
    expect(w.find('.state--error').exists()).toBe(true)
  })

  it('drills into a channel scorecard row and lists its links', async () => {
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(BASE_SUMMARY as any)
    vi.mocked(api.fetchScorecardLinks).mockResolvedValue({
      ok: true, links: [{ live_url: 'https://a.com/x' }],
    })
    const w = mountPage()
    await flushPromises()

    const viewLinksBtn = w.findAll('button').find((b) => b.text() === '查看链接')!
    await viewLinksBtn.trigger('click')
    await flushPromises()

    expect(api.fetchScorecardLinks).toHaveBeenCalledWith('blogger')
    expect(w.text()).toContain('https://a.com/x')
  })

  it('recheck-link action surfaces a success toast', async () => {
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(BASE_SUMMARY as any)
    vi.mocked(api.fetchScorecardLinks).mockResolvedValue({
      ok: true, links: [{ live_url: 'https://a.com/x' }],
    })
    vi.mocked(api.recheckLink).mockResolvedValue({ ok: true, verdict: 'alive' })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    const viewLinksBtn = w.findAll('button').find((b) => b.text() === '查看链接')!
    await viewLinksBtn.trigger('click')
    await flushPromises()

    const recheckBtn = w.findAll('button').find((b) => b.text() === '重核')!
    await recheckBtn.trigger('click')
    await flushPromises()

    expect(api.recheckLink).toHaveBeenCalledWith('https://a.com/x')
    expect(notify.toasts.some((t) => t.message.includes('已重新核实'))).toBe(true)
  })

  it('pauses a platform and surfaces a success toast', async () => {
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(BASE_SUMMARY as any)
    vi.mocked(api.pausePlatform).mockResolvedValue({ ok: true, platform: 'blogger', paused: true })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    const pauseBtn = w.findAll('.row-actions button')[0]
    await pauseBtn.trigger('click')
    await flushPromises()

    expect(api.pausePlatform).toHaveBeenCalledWith('blogger', true)
    expect(notify.toasts.some((t) => t.message.includes('已暂停'))).toBe(true)
  })

  it('reverifies a platform and surfaces the ready result', async () => {
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(BASE_SUMMARY as any)
    vi.mocked(api.reverifyPlatform).mockResolvedValue({
      ok: true, platform: 'blogger', ready: true, reason: '',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    const reverifyBtn = w.findAll('.row-actions button')[1]
    await reverifyBtn.trigger('click')
    await flushPromises()

    expect(api.reverifyPlatform).toHaveBeenCalledWith('blogger')
    expect(notify.toasts.some((t) => t.message.includes('校验通过'))).toBe(true)
  })

  it('circuit-reset button is disabled unless the circuit is tripped', async () => {
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(BASE_SUMMARY as any)
    const w = mountPage()
    await flushPromises()
    const resetBtn = w.findAll('.row-actions button')[2]
    expect((resetBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('circuit-reset action fires when the circuit is tripped', async () => {
    const summary = {
      ...BASE_SUMMARY,
      panels: {
        ...BASE_SUMMARY.panels,
        platform_health: panel({
          blogger: {
            platform: 'blogger', last_success_at: null, last_failure_at: null,
            last_error_msg: null, consecutive_failures: 5, circuit_tripped: true,
            circuit_tripped_at: '2026-07-06T00:00:00Z', paused: false,
          },
        }),
      },
    }
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(summary as any)
    vi.mocked(api.circuitResetPlatform).mockResolvedValue({ ok: true, platform: 'blogger' })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    const resetBtn = w.findAll('.row-actions button')[2]
    expect((resetBtn.element as HTMLButtonElement).disabled).toBe(false)
    await resetBtn.trigger('click')
    await flushPromises()

    expect(api.circuitResetPlatform).toHaveBeenCalledWith('blogger')
    expect(notify.toasts.some((t) => t.message.includes('已重置'))).toBe(true)
  })

  it('renders the secondary panels behind a details/summary toggle', async () => {
    const summary = {
      ...BASE_SUMMARY,
      panels: {
        ...BASE_SUMMARY.panels,
        decay_alerts: panel([{ target_url: 'https://a.com', lost_count: 2, ts: '2026-07-01' }]),
      },
    }
    vi.mocked(api.fetchHealthSummary).mockResolvedValue(summary as any)
    const w = mountPage()
    await flushPromises()

    expect(w.find('.health__more').exists()).toBe(true)
    expect(w.text()).toContain('更多指标')
  })
})
