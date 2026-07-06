---
status: pending
priority: p3
issue_id: "013"
tags: [frontend, confirm-dialog, race-condition, latent]
dependencies: []
---

# ConfirmDialog's busy-guard resets unconditionally on reopen, not on prior confirm() settlement

## Problem Statement

`ConfirmDialog.vue`'s `onOpen()` (fired by `watch(() => props.open)` on every false→true transition) unconditionally sets `busy.value = false` and clears the error message. `onConfirmClick()` is the only place `busy` is set true, and it is only cleared in its own `finally` block after `props.confirm()` settles — there is no coupling between "a confirm() call is still in flight" and "the dialog is about to reopen." If a future/other caller flips `open` false→true externally (e.g. derived from unrelated reactive state, a route change, or a hotkey) while a prior `confirm()` promise from the same component instance is still pending, `onOpen` silently re-arms the confirm button before the first destructive call has resolved — allowing a double-fire of a destructive action.

**Not currently exploitable**: neither of this component's two real call sites can trigger it today — `KeepAlivePage`'s `open` is derived from a state machine where `'confirming'` is unreachable again until `'publishing'`/`'idle'` has fully unwound, and `BloggerCard`'s backdrop blocks the only button that could reopen it. This is a latent contract gap in the shared component, not a live break in the current diff.

## Findings

- Found by the `adversarial` reviewer during Plan 2026-07-06-005 W3/W7 code review (run `20260706-165554-4eb9d65a`), confidence 0.6.
- `frontend/src/components/ConfirmDialog.vue:139-140` (`onOpen`) has no check for an in-flight `confirm()` promise before resetting `busy`.

## Proposed Solutions

### Option 1: Track an in-flight confirm() promise across open/close transitions (Recommended)

**Approach:** Add a `pendingConfirm` promise ref set when `onConfirmClick` starts and cleared in its `finally`. Have `onOpen` refuse to reset `busy` while `pendingConfirm` is set (or block reopening entirely until it settles).

**Pros:** Closes the gap for any future consumer of the shared component, not just the current two call sites.

**Cons:** Adds state-tracking complexity to a component whose current real-world usage never exercises this path — some judgment needed on whether the added complexity is worth it before any consumer actually needs it.

**Effort:** 1 hour including a targeted test simulating an externally-driven reopen while `confirm()` is pending.

**Risk:** Low — additive guard, no change to existing call sites' behavior.

## Recommended Action

Track for future work. Since this is unreachable by both current call sites, it is not urgent, but should be fixed before any new consumer relies on externally-driven `open` transitions (rather than the state-machine-gated pattern both current callers use).

## Technical Details

**Affected files:**
- `frontend/src/components/ConfirmDialog.vue` — `onOpen()`, `onConfirmClick()`
- `frontend/src/components/ConfirmDialog.spec.ts` — add the externally-driven-reopen-while-pending test

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260706-165554-4eb9d65a/adversarial.json`
- Plan: `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` (W3)

## Acceptance Criteria

- [ ] `onOpen()` does not reset `busy` while a prior `confirm()` call from the same instance is still in flight
- [ ] New test: reopening the dialog externally while `confirm()` is pending does not allow a second concurrent `confirm()` invocation
- [ ] `cd frontend && npx vitest run src/components/ConfirmDialog.spec.ts` passes

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode, run 20260706-165554-4eb9d65a)

**Actions:**
- Surfaced by the adversarial reviewer during Plan 2026-07-06-005 W3/W7 code review
- Verified as a genuine latent gap; confirmed unreachable by both current call sites (KeepAlivePage, BloggerCard)
- Classified `manual` (a concrete fix exists but involves new state-tracking design, not a mechanical one-line patch; low urgency given current unreachability)

## Notes

Low priority — no current consumer of `ConfirmDialog` can trigger this. Revisit if a future consumer wires `open` from a source other than a state machine that already gates re-entry.
