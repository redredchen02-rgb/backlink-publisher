// Plan 2026-07-06-005 W10 — session-scoped row <-> error-report correlation.
//
// W13 wired History's hand-written mutation catch blocks to
// `reportManualMutationError` (lib/errorCapture.ts), so a failed row action
// (delete/undo/recheck/bulk-*) now produces a real error-reports row. But the
// backend `error_reports` table (webui_store/error_reports.py) has NO
// row-id/route field — `fingerprint` is derived purely from
// name+message+stack (see error-capture-core.js's `computeFingerprint`), and
// the manual-report `message` only carries a free-form call-site label like
// `history.delete`, never the specific row id. So there is no way to look up
// "which report belongs to this row" from the server data alone.
//
// This store closes that gap the ONLY honest way available without a backend
// schema change: it records the *exact* id returned by submitting THAT
// specific failure for THAT specific row, at the moment it happens (see
// HistoryPage.vue's `reportError`). It is NOT a heuristic/fuzzy match — each
// entry is a literal, causally-verified correlation. Consequences of that
// choice, both deliberate:
//   - It is memory-only (a plain Pinia store, not persisted) and therefore
//     does not survive a full page reload. Do NOT attempt to reconstruct
//     stale correlations from `fingerprint`/`message` after a reload — a
//     guess like "the most recent report with a matching context prefix" is
//     exactly the fragile heuristic this module exists to avoid; if the
//     mapping isn't in memory, the honest answer is "unknown", not a guess.
//   - It only ever covers rows that failed A ROW ACTION during the current
//     SPA session. A row with `status: 'failed'` because the ORIGINAL
//     PUBLISH attempt failed (unrelated to any UI mutation) never has an
//     entry here, and must not be given a fake "查看报告" link.
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface RowReportLink {
  /** Router route `name` to navigate back to (e.g. `'history'`). */
  routeName: string
  /** The row id within that route's list this report's failure applies to. */
  rowId: string
}

export const useRowReportLinksStore = defineStore('rowReportLinks', () => {
  const byReportId = ref<Map<string, RowReportLink>>(new Map())
  const byRowId = ref<Map<string, string>>(new Map())

  /** Record a real, causally-verified correlation: submitting the failure for
   *  `rowId` (on `routeName`'s page) produced error-report `reportId`. */
  function link(routeName: string, rowId: string, reportId: string): void {
    byReportId.value = new Map(byReportId.value).set(reportId, { routeName, rowId })
    byRowId.value = new Map(byRowId.value).set(rowId, reportId)
  }

  /** Drop any link for `rowId` — call once the row's underlying action later
   *  succeeds, or the row itself is gone, so a stale "查看报告" link never
   *  outlives the failure it described. */
  function unlinkRow(rowId: string): void {
    const reportId = byRowId.value.get(rowId)
    if (reportId === undefined) return
    const nextByRow = new Map(byRowId.value)
    nextByRow.delete(rowId)
    byRowId.value = nextByRow
    const nextByReport = new Map(byReportId.value)
    nextByReport.delete(reportId)
    byReportId.value = nextByReport
  }

  /** Forward direction: History row -> its report id, if one is known. */
  function reportIdForRow(rowId: string): string | undefined {
    return byRowId.value.get(rowId)
  }

  /** Backward direction: error-report -> the row/route it came from, if
   *  still known (memory-only — see module docstring). */
  function linkForReport(reportId: string): RowReportLink | undefined {
    return byReportId.value.get(reportId)
  }

  return { link, unlinkRow, reportIdForRow, linkForReport }
})
