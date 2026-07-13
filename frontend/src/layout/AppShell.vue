<script setup lang="ts">
// Global console shell — Plan 2026-06-18-002 U4. Persistent sidebar + top bar
// wrap the routed page; the Toast host lives here so notifications are global.
//
// Plan 2026-07-01-001 U4: owns the single shared drawer-state instance (one
// composable call for the whole app lifetime) and provides it down to
// SideNav.vue (drawer body) / TopBar.vue (hamburger toggle) since those are
// sibling components that both need to read/drive the same isOpen state. Also
// renders the overlay/backdrop here since it sits visually above both.
//
// Plan 2026-07-09-001: hosts the onboarding wizard overlay and auto-opens it on
// first load when setup is incomplete and the operator hasn't dismissed it.
import { provide, watch } from 'vue'
import SideNav from './SideNav.vue'
import TopBar from './TopBar.vue'
import Toast from '../components/Toast.vue'
import OnboardingWizard from '../components/OnboardingWizard.vue'
import { SIDENAV_DRAWER_KEY, useSidenavDrawer } from '../composables/useSidenavDrawer'
import { useOnboardingStore } from '../stores/onboarding'

const drawer = useSidenavDrawer()
provide(SIDENAV_DRAWER_KEY, drawer)

const onboarding = useOnboardingStore()
// Auto-open the guide once the status query resolves to "incomplete + not dismissed".
watch(
  () => onboarding.showWizard,
  (show) => {
    if (show) onboarding.openWizard()
  },
)
</script>

<template>
  <div class="shell">
    <a href="#main" class="skip-link">跳至主内容</a>
    <SideNav />
    <div
      class="shell__overlay"
      :class="{ 'shell__overlay--open': drawer.isOpen.value }"
      aria-hidden="true"
      @click="drawer.close()"
    ></div>
    <div class="shell__body">
      <TopBar />
      <main id="main" class="shell__main" tabindex="-1">
        <RouterView />
      </main>
    </div>
    <Toast />
    <OnboardingWizard />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}
.shell__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.shell__main {
  flex: 1;
  padding: 1.25rem;
  outline: none;
}
/* Drawer backdrop — only ever shown below the 960px breakpoint (SideNav.vue
   mirrors this breakpoint for the drawer transform); auto-close-on-resize in
   useSidenavDrawer guarantees isOpen can't be true above it. */
.shell__overlay {
  display: none;
}
@media (max-width: 960px) {
  .shell__overlay--open {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 1040;
    background: rgba(0, 0, 0, 0.55);
  }
}
</style>
