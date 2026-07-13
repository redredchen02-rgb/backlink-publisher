/**
 * .data-table adoption guard — Unit 3 of
 * docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md.
 *
 * Five pages (CampaignProgress/EquityLedger/KeepAlive/OptimizationStatus/PrQueue)
 * used to render their tables with Bootstrap's `table table-sm table-hover
 * align-middle mb-0` + `thead.table-light` classes instead of the shared
 * `.data-table-wrap` / `.data-table` convention already used by
 * History/Schedule/Sites. Same "read source text with regex" technique as
 * token-resolution.spec.ts (no browser/DOM rendering needed).
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
// __dir = .../backlink-publisher/frontend/src/__tests__
const PAGES_DIR = resolve(__dir, '../pages')

// EXEMPT: CampaignProgress & EquityLedger — migrated to DataTable component (Task 7 & 8),
// PrQueue (Task 9), and OptimizationStatus (Task 11) — same reason: DataTable
// provides .data-table/.data-table-wrap internally; those classes are not
// visible in the page source and thus cannot satisfy source-text regex checks.
const TARGET_PAGES = [
  'KeepAlive/KeepAlivePage.vue',
]

const sources = TARGET_PAGES.map((rel) => ({
  rel,
  text: readFileSync(resolve(PAGES_DIR, rel), 'utf8'),
}))

/**
 * True only when some `<table ...>` opening tag's `class="..."` attribute
 * carries `data-table` as its own whitespace-separated token — NOT merely as
 * a substring (which would also match the wrapper div's `data-table-wrap`
 * class, e.g. via a naive `/\bdata-table\b/` test: the hyphen in "-wrap" is a
 * regex word boundary, so that pattern false-positives on
 * `class="data-table-wrap"` alone with no `.data-table` on the <table> itself).
 */
function hasDataTableClassOnTableTag(text: string): boolean {
  const tableTagPattern = /<table\b[^>]*>/g
  let match: RegExpExecArray | null
  while ((match = tableTagPattern.exec(text)) !== null) {
    const tag = match[0]
    const classMatch = /\bclass="([^"]*)"/.exec(tag)
    if (!classMatch) continue
    const classes = classMatch[1].split(/\s+/)
    if (classes.includes('data-table')) return true
  }
  return false
}

describe('.data-table adoption guard', () => {
  it('each remaining target page references both .data-table and .data-table-wrap', () => {
    const missing: string[] = []

    for (const { rel, text } of sources) {
      if (!text.includes('data-table-wrap')) missing.push(`${rel} — missing "data-table-wrap"`)
      if (!hasDataTableClassOnTableTag(text)) {
        missing.push(`${rel} — no <table> tag carries class="data-table"`)
      }
    }

    expect(missing, `\n${missing.join('\n')}`).toEqual([])
  })

  it('none of the remaining target pages still use the Bootstrap table class combo', () => {
    const violations: string[] = []
    const BOOTSTRAP_TABLE_COMBO = 'table table-sm table-hover align-middle mb-0'

    for (const { rel, text } of sources) {
      if (text.includes(BOOTSTRAP_TABLE_COMBO)) {
        violations.push(`${rel} — still contains Bootstrap combo "${BOOTSTRAP_TABLE_COMBO}"`)
      }
      if (text.includes('table-light')) {
        violations.push(`${rel} — still contains "table-light"`)
      }
    }

    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })
})
