import { describe, expect, it, vi } from 'vitest'
import { RouterLinkStub, mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import SideNav from './SideNav.vue'
import { NAV_ITEMS, isMigrated } from './navItems'

// Plan 2026-07-06-005 W8 (R8): SideNav now sources the anomaly badge from
// monitor.ts's monitorSummary() (the same aggregator feed
// MonitorDashboard.vue polls). Mocked here per-test so happy/error paths are
// deterministic and don't depend on network/fetch behaviour in jsdom — same
// convention as MonitorDashboard.spec.ts's own api/monitor mock.
const monitorSummaryMock = vi.fn()
vi.mock('../api/monitor', async () => {
  const actual = await vi.importActual<typeof import('../api/monitor')>('../api/monitor')
  return {
    ...actual,
    monitorSummary: () => monitorSummaryMock(),
  }
})

function mountSideNav() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SideNav, {
    global: {
      stubs: { RouterLink: RouterLinkStub },
      plugins: [[VueQueryPlugin, { queryClient }]],
    },
  })
}

describe('SideNav dual-stack wayfinding', () => {
  it('renders RouterLink for migrated pages and <a href> (with a leave-mark) for legacy', () => {
    monitorSummaryMock.mockResolvedValue({ cards: [], anomaly_count: 0, degraded: false })
    const w = mountSideNav()

    const migratedCount = NAV_ITEMS.filter(isMigrated).length
    // Scope to nav-item links only — the brand region is also a RouterLink
    // (returns to home) but is not one of the nav items being counted here.
    const navLinkStubs = w
      .findAllComponents(RouterLinkStub)
      .filter((c) => c.classes().includes('sidenav__link'))
    expect(navLinkStubs.length).toBe(migratedCount)

    const legacyLinks = w.findAll('a.sidenav__link--legacy')
    expect(legacyLinks.length).toBe(NAV_ITEMS.length - migratedCount)
    if (legacyLinks.length > 0) {
      expect(legacyLinks[0].attributes('href')).toMatch(/^\//)
      // The operator must see that a legacy click leaves the new console.
      expect(w.text()).toContain('↪')
    }
  })

  it('renders the brand region as a RouterLink to the home/workbench route', () => {
    monitorSummaryMock.mockResolvedValue({ cards: [], anomaly_count: 0, degraded: false })
    const w = mountSideNav()

    const brand = w.findComponent(RouterLinkStub)
    expect(brand.exists()).toBe(true)
    expect(brand.classes()).toContain('sidenav__brand')
    expect(brand.props('to')).toBe('/')
  })

  it('renders a decorative (aria-hidden) icon for every nav item', () => {
    monitorSummaryMock.mockResolvedValue({ cards: [], anomaly_count: 0, degraded: false })
    const w = mountSideNav()

    const icons = w.findAll('svg.app-icon')
    // One per nav item, plus none extra: every NavItem carries an `icon`.
    expect(icons.length).toBe(NAV_ITEMS.length)
    for (const icon of icons) {
      expect(icon.attributes('aria-hidden')).toBe('true')
      expect(icon.attributes('role')).toBeUndefined()
    }
  })
})

describe('SideNav anomaly badge (W8)', () => {
  it('happy path: shows the aggregator anomaly_count on the monitor item with sr-only context', async () => {
    monitorSummaryMock.mockResolvedValue({ cards: [], anomaly_count: 3, degraded: false })
    const w = mountSideNav()
    await flushPromises()

    const badge = w.get('.sidenav__badge')
    expect(badge.text()).toContain('3')
    expect(badge.text()).toContain('项异常')
    expect(badge.find('.visually-hidden').exists()).toBe(true)
  })

  it('zero anomalies: badge does not render at all (not just visually hidden)', async () => {
    monitorSummaryMock.mockResolvedValue({ cards: [], anomaly_count: 0, degraded: false })
    const w = mountSideNav()
    await flushPromises()

    expect(w.find('.sidenav__badge').exists()).toBe(false)
  })

  it('error path: aggregator failure hides the badge silently and does not block nav rendering', async () => {
    monitorSummaryMock.mockRejectedValue(new Error('network down'))
    const w = mountSideNav()
    await flushPromises()

    // Nav still renders every item — a badge-fetch failure must never block
    // navigation rendering.
    const migratedCount = NAV_ITEMS.filter(isMigrated).length
    expect(w.findAllComponents(RouterLinkStub).filter((c) => c.classes().includes('sidenav__link')).length).toBe(
      migratedCount,
    )
    // No badge, no error text/toast leaked into the nav's own markup.
    expect(w.find('.sidenav__badge').exists()).toBe(false)
  })
})
