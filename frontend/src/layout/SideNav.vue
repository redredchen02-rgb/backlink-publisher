<script setup lang="ts">
// Console sidebar — Plan 2026-06-18-002 U4.
// Groups outlive the migration (Pipeline/Monitoring/Operations/Config). Migrated
// items are RouterLinks (in-SPA, active-state); legacy items are <a> that fully
// navigate out of the SPA and are marked with '↪' so the operator knows.
import {
  GROUP_LABELS,
  GROUP_ORDER,
  isMigrated,
  itemsByGroup,
} from './navItems'
</script>

<template>
  <nav class="sidenav" aria-label="主导航">
    <div class="sidenav__brand">控台</div>
    <template v-for="group in GROUP_ORDER" :key="group">
      <div class="sidenav__group-label">{{ GROUP_LABELS[group] }}</div>
      <ul class="sidenav__list">
        <li v-for="item in itemsByGroup(group)" :key="item.label">
          <RouterLink
            v-if="isMigrated(item)"
            :to="item.to!"
            class="sidenav__link"
            active-class="is-active"
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
  border-right: 1px solid var(--border, #30363d);
  background: var(--surface-raised, #161b22);
  overflow-y: auto;
}
.sidenav__brand {
  font-weight: 700;
  padding: 0.25rem 0.5rem 0.75rem;
}
.sidenav__group-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary, #8b949e);
  padding: 0.75rem 0.5rem 0.25rem;
}
.sidenav__list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sidenav__link {
  display: block;
  padding: 0.4rem 0.5rem;
  border-radius: var(--radius-sm, 4px);
  color: var(--text-primary, #e6edf3);
  text-decoration: none;
  font-size: 0.875rem;
}
.sidenav__link:hover {
  background: var(--surface-overlay, #1f2630);
}
.sidenav__link.is-active {
  background: var(--surface-overlay, #1f2630);
  color: var(--primary, #38bdf8);  /* active nav = primary accent; --info same value today, semantics differ */
  font-weight: 600;
}
.sidenav__link--legacy {
  color: var(--text-secondary, #8b949e);
}
.sidenav__legacy-mark {
  opacity: 0.7;
}
</style>
