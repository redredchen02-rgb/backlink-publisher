// frontend/src/__tests__/component-adoption.spec.ts
// Phase A ratchet guards — docs/superpowers/plans/2026-07-13-webui-phase-a-consistency.md
// Remove entries from the TOLERANCE sets as pages migrate; both must reach empty.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const PAGES = resolve(dirname(fileURLToPath(import.meta.url)), '../pages')
const read = (rel: string) => readFileSync(resolve(PAGES, rel), 'utf8')

/** List pages that must render tables via the shared <DataTable> component. */
const LIST_PAGES = [
  'CampaignProgress/CampaignProgressPage.vue',
  'Drafts/DraftsPage.vue',
  'EquityLedger/EquityLedgerPage.vue',
  'ErrorReports/ErrorReportsPage.vue',
  'History/HistoryPage.vue',
  'KeepAlive/KeepAlivePage.vue',
  'Operations/OperationsPage.vue',
  'OptimizationStatus/OptimizationStatusPage.vue',
  'PrQueue/PrQueuePage.vue',
  'Schedule/SchedulePage.vue',
  'Sites/SitesPage.vue',
]

/** EXEMPT: Health/HealthPage.vue — fail-open dashboard with expandable
 * drill-down rows and ~16 dynamic panels; DataTable's one-<tr>-per-item slot
 * model cannot express it. It keeps the .data-table CSS convention + sr-only
 * captions instead (see Task 13). Re-evaluate if DataTable grows row-details. */

// Ratchet: pages still hand-rolling <table>. Page tasks delete their entry.
const TABLE_TOLERANCE = new Set<string>([])

// Ratchet: files still hand-rolling status badges/pills (class="badge",
// class="status" :data-status, or STATUS_COLORS-style class maps).
const BADGE_TOLERANCE = new Set<string>([])

describe('DataTable component adoption (Phase A ratchet)', () => {
  for (const rel of LIST_PAGES) {
    if (TABLE_TOLERANCE.has(rel)) continue
    it(`${rel} uses <DataTable> and no raw <table>`, () => {
      const text = read(rel)
      expect(text, 'must import DataTable').toMatch(/import DataTable from/)
      expect(text, 'must not hand-roll <table>').not.toMatch(/<table\b/)
    })
  }
})

describe('StatusBadge adoption (Phase A ratchet)', () => {
  // Also catches dynamic bindings like :class="['badge', …]" and leftover
  // Bootstrap bg-* classes, which the literal class="…" patterns miss.
  const OFFENDER =
    /class="badge|class="status"|:data-status=|STATUS_COLORS|'badge'|\bbg-(?:success|danger|secondary|warning|primary|info|dark|light)\b/
  const ALL = [...LIST_PAGES, 'ErrorReports/ErrorReportDetailPage.vue']
  for (const rel of ALL) {
    if (BADGE_TOLERANCE.has(rel)) continue
    it(`${rel} has no hand-rolled badge/status markup`, () => {
      expect(read(rel)).not.toMatch(OFFENDER)
    })
  }
})
