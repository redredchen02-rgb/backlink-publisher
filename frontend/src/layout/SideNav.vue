<script setup lang="ts">
// Console sidebar — Plan 2026-06-18-002 U4.
// Groups outlive the migration (Pipeline/Monitoring/Operations/Config). Migrated
// items are RouterLinks (in-SPA, active-state); legacy items are <a> that fully
// navigate out of the SPA and are marked with '↪' so the operator knows.
//
// Plan 2026-07-01-001 U4: below the 960px breakpoint this <nav> becomes an
// off-canvas drawer (transform, not v-if — it must stay mounted so
// useSidenavDrawer's drawerEl ref, focus trap, and Escape/overlay-close all
// keep working). Above the breakpoint nothing here changes from today.
// `role="dialog"`/`aria-modal` are applied only while the drawer is actually
// open (which auto-closes on resize past the breakpoint), so wide-screen
// a11y semantics are unchanged. Falls back to a standalone drawer instance
// when mounted without an AppShell ancestor (e.g. SideNav.spec.ts), so
// existing tests are unaffected.
//
// Plan 2026-07-06-005 W8 (R8): SPA-only-page nav policy — a nav item that
// has no legacy Jinja equivalent (currently only '错误报告' /error-reports)
// is NOT hidden merely for being SPA-only. It stays in the nav when it's a
// primary, repeatedly-revisited destination; the bar for exclusion is
// "transient/one-off utility", not "doesn't exist in the old shell" (the old
// shell is the one being upgraded away from, not the target to shrink to).
// See navItems.ts's own comment on that entry for the concrete call.
//
// Icon + anomaly-badge (also W8): every NavItem now carries an `icon` (see
// navItems.ts); rendered here via the shared Icon.vue component in its
// default decorative mode (aria-hidden="true" — the text label already names
// the destination, so the icon carries no independent a11y information).
// The anomaly badge is data-driven from the SAME aggregator feed the legacy
// sidebar's static/js/ui/nav-badge.js used (`/api/monitor-hub`, versioned
// here as monitor.ts's monitorSummary() → `/api/v1/monitor/summary` — see
// that file's docstring: same `_collect_subsystem_status` +
// `_build_anomaly_cards`, one source of truth, so this is not a new data
// source). Fail-open by construction: `anomalyCount` below folds a query
// error to 0, which both hides the badge (matching legacy's "leave the badge
// hidden on any error") and never throws into the render — nav renders
// unconditionally either way. TanStack Query's own QueryCache.onError hook
// (main.ts) still files a silent telemetry report on failure; this component
// deliberately does not additionally push a notifications-store toast for a
// background badge fetch.
import { computed, inject, onMounted, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  GROUP_LABELS,
  GROUP_ORDER,
  isMigrated,
  itemsByGroup,
  type NavItem,
} from './navItems'
import { SIDENAV_DRAWER_KEY, useSidenavDrawer } from '../composables/useSidenavDrawer'
import Icon from '../components/Icon.vue'
import { monitorSummary, MONITOR_SUMMARY_QUERY_KEY } from '../api/monitor'

const drawer = inject(SIDENAV_DRAWER_KEY, () => useSidenavDrawer(), true)
const navEl = ref<HTMLElement | null>(null)
onMounted(() => {
  drawer.drawerEl.value = navEl.value
})

// Fix (code review, Plan 2026-07-01-001 U4 follow-up): clicking a nav link
// while the drawer is open (narrow viewport) must close it — otherwise the
// overlay/scroll-lock/focus-trap stay engaged over the newly-routed page.
// close() is a safe no-op when already closed, so this doesn't need to
// distinguish link clicks from other clicks inside the nav.
function onNavClick() {
  if (drawer.isOpen.value) drawer.close()
}

// Deliberately no explicit `staleTime`/`refetchInterval` override here — this
// inherits main.ts's site-wide QueryClient default (staleTime: 30_000,
// refetchOnWindowFocus: true; Plan 2026-07-06-005 W1/D15), which is already
// lower-frequency than MonitorDashboard.vue's own explicit 15s poll on the
// same query key. When that page is mounted its poll keeps this shared cache
// entry warm "for free"; elsewhere the badge only refetches on
// mount/focus/staleness, matching the "low-frequency" intent without adding
// a second timer.
const badgeQuery = useQuery({
  queryKey: MONITOR_SUMMARY_QUERY_KEY,
  queryFn: monitorSummary,
})

// Fail-open: any aggregator error (network failure, non-2xx, thrown parse
// error) folds to 0 — hidden badge, no exception surfaces into the template.
const anomalyCount = computed(() => {
  if (badgeQuery.isError.value) return 0
  return badgeQuery.data.value?.anomaly_count ?? 0
})

