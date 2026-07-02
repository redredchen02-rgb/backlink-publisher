---
status: pending
priority: p1
issue_id: "002"
tags: [frontend, error-reporting, race-condition]
dependencies: []
---

# Legacy ReportPanel._submit() has no busy/disabled guard — a double-click fires two concurrent submissions

## Problem Statement

`webui_app/static/js/ui/error-report-entry.js`'s `ReportPanel._submit()` (the legacy "report a problem" panel used by Unit 5) has no in-flight guard or disabled-state on its submit button, so a rapid double-click sends two concurrent requests. For the manual-report POST path, the server never merges these (no `reportId`/fingerprint means always-insert), so a double-click creates two duplicate report rows.

## Findings

- Found by the `julik-frontend-races` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.80.
- `error-report-entry.js:237`'s `_submit()` has no busy flag checked/set at entry, and the submit button is never disabled during the request.
- The Vue-side counterpart (`frontend/src/components/ReportProblemPanel.vue`) already does this correctly via a `submitting` ref that disables both buttons — the legacy side is the one missing this guard.
- No existing test drives a double-click against the legacy panel's submit button.

## Proposed Solutions

### Option 1: Mirror the Vue side's `submitting` guard (Recommended)

**Approach:** Add a busy flag to the `ReportPanel` class, checked/set at the top of `_submit()`, and toggle `submitBtn.disabled` for the duration of the request — exactly mirroring `ReportProblemPanel.vue`'s `submitting` ref pattern already in this same feature.

**Pros:** Trivial, consistent with the sibling implementation, closes the double-submit gap entirely.

**Cons:** None significant.

**Effort:** 30 minutes including a new test.

**Risk:** Low.

## Recommended Action

Implement Option 1. Add a regression test simulating two rapid clicks on the submit button and assert only one POST is sent.

## Technical Details

**Affected files:**
- `webui_app/static/js/ui/error-report-entry.js` — `ReportPanel._submit()`, `submitBtn` wiring
- `tests/js/test_ui_error_report_entry.mjs` — add the double-click regression test

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/julik-frontend-races.json`
- Reference pattern: `frontend/src/components/ReportProblemPanel.vue`'s `submitting` ref

## Acceptance Criteria

- [ ] `_submit()` is a no-op re-entrant guard while a submission is already in flight
- [ ] Submit button is disabled for the duration of the request (mirroring the Vue side)
- [ ] New test: two rapid clicks on submit result in exactly one POST
- [ ] `node --test tests/js/test_ui_error_report_entry.mjs` passes

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the julik-frontend-races reviewer during Plan 2026-07-01-002's Phase 3 code review
- Confirmed the Vue-side sibling component already implements this guard correctly, making this a straightforward parity fix
- Classified `manual` (small behavior change to an interactive UI flow, not auto-applied in this review pass)

## Notes

Paired with todo 001 (the legacy buffer-retry flush's equivalent missing guard).
