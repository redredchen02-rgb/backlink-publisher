// Nav model for the console shell — Plan 2026-06-18-002 U4.
//
// Migration complete as of Sprint B1 (2026-07-02): all 13 navItems carry
// `to` (isMigrated: true) — every entry routes in-SPA via RouterLink, no
// full-page reload. The `href` field is kept on the NavItem type as an
// escape hatch for any future not-yet-migrated page, but nothing in
// NAV_ITEMS currently uses it. IA groups outlive the migration:
// Pipeline / Monitoring / Operations / Config.

export type NavGroup = 'pipeline' | 'monitoring' | 'operations' | 'config'

export interface NavItem {
  label: string
  group: NavGroup
  to?: string // migrated: in-SPA route
  href?: string // legacy: Jinja page (full nav)
}

export const GROUP_LABELS: Record<NavGroup, string> = {
  pipeline: '核心',
  monitoring: '监控',
  operations: '运营',
  config: '配置',
}

export const NAV_ITEMS: NavItem[] = [
  // Migrated (in-SPA).
  { label: '发布工作台', group: 'pipeline', to: '/' },
  { label: '监控聚合', group: 'monitoring', to: '/monitor' }, // migrated in U6
  { label: '历史', group: 'operations', to: '/history' }, // migrated in U7
  { label: '草稿', group: 'operations', to: '/drafts' }, // migrated in U7
  { label: '站点', group: 'config', to: '/sites' }, // migrated in U7
  { label: '排程', group: 'operations', to: '/schedule' }, // migrated in U7
  { label: '批量', group: 'operations', to: '/batch-campaign' }, // migrated in U7
  { label: '设置', group: 'config', to: '/settings' }, // migrated in U7 §5 — SPA settings page now complete (was legacy href)
  { label: 'PR 机会', group: 'operations', to: '/pr-queue' }, // migrated in P12 A1
  { label: '存活率', group: 'monitoring', to: '/survival' }, // migrated in P13 B1
  { label: '优化权重', group: 'monitoring', to: '/optimization-status' }, // migrated in P13 B2
  { label: '权益总账', group: 'monitoring', to: '/equity-ledger' }, // migrated in P14 B1
  { label: '保活看板', group: 'monitoring', to: '/keep-alive' }, // migrated in P15 A1
  // Plan 2026-07-01-002 Unit 8 — deliberately 'operations', NOT 'monitoring':
  // that group is exclusively ops-health dashboards (survival rate,
  // optimization weight, equity ledger, keep-alive); mixing in error-reporting
  // there would recreate the naming/routing confusion this unit's own design
  // decision was meant to avoid (see the plan's Unit 8 Files note).
  { label: '错误报告', group: 'operations', to: '/error-reports' },

]

export const GROUP_ORDER: NavGroup[] = ['pipeline', 'monitoring', 'operations', 'config']

export function itemsByGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((i) => i.group === group)
}

export function isMigrated(item: NavItem): boolean {
  return item.to !== undefined
}
