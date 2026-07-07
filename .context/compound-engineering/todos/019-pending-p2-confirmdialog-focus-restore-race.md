---
status: pending
priority: p2
issue_id: "019"
tags: [frontend, confirm-dialog, keepalive, accessibility, race-condition]
dependencies: []
---

# Focus restore to trigger element races the same-tick unmount of that trigger during KeepAlive's confirming→publishing transition

## Problem Statement

`ConfirmDialog.vue`'s `onOpen()` captures `prevFocusEl` as `document.activeElement` (the republish trigger button), and `onClose()` later calls `prevFocusEl.focus()`. In `KeepAlivePage.vue`, `doRepublish()` sets `actionState.value = 'publishing'` synchronously as its first statement, before its `await` on `executeRepublish`. That synchronous mutation flips the `open` binding (derived from `actionState === 'confirming'`) to `false` in the same reactive flush that also removes the gap-selection panel (`v-if` idle/selecting) containing `prevFocusEl`. Depending on watcher/render job ordering, `onClose`'s focus call can land on a node being unmounted in the same tick — typically dropping focus to `document.body` rather than anywhere meaningful. This is an a11y regression exactly at the confirming→publishing transition, the moment a screen-reader user most needs an announced focus target.

## Findings

- Found by the `julik-frontend-races` reviewer during Plan 2026-07-06-005 W3/W7 code review (run `20260706-165554-4eb9d65a`), confidence 0.65.
- `frontend/src/components/ConfirmDialog.vue:139-163` (`onOpen`/`onClose`) restores focus to a generic `prevFocusEl` with no check for whether that element is about to be unmounted by the parent's own state transition.
- No test asserts `document.activeElement` across the confirming→publishing transition in `KeepAlivePage`; only the ConfirmDialog unit tests check focus restore, and only for the cancel/Escape paths where the trigger element is not simultaneously being unmounted by the parent.

## Proposed Solutions

### Option 1: Explicit stable focus target on state-machine-driven close (Recommended)

**Approach:** When the dialog closes because of a parent state-machine transition (not a user cancel/Escape), have `KeepAlivePage` move focus explicitly to a stable landmark (e.g. the progress card heading) instead of relying on `ConfirmDialog`'s generic `prevFocusEl` restore.

**Pros:** Fixes the specific KeepAlive case without changing `ConfirmDialog`'s general-purpose restore behavior (which is correct for the cancel/Escape paths).

**Cons:** Requires KeepAlivePage to distinguish "closed by state machine" vs "closed by user cancel" and manage its own focus target for the former.

**Effort:** 1-2 hours including an a11y-focused regression test.

**Risk:** Low — additive, does not change ConfirmDialog's existing contract.

### Option 2: Keep the trigger button rendered (visually hidden) through the publishing transition

**Approach:** Instead of `v-if` removing the gap-selection panel immediately, keep the trigger button present but visually hidden until the publishing transition settles, so `prevFocusEl` remains a valid, focusable node when `onClose` runs.

**Pros:** No change needed in ConfirmDialog or KeepAlivePage's focus logic.

**Cons:** More invasive to KeepAlivePage's existing v-if-driven panel layout; risk of the hidden trigger being reachable via Tab if not also given `tabindex="-1"` while hidden.

**Effort:** 2-3 hours.

**Risk:** Medium — layout/tab-order side effects need careful verification.

## Recommended Action

Implement Option 1. Add a test asserting `document.activeElement` lands on a stable, meaningful element (not `document.body`) immediately after the confirming→publishing transition.

## Technical Details

**Affected files:**
- `frontend/src/pages/KeepAlive/KeepAlivePage.vue` — `doRepublish()`, focus handling on state transition
- `frontend/src/components/ConfirmDialog.vue` — `onClose()` (context only, likely unchanged if Option 1 is taken)
- `frontend/src/pages/KeepAlive/KeepAlivePage.spec.ts` — add the focus-target regression test

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260706-165554-4eb9d65a/julik-frontend-races.json`
- Plan: `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` (W3)

## Acceptance Criteria

- [ ] Focus lands on a stable, meaningful element (not `document.body`) immediately after the confirming→publishing transition
- [ ] New test: `document.activeElement` assertion across the confirming→publishing transition
- [ ] `cd frontend && npx vitest run src/pages/KeepAlive/KeepAlivePage.spec.ts` passes

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode, run 20260706-165554-4eb9d65a)

**Actions:**
- Surfaced by the julik-frontend-races reviewer during Plan 2026-07-06-005 W3/W7 code review
- Verified as a genuine timing gap (no explicit focus-target handling exists for the state-machine-driven close path)
- Classified `gated_auto` (concrete fix options exist, but changing focus-restore behavior touches a11y contracts — needs sign-off)

## Notes

Discovered alongside todo 011 (startConfirm re-entrancy race) — both stem from `doRepublish` synchronously flipping `actionState` before its `await`.
