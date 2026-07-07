// Plan 2026-07-06-005 W10 — unit coverage for the session-scoped row <->
// error-report correlation store. See rowReportLinks.ts's module docstring
// for why this deliberately never persists and never guesses.
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRowReportLinksStore } from './rowReportLinks'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('rowReportLinks store', () => {
  it('links a row to a report id in both directions', () => {
    const store = useRowReportLinksStore()
    store.link('history', 'row-1', 'report-1')

    expect(store.reportIdForRow('row-1')).toBe('report-1')
    expect(store.linkForReport('report-1')).toEqual({ routeName: 'history', rowId: 'row-1' })
  })

  it('a row never linked has no entry (no fabricated correspondence)', () => {
    const store = useRowReportLinksStore()
    expect(store.reportIdForRow('never-linked')).toBeUndefined()
    expect(store.linkForReport('never-linked')).toBeUndefined()
  })

  it('unlinkRow removes both directions', () => {
    const store = useRowReportLinksStore()
    store.link('history', 'row-1', 'report-1')
    store.unlinkRow('row-1')

    expect(store.reportIdForRow('row-1')).toBeUndefined()
    expect(store.linkForReport('report-1')).toBeUndefined()
  })

  it('unlinkRow on a row with no link is a no-op', () => {
    const store = useRowReportLinksStore()
    expect(() => store.unlinkRow('nothing-here')).not.toThrow()
  })

  it('re-linking a row to a new report supersedes the old one', () => {
    const store = useRowReportLinksStore()
    store.link('history', 'row-1', 'report-1')
    store.link('history', 'row-1', 'report-2')

    expect(store.reportIdForRow('row-1')).toBe('report-2')
    expect(store.linkForReport('report-2')).toEqual({ routeName: 'history', rowId: 'row-1' })
  })
})
