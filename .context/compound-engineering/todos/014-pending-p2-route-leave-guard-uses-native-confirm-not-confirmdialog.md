---
status: pending
priority: p2
issue_id: "014"
tags: [frontend, settings, confirm-dialog, router]
dependencies: []
---

# Route-leave dirty-warning uses native window.confirm instead of the W3 ConfirmDialog component

## Problem Statement

W2's `router.beforeEach` guard (added to warn users about unsaved Settings edits before navigating away) uses `window.confirm()` rather than the shared `ConfirmDialog.vue` component introduced in W3. This is exactly the pattern the plan's own doc-review flagged as a risk before W2 was implemented: "an implementer following the dependency graph literally would build it as a fourth bespoke confirm... reproducing the fragmentation D3/W3 exist to fix." W3 is now merged to main, so the concern that motivated the deviation (ConfirmDialog not existing yet) no longer applies.

## Findings

- W2 implementer's stated rationale: `router.beforeEach` needs a synchronous decision (or a simple async resolution) and awaiting a fully async modal confirmation from inside a global navigation guard adds complexity (a global confirm-service singleton reachable from outside component tree) beyond what the test scenarios explicitly asked for.
- `beforeunload` (tab-close case) genuinely cannot use any custom modal — that part is a correct, unavoidable use of the native browser API and is out of scope for this todo.
- Only the **in-app SPA navigation** case (`router.beforeEach`) is the target of this todo — that case has no OS-level constraint forcing a native dialog.

## Proposed Solutions

### Option 1: Global confirm-service singleton backed by ConfirmDialog (Recommended)

**Approach:** Create a small Pinia store or composable (`useGlobalConfirm()`) that mounts a single `ConfirmDialog` instance at the app root (e.g., in `AppShell.vue`) and exposes an imperative `confirm(options): Promise<boolean>` function. `router.beforeEach` calls this async function and awaits the result before calling `next()`/`next(false)` — Vue Router's navigation guards already support returning a Promise, so this is a supported pattern, not a workaround.

**Pros:** Actually unifies all destructive/blocking confirmations behind one component, matching W3's stated purpose; removes the native-dialog visual inconsistency (unstyled, un-themed, blocks the whole browser tab) from an otherwise polished SPA.

**Cons:** New shared infrastructure (confirm-service singleton) needs its own tests for edge cases: navigation triggered before the app root has mounted, guard rejecting/timing out, and interaction with the KeepAlive/Blogger flows that already consume ConfirmDialog directly (should not conflict — different consumers).

**Effort:** 2-3 hours including tests.

**Risk:** Low-medium — router guards are a sensitive spot; needs a regression test confirming normal (non-dirty) navigation is unaffected and confirming the dirty-navigation-confirm/cancel round trip still works through the async path.

## Recommended Action

Implement Option 1 when picking up further Settings/router polish work. Not urgent — `window.confirm` is functionally correct today (users are protected from data loss either way), this is a consistency/polish item, not a bug.

## Technical Details

**Affected files:**
- `frontend/src/router/index.ts` — replace the `window.confirm` call in `beforeEach`
- New: a confirm-service composable/store + its mount point in `AppShell.vue`
- `frontend/src/router/index.spec.ts` — update the existing route-leave-guard test to mock the new async confirm path instead of `window.confirm`

## Resources

- Plan: `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` (W2, W3; see the `route-leave dirty-warning may ship as a 4th ad-hoc confirm` doc-review finding in Deferred/Open Questions)
- `frontend/src/components/ConfirmDialog.vue` (W3)

## Acceptance Criteria

- [ ] `router.beforeEach`'s in-app navigation warning renders through `ConfirmDialog`, not `window.confirm`
- [ ] `beforeunload` (tab-close) is explicitly left alone — still native, documented as intentional
- [ ] Existing W2 tests updated to mock the new confirm path; all pass
- [ ] `cd frontend && npx vitest run` passes

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-work execution of plan 2026-07-06-005 W2)

**Actions:**
- W2 subagent made a deliberate, documented trade-off to use `window.confirm` given the added complexity of an async global confirm service
- Verified the underlying concern (this reproduces the exact pattern the doc-review warned about) is real but non-blocking — W2 ships as-is, this todo tracks the follow-up

## Notes

Low priority — purely a visual/consistency polish item, not a correctness or data-loss issue.