function showBadge(item: NavItem): boolean {
  return Boolean(item.showAnomalyBadge) && anomalyCount.value > 0
}
</script>

<template>
  <nav
    id="sidenav-drawer"
    ref="navEl"
    class="sidenav"
    :class="{ 'sidenav--open': drawer.isOpen.value }"
    aria-label="主导航"
    tabindex="-1"
    :role="drawer.isOpen.value ? 'dialog' : undefined"
    :aria-modal="drawer.isOpen.value ? 'true' : undefined"
    @click="onNavClick"
  >
    <RouterLink to="/" class="sidenav__brand" aria-label="返回操作首页">控台</RouterLink>
    <template v-for="group in GROUP_ORDER" :key="group">
      <div class="sidenav__group-label">{{ GROUP_LABELS[group] }}</div>
      <ul class="sidenav__list">
        <li v-for="item in itemsByGroup(group)" :key="item.label">
          <RouterLink
            v-if="isMigrated(item)"
            :to="item.to!"
            class="sidenav__link"
            active-class="is-active"
            exact-active-class="is-active"
            aria-current-value="page"
          >
            <Icon :name="item.icon" class="sidenav__icon" />
            <span class="sidenav__label">{{ item.label }}</span>
            <span v-if="showBadge(item)" class="sidenav__badge">
              {{ anomalyCount }}
              <span class="visually-hidden">项异常</span>
            </span>
          </RouterLink>
          <a
            v-else
            :href="item.href"
            class="sidenav__link sidenav__link--legacy"
            :title="`旧界面：点击将离开新控台（${item.href}）`"
          >
            <Icon :name="item.icon" class="sidenav__icon" />
            <span class="sidenav__label">{{ item.label }}<span class="sidenav__legacy-mark" aria-hidden="true"> ↪</span></span>
          </a>
        </li>
      </ul>
    </template>
  </nav>
</template>

<style scoped>
.sidenav {
  width: 13rem;
  flex-shrink: 0;
  padding: 0.75rem;
  border-right: 1px solid var(--border);
  background: var(--surface-raised);
  overflow-y: auto;
}
.sidenav__brand {
  font-weight: var(--font-weight-bold);
  padding: 0.25rem 0.5rem 0.75rem;
  color: var(--text-primary);
  text-decoration: none;
}
.sidenav__group-label {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  padding: 0.75rem 0.5rem 0.25rem;
}
.sidenav__list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sidenav__link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: var(--control-pad-y) var(--control-pad-x);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  text-decoration: none;
  font-size: var(--text-base);
}
.sidenav__link:hover {
  background: var(--surface-overlay);
}
.sidenav__link.is-active {
  background: var(--surface-overlay);
  color: var(--primary);  /* active nav = primary accent; --info same value today, semantics differ */
  font-weight: var(--font-weight-semibold);
  border-left: 2px solid var(--primary);  /* non-colour indicator for colour-blind operators */
  padding-left: calc(var(--control-pad-x) - 2px);  /* compensate for border width */
}
.sidenav__link--legacy {
  color: var(--text-secondary);
}
.sidenav__legacy-mark {
  opacity: 0.7;
}
.sidenav__icon {
  flex-shrink: 0;
  opacity: 0.85;
}
.sidenav__label {
  flex: 1;
  min-width: 0;
}
/* Anomaly-count badge (W8) — visual treatment mirrors the legacy sidebar's
   .app-sidebar__badge (danger-toned pill, hidden entirely at zero via
   v-if/showBadge() rather than CSS `hidden`, since Vue already keeps it out
   of the DOM at zero). */
.sidenav__badge {
  flex-shrink: 0;
  min-width: 1.25rem;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill);
  background: var(--danger);
  color: var(--surface-raised);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  text-align: center;
  line-height: 1.4;
}
/* Standard clip-based visually-hidden utility (same recipe as
   MonitorDashboard.vue's R17 severity label) — the badge's numeral stays
   visual-only; this appends the "N 项异常" context so a screen reader
   doesn't announce a bare number. */
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* Off-canvas drawer below 960px — mirrors legacy global_nav.css's
   @media (max-width: 960px) .app-sidebar transform/box-shadow treatment.
   Above this breakpoint the sidebar is entirely unaffected (existing
   always-visible column behaviour, zero regression). */
@media (max-width: 960px) {
  .sidenav {
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    z-index: 1050;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.5);
  }
  .sidenav.sidenav--open {
    transform: translateX(0);
  }
}
</style>
