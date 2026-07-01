// Integration coverage for the shared sidenav-drawer wiring — code review
// follow-up to Plan 2026-07-01-001 U4 (gap flagged independently by four
// reviewers: testing, frontend-races, maintainability, kieran-typescript).
//
// SideNav.spec.ts and (previously) no TopBar test each exercise their own
// component in isolation, falling back to a private `useSidenavDrawer()`
// instance via `inject(..., factory, true)` when no ancestor provides one.
// That fallback means a bug in the real AppShell-level provide()/inject()
// wiring between TopBar (trigger) and SideNav (drawer body) could go
// undetected by either component's own spec. This test mounts both
// components together as siblings with ONE real shared drawer instance
// provided via SIDENAV_DRAWER_KEY — the same wiring AppShell.vue does — and
// asserts the toggle/close/nav-link-close behaviour works end-to-end through
// that real inject(), not just through the composable called directly.
//
// Mounting the full AppShell.vue was judged too heavy for this assertion: it
// additionally pulls in RouterView (real route components + async chunks)
// and Toast (notifications store); none of that is relevant to proving the
// drawer wiring, so SideNav + TopBar are mounted directly as siblings
// instead (mounting approach explicitly sanctioned by the review finding).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

// TopBar fetches /app-config via useQuery — mocked so the test doesn't
// depend on network/fetch behaviour in jsdom (mirrors MonitorDashboard.spec.ts's
// api-mocking convention: mock path is relative to *this* file, same as
// TopBar.vue's own import path since both live in src/layout).
vi.mock('../api/client', () => ({
  getJson: vi.fn().mockResolvedValue({
    lite_edition: false,
    llm_configured: true,
    pro_status: { configured: true },
  }),
}))

import SideNav from './SideNav.vue'
import TopBar from './TopBar.vue'
import { SIDENAV_DRAWER_KEY, useSidenavDrawer } from '../composables/useSidenavDrawer'

/** Mounts TopBar (hamburger trigger) and SideNav (drawer body) as real
 *  siblings sharing one drawer instance, the same relationship AppShell.vue
 *  wires via provide()/inject() — without pulling in RouterView/Toast. */
const TestShell = defineComponent({
  components: { TopBar, SideNav },
  setup() {
    return () => h('div', [h(TopBar), h(SideNav)])
  },
})

function mountShell(sharedDrawer: ReturnType<typeof useSidenavDrawer>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(TestShell, {
    global: {
      stubs: { RouterLink: RouterLinkStub },
      provide: { [SIDENAV_DRAWER_KEY as unknown as symbol]: sharedDrawer },
      plugins: [createPinia(), [VueQueryPlugin, { queryClient }]],
    },
  })
}

describe('SideNav + TopBar share one drawer instance (real provide/inject wiring)', () => {
  let sharedDrawer: ReturnType<typeof useSidenavDrawer>

  beforeEach(() => {
    setActivePinia(createPinia())
    sharedDrawer = useSidenavDrawer()
  })

  afterEach(() => {
    if (sharedDrawer.isOpen.value) sharedDrawer.close()
  })

  it('clicking the hamburger opens the drawer rendered by the sibling SideNav', async () => {
    const w = mountShell(sharedDrawer)
    const nav = w.get('#sidenav-drawer')

    expect(nav.classes()).not.toContain('sidenav--open')
    expect(nav.attributes('role')).toBeUndefined()
    expect(nav.attributes('aria-modal')).toBeUndefined()

    await w.get('button.topbar__hamburger').trigger('click')

    expect(sharedDrawer.isOpen.value).toBe(true)
    expect(nav.classes()).toContain('sidenav--open')
    expect(nav.attributes('role')).toBe('dialog')
    expect(nav.attributes('aria-modal')).toBe('true')
  })

  it('closes again via the shared instance (mirrors AppShell overlay backdrop @click="drawer.close()")', async () => {
    const w = mountShell(sharedDrawer)
    const nav = w.get('#sidenav-drawer')

    await w.get('button.topbar__hamburger').trigger('click')
    expect(sharedDrawer.isOpen.value).toBe(true)

    sharedDrawer.close()
    await w.vm.$nextTick()

    expect(sharedDrawer.isOpen.value).toBe(false)
    expect(nav.classes()).not.toContain('sidenav--open')
  })

  it('clicking a nav link inside SideNav while open closes the drawer end-to-end (Fix 1)', async () => {
    const w = mountShell(sharedDrawer)
    const nav = w.get('#sidenav-drawer')

    await w.get('button.topbar__hamburger').trigger('click')
    expect(sharedDrawer.isOpen.value).toBe(true)
    expect(nav.classes()).toContain('sidenav--open')

    const firstNavLink = w.get('a.sidenav__link')
    await firstNavLink.trigger('click')

    expect(sharedDrawer.isOpen.value).toBe(false)
    expect(nav.classes()).not.toContain('sidenav--open')
  })
})
