// Plan 2026-06-18-002 U3 — theme store.
// The explicit single owner of the light/dark toggle (replaces the vanilla
// `window.*` global per the anti-rot rule). Dark is default; the toggle flips a
// `data-theme` attribute on <html> and tokens.css cascades — no CSS-in-JS.
import { defineStore } from 'pinia'
import { ref } from 'vue'

const STORAGE_KEY = 'bp-theme'
type Theme = 'dark' | 'light'

function apply(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
}

export const useThemeStore = defineStore('theme', () => {
  const initial: Theme =
    (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? 'dark'
  const theme = ref<Theme>(initial)
  apply(theme.value)

  function toggle(): void {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    localStorage.setItem(STORAGE_KEY, theme.value)
    apply(theme.value)
  }

  return { theme, toggle }
})
