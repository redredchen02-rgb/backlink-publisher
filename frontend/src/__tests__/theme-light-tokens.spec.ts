/**
 * Light-theme regression guard — Unit 1 of
 * docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md.
 *
 * Root cause this guards against: frontend/src/styles/app.css previously
 * carried an unconditional `:root { ... }` block (plus unscoped
 * `.alert-warning`/`.alert-danger`/`.btn-outline-secondary` overrides) that
 * always won over tokens.css's `[data-theme="light"]` block regardless of
 * the active `data-theme` attribute — so toggling the SPA theme button had
 * no visible effect. Same "read source text with regex" technique as
 * token-resolution.spec.ts (no browser cascade simulation).
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
// __dir = .../backlink-publisher/frontend/src/__tests__
const TOKENS_CSS = resolve(__dir, '../../../webui_app/static/css/tokens.css')
const APP_CSS    = resolve(__dir, '../styles/app.css')

const tokensCss = readFileSync(TOKENS_CSS, 'utf8')
const appCss    = readFileSync(APP_CSS, 'utf8')

/** Extract the body of a `[data-theme="light"] { ... }` block (first match). */
function lightThemeBlock(css: string): string {
  const m = css.match(/\[data-theme="light"\]\s*\{([\s\S]*?)\n\}/)
  return m ? m[1] : ''
}

describe('theme light-token guard', () => {
  it('tokens.css [data-theme="light"] block defines the accent/status/shadow keys needed for a real light theme', () => {
    const block = lightThemeBlock(tokensCss)
    expect(block, 'expected a [data-theme="light"] { ... } block in tokens.css').not.toEqual('')

    const requiredKeys = [
      '--primary',
      '--accent-cyan',
      '--on-primary',
      '--success-text',
      '--info-text',
      '--warning-text',
      '--danger-text',
      '--violet-text',
      '--shadow-sm',
      '--shadow-brand',
      '--shadow-brand-hover',
      '--shadow-glass',
    ]

    const missing = requiredKeys.filter((key) => !new RegExp(`${key}\\s*:`).test(block))
    expect(missing, `missing keys in [data-theme="light"] block: ${missing.join(', ')}`).toEqual([])
  })

  it('app.css no longer carries an unconditional :root override', () => {
    expect(/:root\s*\{/.test(appCss)).toBe(false)
  })

  it('app.css no longer carries unscoped .alert-warning/.alert-danger/.btn-outline-secondary rules', () => {
    const bannedClasses = ['alert-warning', 'alert-danger', 'btn-outline-secondary']
    const violations: string[] = []

    appCss.split('\n').forEach((line, i) => {
      for (const cls of bannedClasses) {
        if (line.includes(`.${cls}`) && !line.includes('[data-theme')) {
          violations.push(`app.css:${i + 1} — unscoped .${cls}: ${line.trim()}`)
        }
      }
    })

    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })

  it('tokens.css provides [data-theme="light"]-scoped versions of .alert-warning/.alert-danger/.btn-outline-secondary', () => {
    const requiredScopedSelectors = [
      /\[data-theme="light"\]\s*\.alert-warning/,
      /\[data-theme="light"\]\s*\.alert-danger/,
      /\[data-theme="light"\]\s*\.btn-outline-secondary/,
    ]

    const missing = requiredScopedSelectors.filter((re) => !re.test(tokensCss))
    expect(missing.length, 'tokens.css is missing a [data-theme="light"]-scoped version of one of .alert-warning/.alert-danger/.btn-outline-secondary').toBe(0)
  })
})
