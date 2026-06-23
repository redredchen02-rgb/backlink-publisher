<script setup lang="ts">
// Global console shell — Plan 2026-06-18-002 U4. Persistent sidebar + top bar
// wrap the routed page; the Toast host lives here so notifications are global.
import SideNav from './SideNav.vue'
import TopBar from './TopBar.vue'
import Toast from '../components/Toast.vue'
</script>

<template>
  <div class="shell">
    <a href="#main" class="skip-link">跳至主内容</a>
    <SideNav />
    <div class="shell__body">
      <TopBar />
      <main id="main" class="shell__main" tabindex="-1">
        <RouterView />
      </main>
    </div>
    <Toast />
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
</style>
