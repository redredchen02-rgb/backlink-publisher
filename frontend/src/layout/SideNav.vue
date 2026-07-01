<script setup lang="ts">
// Console sidebar — Plan 2026-06-18-002 U4.
// Groups outlive the migration (Pipeline/Monitoring/Operations/Config). Migrated
// items are RouterLinks (in-SPA, active-state); legacy items are <a> that fully
// navigate out of the SPA and are marked with '↪' so the operator knows.
//
// Plan 2026-07-01-001 U4: below the 1024px breakpoint this <nav> becomes an
// off-canvas drawer (transform, not v-if — it must stay mounted so
// useSidenavDrawer's drawerEl ref, focus trap, and Escape/overlay-close all
// keep working). Above the breakpoint nothing here changes from today.
// `role="dialog"`/`aria-modal` are applied only while the drawer is actually
// open (which auto-closes on resize past the breakpoint), so wide-screen
// a11y semantics are unchanged. Falls back to a standalone drawer instance
// when mounted without an AppShell ancestor (e.g. SideNav.spec.ts), so
// existing tests are unaffected.
import { inject, onMounted, ref } from 'vue'
import {
  GROUP_LABELS,
  GROUP_ORDER,
  isMigrated,
  itemsByGroup,
} from './navItems'
import { SIDENAV_DRAWER_KEY, useSidenavDrawer } from '../composables/useSidenavDrawer'

const drawer = inject(SIDENAV_DRAWER_KEY, () => useSidenavDrawer(), true)
const navEl = ref<HTMLElement | null>(null)
onMounted(() => {
  drawer.drawerEl.value = navEl.value
})
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
            {{ item.label }}
          </RouterLink>
          <a
            v-else
            :href="item.href"
            class="sidenav__link sidenav__link--legacy"
            :title="`旧界面：点击将离开新控台（${item.href}）`"
          >
            {{ item.label }}<span class="sidenav__legacy-mark" aria-hidden="true"> ↪</span>
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
  font-weight: 700;
  padding: 0.25rem 0.5rem 0.75rem;
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
  display: block;
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

/* Off-canvas drawer below 1024px — mirrors legacy global_nav.css's
   @media (max-width: 1024px) .app-sidebar transform/box-shadow treatment.
   Above this breakpoint the sidebar is entirely unaffected (existing
   always-visible column behaviour, zero regression). */
@media (max-width: 1024px) {
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
