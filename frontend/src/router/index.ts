// Plan 2026-06-18-002 U3 — client router.
// Base '/app/' matches the Flask catch-all that serves the SPA; deep-link
// refreshes on /app/<route> are served index.html by Flask, then resolved here.
import { createRouter, createWebHistory } from 'vue-router'
import { reportRouterError } from '../lib/errorCapture'

export const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    {
      // Homepage swap (Plan 2026-07-06-004 Unit 4): the Monitor aggregate
      // dashboard is now the SPA's landing page; navItems maps 监控聚合 → '/'.
      // PublishWorkbench (formerly here) moved to '/publish' below.
      path: '/',
      name: 'monitor',
      component: () => import('../pages/Monitor/MonitorDashboard.vue'),
    },
    {
      // Publish workbench (Plan 2026-07-06-004 Unit 4, was at '/' pre-swap);
      // navItems maps 发布工作台 → '/publish'. Reached via TopBar's persistent
      // "新建发布" button (router.push, not a floating panel — K2: needs
      // bookmark/back-button/refresh support) or the sidenav.
      path: '/publish',
      name: 'publish',
      component: () => import('../pages/Publish/PublishWorkbench.vue'),
    },
    {
      // Kept as a harmless alias to the same component as '/' — no navItem
      // links here anymore post-swap (Unit 4), but left in place rather than
      // removed since nothing in this unit's scope required deleting it and
      // no other code path references it.
      path: '/monitor',
      name: 'monitor-alias',
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
      // PR opportunity queue (P12 A1 — migrated from Jinja).
      path: '/pr-queue',
      name: 'pr-queue',
      component: () => import('../pages/PrQueue/PrQueuePage.vue'),
    },
    {
      // Survival dashboard (P13 B1 — migrated from Jinja).
      path: '/survival',
      name: 'survival',
      component: () => import('../pages/SurvivalDashboard/SurvivalDashboardPage.vue'),
    },
    {
      // Optimization status (P13 B2 — migrated from Jinja).
      path: '/optimization-status',
      name: 'optimization-status',
      component: () => import('../pages/OptimizationStatus/OptimizationStatusPage.vue'),
    },
    {
      // Equity ledger (P14 B1 — migrated from Jinja).
      path: '/equity-ledger',
      name: 'equity-ledger',
      component: () => import('../pages/EquityLedger/EquityLedgerPage.vue'),
    },
    {
      // Keep-alive dashboard (P15 A1 — migrated from Jinja).
      path: '/keep-alive',
      name: 'keep-alive',
      component: () => import('../pages/KeepAlive/KeepAlivePage.vue'),
    },
    {
      // Campaign progress (P13 B3 — migrated from Jinja).
      path: '/campaign/:campaignId',
      name: 'campaign-progress',
      component: () => import('../pages/CampaignProgress/CampaignProgressPage.vue'),
    },
    {
      // Error-reports dashboard (Plan 2026-07-01-002 Unit 8); navItems maps
      // 错误报告 → '/error-reports'. SPA-only — no legacy Jinja equivalent.
      path: '/error-reports',
      name: 'error-reports',
      component: () => import('../pages/ErrorReports/ErrorReportsPage.vue'),
    },
    {
      // Error-report detail drill-down (Unit 8) — deliberately its own
      // sub-route rather than a modal/drawer, see ErrorReportDetailPage.vue's
      // header comment for why.
      path: '/error-reports/:id',
      name: 'error-report-detail',
      component: () => import('../pages/ErrorReports/ErrorReportDetailPage.vue'),
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

// Plan 2026-07-01-002 Unit 6, hook 3 — navigation-guard / async-component
// resolution failures are cancelled by the Router before they ever reach a
// render/lifecycle call site, so app.config.errorHandler never sees them;
// this is the only interception point that catches this failure surface.
router.onError((error) => {
  reportRouterError(error)
})

