---
status: pending
priority: p3
issue_id: "009"
tags: [backend, error-reporting, performance]
dependencies: []
---

# _enforce_daily_cap() fully JSON-decodes every report created today on every POST instead of using SELECT COUNT(*)

## Problem Statement

`webui_app/api/v1/error_reports.py`'s `_enforce_daily_cap()` (line ~111) fully decodes every report row created since midnight, on every single POST, just to `len()` them — instead of a `SELECT COUNT(*)`. Cost grows through the day and compounds exactly during a high-volume error burst, which is precisely when the cap needs to be cheap to check.

## Findings

- Found by the `reliability` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.6.
- No test exercises `_enforce_daily_cap()`'s latency under a large existing row count.

## Proposed Solutions

### Option 1: Use SELECT COUNT(*) (Recommended)

**Approach:** Use `SELECT COUNT(*) FROM error_reports WHERE created_at >= ?` instead of materializing/decoding every row.

**Pros:** Straightforward performance fix, no behavior change.

**Cons:** None significant.

**Effort:** 30 minutes.

**Risk:** Low.

## Recommended Action

Implement Option 1.

## Technical Details

**Affected files:**
- `webui_app/api/v1/error_reports.py` — `_enforce_daily_cap()`
- `webui_store/error_reports.py` — may need a `count_since(iso_timestamp)` helper if one doesn't already exist

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/reliability.json`

## Acceptance Criteria

- [ ] `_enforce_daily_cap()` uses a COUNT query instead of decoding every row
- [ ] Existing daily-cap tests (`test_daily_cap_exceeded_returns_problem_and_saves_nothing`, `test_daily_cap_excludes_increments_but_counts_new_fingerprints`) still pass

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the reliability reviewer during Plan 2026-07-01-002's Phase 3 code review
- Classified `manual` (touches SQL/store-layer logic, not auto-applied in this review pass)

## Notes

Low priority — not a correctness bug, only a scaling concern under sustained high daily volume.
