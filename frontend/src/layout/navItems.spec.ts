import { describe, expect, it } from 'vitest'
import { GROUP_ORDER, NAV_ITEMS, isMigrated, itemsByGroup } from './navItems'

describe('navItems dual-stack model', () => {
  it('migrated items carry an in-SPA route; legacy items carry an absolute href', () => {
    const migrated = NAV_ITEMS.filter(isMigrated)
    expect(migrated.length).toBeGreaterThanOrEqual(1)
    expect(migrated[0].to).toBe('/')
    for (const i of NAV_ITEMS.filter((x) => !isMigrated(x))) {
      expect(i.href).toMatch(/^\//)
      expect(i.to).toBeUndefined()
    }
  })

  it('groups partition every item exactly once', () => {
    const total = GROUP_ORDER.reduce((n, g) => n + itemsByGroup(g).length, 0)
    expect(total).toBe(NAV_ITEMS.length)
  })
})
