---
status: pending
priority: p2
issue_id: "007"
tags: [frontend, error-reporting, vue]
dependencies: []
---

# Vue SPA capture engine never flushes DedupTracker.collectPendingUpdates(), silently losing occurrence data the legacy JS engine reports

## Problem Statement

`frontend/src/lib/errorCapture.ts`'s shared `DedupTracker` instance records in-window duplicate occurrences via `record()`, but nothing on the Vue side ever calls `tracker.collectPendingUpdates()` to flush accumulated counts back to the server. The legacy JS engine (`webui_app/static/js/ui/error-capture.js`) has an equivalent periodic flush (`FLUSH_INTERVAL_MS`/`setInterval`) that the Vue side lacks entirely — so repeat occurrences of the same error within the dedup window are silently dropped on the Vue side instead of being reported as increased `occurrences`.

## Findings

- Found by the `correctness` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.78.
- `frontend/src/lib/errorCapture.ts:178` (`captureAndSubmit`) only submits on first-occurrence-in-window; subsequent duplicates within the window silently update the tracker's internal count with no corresponding network call.
- No Vue-side test exercises `DedupTracker.collectPendingUpdates()`/periodic-flush behavior, unlike `tests/js/test_ui_error_capture.mjs` for the legacy engine.

## Proposed Solutions

### Option 1: Add a periodic flush mirroring the legacy engine (Recommended)

**Approach:** Add a periodic flush in `errorCapture.ts` (mirroring `error-capture.js`'s `FLUSH_INTERVAL_MS`/`setInterval` pattern) that calls `tracker.collectPendingUpdates()` and re-submits a payload for every fingerprint whose count grew since the last flush.

**Pros:** Brings the Vue engine to parity with the legacy engine's occurrence-tracking behavior.

**Cons:** Needs a submission shape decision — likely a PATCH-style occurrence bump rather than a fresh POST, to avoid creating duplicate rows.

**Effort:** 1-2 hours including tests.

**Risk:** Low-medium — needs to correctly target the existing report row rather than creating new ones.

## Recommended Action

Implement Option 1, reusing the legacy engine's flush interval and payload-shape conventions as the template.

## Technical Details

**Affected files:**
- `frontend/src/lib/errorCapture.ts`
- `frontend/src/lib/errorCapture.spec.ts` — add periodic-flush test coverage

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/correctness.json`
- Reference pattern: `webui_app/static/js/ui/error-capture.js`'s `FLUSH_INTERVAL_MS`/`flushPendingUpdates()`

## Acceptance Criteria

- [ ] `errorCapture.ts` periodically flushes `DedupTracker.collectPendingUpdates()` results to the server
- [ ] New test exercises the flush behavior analogous to the legacy engine's coverage
- [ ] `npm run test` passes in `frontend/`

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the correctness reviewer during Plan 2026-07-01-002's Phase 3 code review
- Classified `manual` (requires a payload/submission design decision, not auto-applied in this review pass)

## Notes

None.
