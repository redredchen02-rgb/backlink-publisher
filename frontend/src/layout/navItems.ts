// Nav model for the console shell — Plan 2026-06-18-002 U4.
//
// Dual-stack wayfinding (design-lens): during the strangler-fig migration the
// sidebar lists BOTH migrated SPA pages and not-yet-migrated legacy Jinja pages.
// - `to`   → an in-SPA route (RouterLink, no reload).
// - `href` → a legacy Jinja URL (full navigation OUT of the SPA; SPA-resident
//            state like toasts/polling is lost by design, theme persists via the
//            data-theme attribute the legacy pages also honour).
// Legacy items are visually marked so the operator knows a click leaves the new
// console. IA groups outlive the migration: Pipeline / Monitoring / Operations / Config.

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

  // Legacy Jinja pages — full navigation out of the SPA until migrated.
  { label: '健康', group: 'monitoring', href: '/ce:health' },
  { label: '权益账本', group: 'monitoring', href: '/ce:equity-ledger' },
  { label: '保活', group: 'monitoring', href: '/ce:keep-alive' },

  { label: '设置', group: 'config', href: '/settings' },
]

export const GROUP_ORDER: NavGroup[] = ['pipeline', 'monitoring', 'operations', 'config']

export function itemsByGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((i) => i.group === group)
}

export function isMigrated(item: NavItem): boolean {
  return item.to !== undefined
}
