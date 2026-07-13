/**
 * Theme store storage-key migration — audit finding [39].
 *
 * The SPA and legacy Jinja pages now share the canonical 'bp-theme' localStorage
 * key. The store also reads the legacy 'backlink-publisher-theme' key as a one-time
 * fallback so a preference set on a legacy page carries into the SPA.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useThemeStore } from './theme'

describe('theme store storage-key migration', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    document.documentElement.removeAttribute('data-theme')
  })

  it('reads a preference stored under the legacy key when bp-theme is absent', () => {
    localStorage.setItem('backlink-publisher-theme', 'light')
    const store = useThemeStore()
    expect(store.theme).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('prefers the canonical bp-theme key over the legacy key', () => {
    localStorage.setItem('bp-theme', 'light')
    localStorage.setItem('backlink-publisher-theme', 'dark')
    const store = useThemeStore()
    expect(store.theme).toBe('light')
  })

  it('toggle persists under the canonical bp-theme key', () => {
    const store = useThemeStore() // default dark
    store.toggle() // -> light
    expect(localStorage.getItem('bp-theme')).toBe('light')
    expect(store.theme).toBe('light')
  })
})
