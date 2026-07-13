/**
 * .data-table adoption guard — Unit 3 of
 * docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md.
 *
 * RETIRED (Task 12, 2026-07-13): this guard's original target list was five
 * pages hand-rolling Bootstrap's `table table-sm table-hover align-middle
 * mb-0` + `thead.table-light` classes instead of the shared `.data-table-wrap`
 * / `.data-table` convention. All five have since migrated to the shared
 * <DataTable> component (CampaignProgress/EquityLedger — Task 7 & 8; PrQueue —
 * Task 9; OptimizationStatus — Task 11; KeepAlive — Task 12, the last entry),
 * which renders `.data-table`/`.data-table-wrap` internally rather than in the
 * page's own source text — so this guard's source-text regex technique can no
 * longer see (or usefully check) any of them.
 *
 * component-adoption.spec.ts's `TABLE_TOLERANCE` ratchet is the successor
 * guard for "does this page still hand-roll a <table>" going forward. This
 * file is kept as a tombstone (rather than deleted) so the unit's history and
 * the retirement reasoning stay discoverable in-repo; the single trivial test
 * below just documents the empty target list instead of vacuously iterating
 * zero describe/it blocks.
 */

import { describe, it, expect } from 'vitest'

const TARGET_PAGES: string[] = []

describe('.data-table adoption guard (retired)', () => {
  it('TARGET_PAGES is empty — all pages migrated to <DataTable>; see component-adoption.spec.ts', () => {
    expect(TARGET_PAGES).toEqual([])
  })
})
