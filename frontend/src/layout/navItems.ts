// Nav model for the console shell — Plan 2026-06-18-002 U4.
//
// Migration complete as of Sprint B1 (2026-07-02): all navItems carry `to`
// (isMigrated: true) — every entry routes in-SPA via RouterLink, no
// full-page reload. The `href` field is kept on the NavItem type as an
// escape hatch for any future not-yet-migrated page, but nothing in
// NAV_ITEMS currently uses it. IA groups outlive the migration:
// Pipeline / Monitoring / Operations / Config.
//
// Plan 2026-07-06-005 W8 (R8): every item now also carries `icon` — a name
// registered in components/Icon.vue's ICONS table (bootstrap-icons v1.11.0
// path data, offline). Chosen to match the legacy Jinja sidebar's own
// `bi-*` icon per nav_item() call in webui_app/templates/base.html wherever
// that page has an equivalent entry (keep-alive → shield-check, monitor
// aggregator → grid-1x2, etc.) so the two shells read as the same product;
// error-reports/PR-queue got a best-fit icon instead (bug/people — 2026-07-07
// follow-up, more semantically fitting than the icons originally picked).
// SPA-only items (history/drafts/
// optimization-status/equity-ledger, which the legacy sidebar doesn't list at
// all) got a best-fit icon of their own. `showAnomalyBadge` marks the single
// item (the monitor aggregator, now the homepage) that SideNav.vue attaches
// the anomaly-count badge to — parity with the legacy sidebar's
// `badge_id='navAnomalyBadge'` on its own '/monitor-hub' entry.

export type NavGroup = 'pipeline' | 'monitoring' | 'operations' | 'config'

export interface NavItem {
  label: string
  group: NavGroup
  icon: string // components/Icon.vue registered name
  to?: string // migrated: in-SPA route
  href?: string // legacy: Jinja page (full nav)
  showAnomalyBadge?: boolean // SideNav.vue: render the aggregator anomaly-count badge here
}

export const GROUP_LABELS: Record<NavGroup, string> = {
  pipeline: '核心',
  monitoring: '监控',
  operations: '运营',
  config: '配置',
}

export const NAV_ITEMS: NavItem[] = [
  // Migrated (in-SPA).
  { label: '发布工作台', group: 'pipeline', icon: 'send', to: '/publish' }, // moved off '/' in Plan 2026-07-06-004 Unit 4
  {
    label: '监控聚合',
    group: 'monitoring',
    icon: 'grid-1x2', // matches legacy nav_item('/monitor-hub', …, 'bi-grid-1x2', badge_id='navAnomalyBadge')
    to: '/', // promoted to homepage in Plan 2026-07-06-004 Unit 4 (was '/monitor', migrated in U6)
    showAnomalyBadge: true,
  },
  { label: '历史', group: 'operations', icon: 'clock-history', to: '/history' }, // migrated in U7
  { label: '草稿', group: 'operations', icon: 'file-earmark-text', to: '/drafts' }, // migrated in U7
  { label: '站点', group: 'config', icon: 'globe2', to: '/sites' }, // migrated in U7
  { label: '排程', group: 'operations', icon: 'calendar-week', to: '/schedule' }, // migrated in U7
  { label: '批量', group: 'operations', icon: 'stack', to: '/batch-campaign' }, // migrated in U7
  { label: '设置', group: 'config', icon: 'gear', to: '/settings' }, // migrated in U7 §5 — SPA settings page now complete (was legacy href)
  { label: 'PR 机会', group: 'operations', icon: 'people', to: '/pr-queue' }, // migrated in P12 A1
  { label: '存活率', group: 'monitoring', icon: 'graph-up', to: '/survival' }, // migrated in P13 B1
  { label: '优化权重', group: 'monitoring', icon: 'graph-up-arrow', to: '/optimization-status' }, // migrated in P13 B2
  { label: '权益总账', group: 'monitoring', icon: 'wallet2', to: '/equity-ledger' }, // migrated in P14 B1
  { label: '保活看板', group: 'monitoring', icon: 'shield-check', to: '/keep-alive' }, // migrated in P15 A1
  { label: '发布健康看板', group: 'monitoring', icon: 'heart-pulse', to: '/health' }, // migrated in Plan 2026-07-02-001 U6
  // Plan 2026-07-01-002 Unit 8 — deliberately 'operations', NOT 'monitoring':
  // that group is exclusively ops-health dashboards (survival rate,
  // optimization weight, equity ledger, keep-alive); mixing in error-reporting
  // there would recreate the naming/routing confusion this unit's own design
  // decision was meant to avoid (see the plan's Unit 8 Files note).
  //
  // Plan 2026-07-06-005 W8: kept IN the nav (not hidden as "SPA-only"). It IS
  // SPA-only — the legacy Jinja sidebar has no equivalent entry — but it's a
  // primary, frequently-revisited destination (the "查看报告" deep-links from
  // W10 land here), not a transient/one-off utility page. Omitting it would
  // make the SPA shell weaker than a plain "everything reachable" nav for no
  // real benefit, so the SPA-only-ness alone isn't treated as a reason to hide
  // it — see SideNav.vue's module docstring for the general policy this
  // follows.
  { label: '错误报告', group: 'operations', icon: 'bug', to: '/error-reports' },
  // Operations task center (Plan 2026-07-09 operation-progress P3). SPA-only,
  // same inclusion rationale as 错误报告 above: a primary, repeatedly-revisited
  // destination (running publish/chain tasks live here), not a one-off utility.
  { label: '任务中心', group: 'operations', icon: 'activity', to: '/operations' },

]

export const GROUP_ORDER: NavGroup[] = ['pipeline', 'monitoring', 'operations', 'config']

export function itemsByGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((i) => i.group === group)
}

export function isMigrated(item: NavItem): boolean {
  return item.to !== undefined
}
