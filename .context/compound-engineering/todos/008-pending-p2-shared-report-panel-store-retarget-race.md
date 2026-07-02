---
status: pending
priority: p2
issue_id: "008"
tags: [frontend, error-reporting, race-condition, vue]
dependencies: []
---

# Shared reportPanel Pinia store lets the sibling trigger retarget an open panel mid-submit, silently losing the other session's typed text

## Problem Statement

`frontend/src/stores/reportPanel.ts`'s shared `isOpen`/`reportId` state lets `TopBar.vue`'s nav-bar button and `Toast.vue`'s per-toast "补充说明" action open the same panel instance. If a user opens the panel from one trigger, starts typing, and (while that submit is still in flight, or before submitting) the OTHER trigger opens the panel again, the panel silently retargets — losing the first session's typed text/context with no warning.

## Problem Statement (continued) / Findings

- Found by the `julik-frontend-races` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.72.
- `frontend/src/stores/reportPanel.ts:24` (`open()`).
- No test opens the shared store from the OTHER trigger point while a submit from the first trigger's session is still in flight.

## Proposed Solutions

### Option 1: Session token guard (Recommended)

**Approach:** Give each `open()` call a monotonically increasing session token stored in the panel store. `ReportProblemPanel.vue`'s `onSubmit` should capture that token before its `await` and only `close()`/set `errorMsg` if the store's current token still matches afterward (i.e. no other `open()` call has retargeted the panel in the meantime).

**Pros:** Closes the race cleanly without needing to lock/disable the OTHER trigger while one session is active.

**Cons:** Slightly more state to reason about in the store.

**Effort:** 1 hour including tests.

**Risk:** Low.

## Recommended Action

Implement Option 1. Add a test that opens the panel from one trigger, starts a submit, then opens from the other trigger before the first resolves, and asserts the first submit's completion doesn't clobber the second session's state.

## Technical Details

**Affected files:**
- `frontend/src/stores/reportPanel.ts`
- `frontend/src/components/ReportProblemPanel.vue` — `onSubmit`
- `frontend/src/components/ReportProblemPanel.spec.ts` — add the retarget-race test

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/julik-frontend-races.json`

## Acceptance Criteria

- [ ] A session token (or equivalent) prevents a stale submit from acting on a panel that's been retargeted to a different report/trigger since
- [ ] New test covers the cross-trigger retarget-during-submit scenario
- [ ] `npm run test` passes in `frontend/`

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the julik-frontend-races reviewer during Plan 2026-07-01-002's Phase 3 code review
- Classified `manual` (state-machine change to the shared panel store, not auto-applied in this review pass)

## Notes

None.
