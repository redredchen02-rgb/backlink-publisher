---
status: pending
priority: p1
issue_id: "001"
tags: [frontend, error-reporting, race-condition]
dependencies: []
---

# retryBufferedReports() has no in-flight guard — overlapping flush events can double-submit and drop buffered reports

## Problem Statement

`webui_app/static/js/ui/error-capture.js`'s `retryBufferedReports()` flushes the localStorage error-report buffer on `visibilitychange`/`pagehide`/next-load, but nothing prevents two of these events firing in close succession (e.g. `visibilitychange` immediately followed by `pagehide` during a real tab-close) from both reading the same buffer and racing to submit/clear it — potentially double-submitting the same reports or silently dropping ones added between the two reads.

## Findings

- Found by the `julik-frontend-races` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.85.
- `retryBufferedReports()` at `webui_app/static/js/ui/error-capture.js:219` has no module-level "already flushing" flag.
- The function reads the full buffer, submits each entry, then overwrites localStorage with a `remaining` array computed from the buffer state at READ time — if a second overlapping call already removed/added entries, the overwrite can lose them.
- No existing test exercises two overlapping flush calls (confirmed testing gap from the same review).

## Proposed Solutions

### Option 1: Module-level in-flight promise guard (Recommended)

**Approach:** Memoize the in-progress `retryBufferedReports()` promise in a module-level variable; a second call while one is in flight returns/awaits the same promise instead of starting a new read. Clear the guard in a `finally` block. Additionally, when writing back the "remaining" buffer, re-read localStorage at write time and remove only the specific entries this call actually submitted, rather than blindly overwriting with a stale snapshot.

**Pros:** Directly closes both the double-submit and lost-entry failure modes; small, localized change.

**Cons:** Requires care to get the read-modify-write ordering right; needs a dedicated overlapping-call test.

**Effort:** 1-2 hours including the new test.

**Risk:** Low — purely additive guard logic, no change to the happy-path single-flush behavior.

## Recommended Action

Implement Option 1. Add a regression test simulating `visibilitychange` immediately followed by `pagehide` (or two rapid `visibilitychange` events) and assert each buffered report is submitted exactly once with no entries lost.

## Technical Details

**Affected files:**
- `webui_app/static/js/ui/error-capture.js` — `retryBufferedReports()`, `MAX_BUFFERED_REPORTS` constant area
- `tests/js/test_ui_error_capture.mjs` — add the overlapping-flush regression test

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/julik-frontend-races.json`
- Plan: `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`

## Acceptance Criteria

- [ ] `retryBufferedReports()` guards against overlapping concurrent invocations
- [ ] Buffer write-back only removes entries actually submitted by that call, not a stale full-buffer snapshot
- [ ] New test: two overlapping flush-trigger events result in each buffered report submitted exactly once, none lost
- [ ] `node --test tests/js/test_ui_error_capture.mjs` passes

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the julik-frontend-races reviewer during Plan 2026-07-01-002's Phase 3 code review
- Verified as a genuine gap (no in-flight guard exists in the current implementation)
- Classified `manual` (behavior-changing concurrency fix, not auto-applied in this review pass)

## Notes

Paired with todo 002 (the legacy manual-report panel's equivalent missing busy-guard) — both stem from the same "no guard against overlapping async operations" gap in the legacy JS capture UI.
