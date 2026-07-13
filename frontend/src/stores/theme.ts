// Plan 2026-06-18-002 U3 — theme store.
// The explicit single owner of the light/dark toggle (replaces the vanilla
// `window.*` global per the anti-rot rule). Dark is default; the toggle flips a
// `data-theme` attribute on <html> and tokens.css cascades — no CSS-in-JS.
import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'bp-theme'
// Legacy Jinja pages persisted under this key before both surfaces unified on
// 'bp-theme'; read it as a one-time fallback so a preference set on a legacy page
// carries into the SPA instead of silently resetting (audit [39]).
const LEGACY_STORAGE_KEY = 'backlink-publisher-theme'
type Theme = 'dark' | 'light'

function apply(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
}

function readStored(): Theme | null {
  const v = localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(LEGACY_STORAGE_KEY)
  return v === 'dark' || v === 'light' ? v : null
}

export const useThemeStore = defineStore('theme', () => {
  const initial: Theme = readStored() ?? 'dark'
  const theme = ref<Theme>(initial)
  apply(theme.value)

  function toggle(): void {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    localStorage.setItem(STORAGE_KEY, theme.value)
    apply(theme.value)
  }

  return { theme, toggle }
})
