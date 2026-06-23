// Plan 2026-06-18-002 U3 — client router.
// Base '/app/' matches the Flask catch-all that serves the SPA; deep-link
// refreshes on /app/<route> are served index.html by Flask, then resolved here.
import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    {
      // The pipeline group's primary page IS the publish workbench (U5);
      // navItems maps 发布工作台 → '/'.
      path: '/',
      name: 'publish',
      component: () => import('../pages/Publish/PublishWorkbench.vue'),
    },
    {
      // Monitoring aggregate dashboard (U6); navItems maps 监控聚合 → '/monitor'.
      path: '/monitor',
      name: 'monitor',
      component: () => import('../pages/Monitor/MonitorDashboard.vue'),
    },
    {
      // Publish history (U7); navItems maps 历史 → '/history'.
      path: '/history',
      name: 'history',
      component: () => import('../pages/History/HistoryPage.vue'),
    },
    {
      // Draft queue (U7); navItems maps 草稿 → '/drafts'.
      path: '/drafts',
      name: 'drafts',
      component: () => import('../pages/Drafts/DraftsPage.vue'),
    },
    {
      // Work-themed site config (U7); navItems maps 站点 → '/sites'.
      path: '/sites',
      name: 'sites',
      component: () => import('../pages/Sites/SitesPage.vue'),
    },
    {
      // Scheduled-drafts view (U7); navItems maps 排程 → '/schedule'.
      path: '/schedule',
      name: 'schedule',
      component: () => import('../pages/Schedule/SchedulePage.vue'),
    },
    {
      // Batch-campaign creation (U7); navItems maps 批量 → '/batch-campaign'.
      path: '/batch-campaign',
      name: 'batch-campaign',
      component: () => import('../pages/BatchCampaign/BatchCampaignPage.vue'),
    },
    {
      // Settings (U7) — built section-by-section, complete as of §5. The console
      // nav now points here (navItems `to`), making this the PRIMARY settings
      // entry; the legacy Jinja /settings page survives only until U8 retirement.
      path: '/settings',
      name: 'settings',
      component: () => import('../pages/Settings/SettingsPage.vue'),
    },
    {
      // Equity-ledger detail page (U8 sub-knife 9); navItems maps 权益账本 → '/equity-ledger'.
      path: '/equity-ledger',
      name: 'equity-ledger',
      component: () => import('../pages/Monitor/EquityLedgerPage.vue'),
    },
    {
      // Keep-alive monitoring page (U8 sub-knife 10); navItems maps 保活 → '/keep-alive'.
      path: '/keep-alive',
      name: 'keep-alive',
      component: () => import('../pages/Monitor/KeepAlivePage.vue'),
    },
    {
      // Health dashboard (U8 sub-knife 11); navItems maps 健康 → '/health'.
      path: '/health',
      name: 'health',
      component: () => import('../pages/Monitor/HealthPage.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../pages/NotFound.vue'),
    },
  ],
})

// a11y: SPA navigations don't move focus. After each route change, move focus
// to the main region so screen-reader users land on the new page content.
router.afterEach(() => {
  requestAnimationFrame(() => {
    const main = document.getElementById('main')
    if (main) main.focus()
  })
})

