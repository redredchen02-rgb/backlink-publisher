import { describe, expect, it } from 'vitest'
import { RouterLinkStub, mount } from '@vue/test-utils'
import SideNav from './SideNav.vue'
import { NAV_ITEMS, isMigrated } from './navItems'

describe('SideNav dual-stack wayfinding', () => {
  it('renders RouterLink for migrated pages and <a href> (with a leave-mark) for legacy', () => {
    const w = mount(SideNav, { global: { stubs: { RouterLink: RouterLinkStub } } })

    const migratedCount = NAV_ITEMS.filter(isMigrated).length
    expect(w.findAllComponents(RouterLinkStub).length).toBe(migratedCount)

    const legacyLinks = w.findAll('a.sidenav__link--legacy')
    expect(legacyLinks.length).toBe(NAV_ITEMS.length - migratedCount)
    expect(legacyLinks[0].attributes('href')).toMatch(/^\//)
    // The operator must see that a legacy click leaves the new console.
    expect(w.text()).toContain('↪')
  })
})
