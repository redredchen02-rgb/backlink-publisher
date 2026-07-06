// Shared sidenav-drawer composable — Plan 2026-07-01-001 U4.
//
// Off-canvas drawer behaviour for the SPA sidebar on narrow viewports, matching
// legacy Jinja's `webui_app/static/js/nav.js` MobileDrawer interaction semantics
// (breakpoint 1024px, Escape closes, backdrop click closes, body scroll lock)
// reimplemented in Vue idioms rather than ported. One instance is created in
// AppShell.vue and shared with SideNav.vue/TopBar.vue via provide/inject
// (SIDENAV_DRAWER_KEY) since the drawer body, the toggle button, and the
// overlay all live in different sibling components.
//
// Accessibility (a11y review requirements — see plan Unit 4 Approach):
//   - focus moves into the drawer (first focusable element) on open
//   - Tab/Shift+Tab is trapped inside the drawer while open
//   - focus returns to the trigger (hamburger) button on close
//   - Escape closes; the keydown listener is only registered while open
//   - resizing past the breakpoint while open auto-closes and releases the
//     scroll lock / focus trap, so state can't get stuck inconsistent with a
//     now-wide permanent-sidebar layout

import { type InjectionKey, type Ref, getCurrentScope, onScopeDispose, ref } from 'vue'

/** Matches legacy `global_nav.css`'s `@media (max-width: 1024px)` breakpoint. */
export const DRAWER_BREAKPOINT_PX = 1024

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useSidenavDrawer() {
  const isOpen = ref(false)
  /** The drawer's DOM container — set by SideNav.vue once its <nav> is mounted. */
  const drawerEl: Ref<HTMLElement | null> = ref(null)
  /** The hamburger toggle button — set by TopBar.vue once it is mounted. */
  const triggerEl: Ref<HTMLElement | null> = ref(null)

  let keydownListener: ((e: KeyboardEvent) => void) | null = null
  let resizeListener: (() => void) | null = null

  function getFocusable(): HTMLElement[] {
    if (!drawerEl.value) return []
    return Array.from(drawerEl.value.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
  }

  function focusFirst() {
    const focusable = getFocusable()
    const target = focusable[0] ?? drawerEl.value
    target?.focus()
  }

  function trapTab(e: KeyboardEvent) {
    const focusable = getFocusable()
    if (focusable.length === 0) {
      e.preventDefault()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement as HTMLElement | null
    const activeInDrawer = active != null && focusable.includes(active)

    if (e.shiftKey) {
      if (!activeInDrawer || active === first) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (!activeInDrawer || active === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      close()
      return
    }
    if (e.key === 'Tab') {
      trapTab(e)
    }
  }

  function handleResize() {
    if (isOpen.value && window.innerWidth > DRAWER_BREAKPOINT_PX) {
      close()
    }
  }

  function lockScroll() {
    document.body.style.overflow = 'hidden'
  }

  function unlockScroll() {
    document.body.style.overflow = ''
  }

  function open() {
    if (isOpen.value) return
    isOpen.value = true
    lockScroll()
    keydownListener = handleKeydown
    document.addEventListener('keydown', keydownListener)
    resizeListener = handleResize
    window.addEventListener('resize', resizeListener)
    focusFirst()
  }

  function close() {
    if (!isOpen.value) return
    isOpen.value = false
    unlockScroll()
    if (keydownListener) {
      document.removeEventListener('keydown', keydownListener)
      keydownListener = null
    }
    if (resizeListener) {
      window.removeEventListener('resize', resizeListener)
      resizeListener = null
    }
    triggerEl.value?.focus()
  }

  function toggle() {
    if (isOpen.value) {
      close()
    } else {
      open()
    }
  }

  // Safety net (code review): there's no other teardown path if the owning
  // component tree unmounts while the drawer is still open (Vite HMR today;
  // a real risk if AppShell is ever made conditionally-mounted later).
  // Guarded with getCurrentScope() since useSidenavDrawer() is also called
  // directly outside of a component's setup() scope (see
  // useSidenavDrawer.spec.ts), where onScopeDispose would otherwise warn.
  if (getCurrentScope()) {
    onScopeDispose(() => {
      if (isOpen.value) close()
    })
  }

  return { isOpen, drawerEl, triggerEl, open, close, toggle }
}

export type SidenavDrawer = ReturnType<typeof useSidenavDrawer>

/** Provide/inject key shared by AppShell (provider) and SideNav/TopBar (consumers). */
export const SIDENAV_DRAWER_KEY: InjectionKey<SidenavDrawer> = Symbol('sidenav-drawer')
