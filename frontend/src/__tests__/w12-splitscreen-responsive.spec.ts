/**
 * W12: 分屏寬度可用性 (700-960px) — Plan 2026-07-06-005, D12.
 *
 * jsdom does not evaluate CSS media queries (no real layout engine), so this
 * guard follows the same "read source text with regex" technique as
 * data-table-adoption.spec.ts / token-resolution.spec.ts rather than trying
 * to render actual visual breakpoints.
 *
 * Scope per D12: 700-960px desktop split-screen only, Settings + Monitor
 * (non-table surfaces — v0.6.0 U5's DataTable hasn't landed, so there is no
 * card-fallback branch to touch). History's `.data-table-wrap` horizontal
 * scroll is a *regression* check here, not new work — this file asserts it
 * is untouched, it does not add new table behavior.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
const PAGES_DIR = resolve(__dir, '../pages')

function read(rel: string): string {
  return readFileSync(resolve(PAGES_DIR, rel), 'utf8')
}

describe('W12: Settings split-screen collapse (700-960px)', () => {
  const src = read('Settings/SettingsPage.vue')

  it('extends the sidebar-collapse breakpoint to cover the full 700-960px band (not just <=720px)', () => {
    // The old 720px-only breakpoint left a gap: a 760px split-screen viewport
    // (inside the 700-960px range D12 targets) would fall between the old
    // 720px collapse and no upper collapse at all, keeping the two-column
    // grid + visible sidebar nav at a width too narrow for it.
    expect(src).not.toMatch(/@media\s*\(max-width:\s*720px\)/)
    expect(src).toMatch(/@media\s*\(max-width:\s*960px\)/)
  })

  it('the 960px query still collapses .settings__layout to one column and hides .settings__nav', () => {
    const queryBlockMatch = /@media\s*\(max-width:\s*960px\)\s*\{([\s\S]*?)\n\}/.exec(src)
    expect(queryBlockMatch, 'expected a max-width:960px media block').toBeTruthy()
    const block = queryBlockMatch![1]
    expect(block).toMatch(/\.settings__layout\s*\{[^}]*grid-template-columns:\s*1fr/)
    expect(block).toMatch(/\.settings__nav\s*\{[^}]*display:\s*none/)
  })
})

describe('W12: Monitor split-screen card flow (700-960px)', () => {
  const src = read('Monitor/MonitorDashboard.vue')

  it('adds a 960px query collapsing the card grid to one column and letting action links wrap', () => {
    const queryBlockMatch = /@media\s*\(max-width:\s*960px\)\s*\{([\s\S]*?)\n\}/.exec(src)
    expect(queryBlockMatch, 'expected a max-width:960px media block').toBeTruthy()
    const block = queryBlockMatch![1]
    expect(block).toMatch(/\.cards\s*\{[^}]*grid-template-columns:\s*1fr/)
    expect(block).toMatch(/\.card__links\s*\{[^}]*flex-wrap:\s*wrap/)
  })
})

describe('W12: History table horizontal-scroll regression guard', () => {
  it('HistoryPage.vue is untouched by W12 and still wraps its table in .data-table-wrap', () => {
    // Regression check only — W12 must not touch HistoryPage.vue (owned by
    // another in-flight unit) or invent new table behavior. This just proves
    // the pre-existing overflow-x mechanism this plan relies on is still there.
    const src = read('History/HistoryPage.vue')
    expect(src).toContain('data-table-wrap')
  })

  it('.data-table-wrap keeps its overflow-x: auto rule in app.css, unmodified by W12', () => {
    const cssPath = resolve(__dir, '../styles/app.css')
    const css = readFileSync(cssPath, 'utf8')
    expect(css).toMatch(/\.data-table-wrap\s*\{[^}]*overflow-x:\s*auto/)
  })
})
