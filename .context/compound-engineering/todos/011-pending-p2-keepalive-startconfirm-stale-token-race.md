---
status: pending
priority: p2
issue_id: "011"
tags: [frontend, keepalive, race-condition, confirm-dialog]
dependencies: []
---

# startConfirm() has no re-entrancy/staleness guard — a slow or double-clicked token fetch can snap the state machine back to confirming after it already advanced

## Problem Statement

`KeepAlivePage.vue`'s `startConfirm()` is triggered by the republish button, which stays clickable and rendered for the entire duration of the awaited `getRepublishToken()` call — unlike `doRecheck`, which gets a busy-guard. Two overlapping invocations (double-click, or a slow first request plus an impatient second click) both resolve independently and each unconditionally sets `republishToken.value` and `actionState.value = 'confirming'`. If the first call wins the race and the user proceeds through confirm → `doRepublish` (which flips `actionState` to `publishing` → `result` and resets `selectedGaps` to an empty Set in `finishRepublish`), a later-resolving stale second call can still land and snap `actionState` back to `confirming` with a stale token and an emptied `selectedGaps` — silently reopening the ConfirmDialog after the flow already completed.

## Findings

- Found by the `julik-frontend-races` reviewer during Plan 2026-07-06-005 W3/W7 code review (run `20260706-165554-4eb9d65a`), confidence 0.75.
- `frontend/src/pages/KeepAlive/KeepAlivePage.vue:155-168` (`startConfirm`) has no busy flag and no request-sequence token — a classic overwritten-async-response race.
- No test exercises rapid or double-clicking the republish trigger button before `getRepublishToken()` resolves.

## Proposed Solutions

### Option 1: Mirror doRecheck's synchronous-flag guard + add a request-sequence id (Recommended)

**Approach:** Add a `confirmPending` ref set synchronously before the `await getRepublishToken()` (mirroring the existing `doRecheck` pattern in the same file), ignoring further clicks while pending. Additionally stamp each call with an incrementing request id and drop responses that don't match the latest id when they resolve, so a stale response can never re-open the dialog after the flow has moved on.

**Pros:** Reuses an existing in-codebase pattern (`doRecheck`); closes both the double-click and slow-then-fast-click race variants.

**Cons:** Needs a dedicated overlapping-click regression test since the current test suite doesn't cover this timing.

**Effort:** 1-2 hours including the new test.

**Risk:** Low — additive guard logic, no change to the single-click happy path.

## Recommended Action

Implement Option 1. Add a regression test simulating a double-click (or slow-then-fast-click) on the republish trigger and assert the state machine never regresses to `confirming` with a stale token after the flow has advanced past it.

## Technical Details

**Affected files:**
- `frontend/src/pages/KeepAlive/KeepAlivePage.vue` — `startConfirm()`, near the existing `doRecheck` guard pattern
- `frontend/src/pages/KeepAlive/KeepAlivePage.spec.ts` — add the overlapping-click regression test

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260706-165554-4eb9d65a/julik-frontend-races.json`
- Plan: `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` (W3)

## Acceptance Criteria

- [ ] `startConfirm()` guards against overlapping concurrent invocations (busy flag, mirroring `doRecheck`)
- [ ] Stale responses (request id mismatch) are dropped rather than mutating `actionState`/`republishToken`
- [ ] New test: double-click / slow-then-fast-click on the republish trigger never reopens `confirming` with a stale token after the flow advances
- [ ] `cd frontend && npx vitest run src/pages/KeepAlive/KeepAlivePage.spec.ts` passes

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode, run 20260706-165554-4eb9d65a)

**Actions:**
- Surfaced by the julik-frontend-races reviewer during Plan 2026-07-06-005 W3/W7 code review
- Verified as a genuine gap (no busy flag or staleness check exists in the current `startConfirm` implementation)
- Classified `gated_auto` (concrete fix pattern exists in the same file via `doRecheck`, but changes control flow — needs sign-off before applying)

## Notes

Discovered alongside todo 012 (ConfirmDialog focus-restore race during the same confirming→publishing transition) — both stem from `doRepublish` synchronously flipping `actionState` before its `await`.
