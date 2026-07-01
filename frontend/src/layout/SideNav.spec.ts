import { describe, expect, it } from 'vitest'
import { RouterLinkStub, mount } from '@vue/test-utils'
import SideNav from './SideNav.vue'
import { NAV_ITEMS, isMigrated } from './navItems'

describe('SideNav dual-stack wayfinding', () => {
  it('renders RouterLink for migrated pages and <a href> (with a leave-mark) for legacy', () => {
    const w = mount(SideNav, { global: { stubs: { RouterLink: RouterLinkStub } } })

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
    const w = mount(SideNav, { global: { stubs: { RouterLink: RouterLinkStub } } })

    const brand = w.findComponent(RouterLinkStub)
    expect(brand.exists()).toBe(true)
    expect(brand.classes()).toContain('sidenav__brand')
    expect(brand.props('to')).toBe('/')
  })
})
