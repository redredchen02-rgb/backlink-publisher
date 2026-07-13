// Nav model for the console shell — Plan 2026-06-18-002 U4.
//
// Migration complete as of Sprint B1 (2026-07-02): all navItems carry `to`
// (isMigrated: true) — every entry routes in-SPA via RouterLink, no
// full-page reload. The `href` field is kept on the NavItem type as an
// escape hatch for any future not-yet-migrated page, but nothing in
// NAV_ITEMS currently uses it. IA groups outlive the migration:
// Pipeline / Monitoring / Operations / Config.

export type NavGroup = 'pipeline' | 'monitoring' | 'operations' | 'config'

export interface NavItem {
  label: string
  group: NavGroup
  icon: string // bootstrap-icons name, consumed by Icon.vue (W7)
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
  { label: '发布工作台', group: 'pipeline', icon: 'send', to: '/publish' },
  { label: '监控聚合', group: 'monitoring', icon: 'grid-1x2-fill', to: '/' },
  { label: '历史', group: 'operations', icon: 'clock-history', to: '/history' },
  { label: '草稿', group: 'operations', icon: 'file-earmark-text', to: '/drafts' },
  { label: '站点', group: 'config', icon: 'globe2', to: '/sites' },
  { label: '排程', group: 'operations', icon: 'calendar-event', to: '/schedule' },
  { label: '批量', group: 'operations', icon: 'layers', to: '/batch-campaign' },
  { label: '设置', group: 'config', icon: 'gear', to: '/settings' },
  { label: 'PR 机会', group: 'operations', icon: 'people', to: '/pr-queue' },
  { label: '存活率', group: 'monitoring', icon: 'graph-up-arrow', to: '/survival' },
  { label: '优化权重', group: 'monitoring', icon: 'sliders', to: '/optimization-status' },
  { label: '权益总账', group: 'monitoring', icon: 'wallet2', to: '/equity-ledger' },
  { label: '保活看板', group: 'monitoring', icon: 'activity', to: '/keep-alive' },
  { label: '发布健康看板', group: 'monitoring', icon: 'heart-pulse', to: '/health' },
  // Plan 2026-07-01-002 Unit 8 — deliberately 'operations', NOT 'monitoring':
  // that group is exclusively ops-health dashboards (survival rate,
  // optimization weight, equity ledger, keep-alive); mixing in error-reporting
  // there would recreate the naming/routing confusion this unit's own design
  // decision was meant to avoid (see the plan's Unit 8 Files note).
  { label: '错误报告', group: 'operations', icon: 'bug', to: '/error-reports' },

]

export const GROUP_ORDER: NavGroup[] = ['pipeline', 'monitoring', 'operations', 'config']

export function itemsByGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((i) => i.group === group)
}

export function isMigrated(item: NavItem): boolean {
  return item.to !== undefined
}
