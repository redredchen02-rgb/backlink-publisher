---
status: pending
priority: p2
issue_id: "003"
tags: [backend, error-reporting, correctness]
dependencies: []
---

# PATCH /api/v1/error-reports/<id> ignores attach_description()/update_status() return values, producing a false-success 200

## Problem Statement

`webui_app/api/v1/error_reports.py`'s `update_error_report()` calls `attach_description()` and/or `update_status()` but never checks their boolean return values. If the report row is deleted concurrently between the initial existence check and these calls, both return `False` silently, and the endpoint falls through to `error_report_store.get(report_id) or existing`, returning the STALE pre-request `existing` object with a 200 — telling the client the update succeeded when nothing was actually persisted.

## Findings

- Found independently by both the `correctness` reviewer (confidence 0.72) and `kieran-python` reviewer (confidence 0.62, framed as a split-outcome-between-two-writes issue) during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`) — cross-reviewer agreement on the same root cause.
- `webui_app/api/v1/error_reports.py` around line 305.
- No existing test covers the race window where the row is deleted between the existence check and the write.
- This violates the project's own UX-Honesty convention (`docs/solutions/ux-honesty/webui-false-success-resolution.md`): never present a fake `ok:true`/200 when the underlying operation didn't actually happen.

## Proposed Solutions

### Option 1: Check return values, 404 on failure (Recommended)

**Approach:** After calling `attach_description()`/`update_status()`, check their boolean return values; if either returns `False`, raise `ApiProblem(404, ...)` instead of silently falling through.

**Pros:** Small, matches this endpoint's existing 404 pattern for the initial existence check; closes the false-success gap directly.

**Cons:** None significant.

**Effort:** 30-45 minutes including a new race-condition test.

**Risk:** Low.

## Recommended Action

Implement Option 1. Add a test that deletes the report between the initial existence check and the PATCH write (e.g. via monkeypatching `attach_description`/`update_status` to return `False`) and assert a 404, not a stale 200.

## Technical Details

**Affected files:**
- `webui_app/api/v1/error_reports.py` — `update_error_report()`
- `tests/test_webui_api_v1_error_reports.py` — add the race-condition test

## Resources

- Review artifacts: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/correctness.json`, `kieran-python.json`

## Acceptance Criteria

- [ ] `update_error_report()` raises a 404 `ApiProblem` when either write call returns `False`
- [ ] New test covers the concurrent-delete race window
- [ ] `pytest tests/test_webui_api_v1_error_reports.py` passes

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Independently flagged by two reviewers (correctness, kieran-python) converging on the same function/root cause
- Classified `gated_auto`/`manual` (changes the endpoint's error-response contract for this race window, not auto-applied)

## Notes

None.
