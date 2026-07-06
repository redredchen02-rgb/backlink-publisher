---
status: pending
priority: p2
issue_id: "004"
tags: [backend, error-reporting, concurrency, sqlite]
dependencies: []
---

# increment_occurrence()/update_status()/attach_description() retain the SELECT-then-UPDATE lost-update race the module docstring only disclaims for add()

## Problem Statement

`webui_store/error_reports.py`'s module docstring extensively argues that `add()` avoids the same-key lost-update race documented in `docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md` (R5) because it's a bare INSERT, never a read-modify-write. That argument is correct for `add()` — but `increment_occurrence()`, `update_status()`, and `attach_description()` all keep the identical SELECT→merge→UPDATE shape R5 already measured a real lost-update rate for. Under concurrent duplicate-error submissions across tabs/processes (exactly the burst scenario fingerprint-merge exists to summarize), occurrence counts can be silently undercounted.

## Findings

- Found by the `reliability` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.65.
- `webui_store/error_reports.py:407` (`increment_occurrence`).
- `TestConcurrentAdd` proves `add()` is safe across separate instances, but no equivalent concurrency test exists for `increment_occurrence()`.
- This is the exact same store family R5 already accepted a documented limitation for — the question here is whether that acceptance should explicitly extend to these three methods too, or whether they should be hardened.

## Proposed Solutions

### Option 1: Rewrite to a single atomic UPDATE (Recommended for increment_occurrence)

**Approach:** Replace `increment_occurrence()`'s SELECT→merge→UPDATE with a single atomic `UPDATE error_reports SET occurrences = occurrences + 1, last_seen_at = ? WHERE id = ?`. This removes the race entirely for occurrence counting (the highest-value target since it's on the hot fingerprint-merge path).

**Pros:** Fully closes the race for the most concurrency-sensitive of the three methods; single SQL statement, easy to test.

**Cons:** `update_status()`/`attach_description()` still merge into a JSON blob (`data_json`) and can't trivially become a single atomic UPDATE without restructuring the schema.

**Effort:** 1 hour for `increment_occurrence()` alone.

**Risk:** Low for `increment_occurrence()`.

### Option 2: Explicitly document and accept the residual race for all three methods (matching R5's original framing)

**Approach:** Extend the module docstring's R5-acceptance language to explicitly cover `update_status()`/`attach_description()`/`increment_occurrence()`, rather than implying (by omission) that only `add()` needed the callout.

**Pros:** No code change, fast, honest documentation.

**Cons:** Leaves the actual race in place for occurrence counting, which directly undermines the fingerprint-merge feature's accuracy under real bursts.

**Effort:** 15 minutes.

**Risk:** None (documentation only), but doesn't fix the underlying issue.

## Recommended Action

Prefer Option 1 for `increment_occurrence()` specifically, since it's cheap and closes the race on the most-exercised path. For `update_status()`/`attach_description()`, apply Option 2 (explicit documentation) unless a future incident shows they need the same treatment.

## Technical Details

**Affected files:**
- `webui_store/error_reports.py` — `increment_occurrence()`, `update_status()`, `attach_description()`, module docstring
- `tests/test_webui_store_error_reports_sqlite.py` — add a concurrency test analogous to `TestConcurrentAdd` for `increment_occurrence()`

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/reliability.json`
- Precedent: `docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md` (R5)

## Acceptance Criteria

- [ ] `increment_occurrence()` uses a single atomic UPDATE (no intervening SELECT)
- [ ] New concurrency test analogous to `TestConcurrentAdd` proves no lost updates across concurrent `increment_occurrence()` calls on the same row
- [ ] Module docstring updated to reflect the actual scope of the R5 acceptance across all four public write methods

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the reliability reviewer during Plan 2026-07-01-002's Phase 3 code review
- Verified the docstring's claim is scoped to `add()` only, while three other methods keep the R5-documented race shape
- Classified `manual` (behavior/concurrency-semantics change, not auto-applied in this review pass)

## Notes

None.
