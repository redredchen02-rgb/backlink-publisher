---
status: pending
priority: p3
issue_id: "010"
tags: [frontend, maintainability, vue]
dependencies: []
---

# notifications.ts's push() 4th positional reportId param is positional-param creep, not an options object

## Problem Statement

`frontend/src/stores/notifications.ts`'s `push(message, severity, timeout, reportId)` now has 4 positional parameters. Callers that only want to pass `reportId` must restate the `timeout` default explicitly (as both `frontend/src/lib/errorCapture.ts`'s call site and `notifications.spec.ts`'s new test already have to do) just to reach position 4.

## Findings

- Found by the `kieran-typescript` reviewer during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.70.
- `frontend/src/stores/notifications.ts:52`.

## Proposed Solutions

### Option 1: Convert trailing args to an options object (Recommended)

**Approach:** Change the signature to `push(message, severity, { timeout, reportId })`, with an options object defaulting internally, so callers that only need `reportId` don't have to restate `timeout`.

**Pros:** Removes the positional-creep smell; easier to extend with future optional fields.

**Cons:** Breaking change to every existing call site of `push()` across the codebase (not just the error-reporting call sites) — requires updating all callers and their tests in the same change.

**Effort:** 1-2 hours (mostly mechanical call-site updates + test updates).

**Risk:** Low-medium — purely a signature refactor, but touches every `push()` call site in the app.

## Recommended Action

Defer to a dedicated small refactor PR, since it requires touching every existing `push()` call site across the SPA, not just the ones added by this feature.

## Technical Details

**Affected files:**
- `frontend/src/stores/notifications.ts` — `push()` signature
- All existing callers of `push()` across `frontend/src/` (grep for `.push(` on the notifications store)
- `frontend/src/stores/notifications.spec.ts` — update to the new call shape

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/kieran-typescript.json`

## Acceptance Criteria

- [ ] `push()` accepts an options object for trailing optional parameters
- [ ] Every existing call site updated to the new signature
- [ ] `npm run test` and `npm run typecheck` pass in `frontend/`

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the kieran-typescript reviewer during Plan 2026-07-01-002's Phase 3 code review
- Classified `manual` (breaking signature change across many call sites, not auto-applied in this review pass)

## Notes

Low priority — purely a maintainability/ergonomics improvement, no functional bug.
