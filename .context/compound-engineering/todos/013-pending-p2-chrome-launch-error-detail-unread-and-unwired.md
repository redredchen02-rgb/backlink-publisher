---
status: pending
priority: p2
issue_id: "013"
tags: [maintainability, agent-native, hardening-sweep]
dependencies: []
---

# ChromeLaunchError's new `detail` field is never read, and RealChromeBrowserRunner isn't wired into production run_bind()

## Problem Statement

D3's fix to `cli/_bind/chrome_backend.py:60` correctly stops leaking raw exception text into the closed-enum `error_code` field, moving it to a new `detail` attribute on `ChromeLaunchError` instead. Three independent code-review passes (correctness, kieran-python, adversarial) confirmed `.detail` is never read anywhere in the codebase outside test assertions — the diagnostic value the fix's own docstring claims to preserve is currently unreachable. Separately, `run_bind()` (`cli/_bind/_driver_impl.py`) only catches `PlaywrightLaunchError`, never `ChromeLaunchError`, and `RealChromeBrowserRunner` (the class that raises `ChromeLaunchError`) is only ever constructed in test files — this whole backend appears not yet wired into the production bind flow.

## Findings

- Grepped every construction and read site of `ChromeLaunchError`/`.detail` in `src/` and `webui_app/` — zero non-test reads of `.detail`.
- `run_bind()`'s `except` clauses (`_driver_impl.py:315+`) cover `PlaywrightLaunchError`, `BoundPredicateTimeout`, `IdentityMismatch`, etc. — no `ChromeLaunchError` clause.
- `run_bind()`'s default `runner = _browser_runner or _PlaywrightBrowserRunner()` — never defaults to or is passed `RealChromeBrowserRunner` outside tests.
- This is not a regression from D3 — the backend appears to have been dormant before this diff too — but D3's fix effort was spent on a currently-unreachable code path, and the `detail` escape hatch it introduces has no consumer.

## Proposed Solutions

### Option 1: Wire `RealChromeBrowserRunner` into `run_bind()` (add a `ChromeLaunchError` except clause, and a way to select this runner) if the backend is intended to go live

**Effort:** Depends on product intent — could be small (an except clause + config flag) or larger if the backend needs further hardening first.
**Risk:** Medium — activates a previously-untested-in-production path.

### Option 2: If the Real Chrome backend is intentionally not yet live, leave it unwired but at minimum surface `.detail` somewhere reachable (a debug log at raise time) so the fix's stated diagnostic-preservation goal is actually true today, not just when the backend eventually ships

**Effort:** 30 minutes.
**Risk:** Low.

### Option 3: Do nothing now; track as a known "backend not yet activated" fact and revisit when the Real Chrome backend is scheduled to ship

**Effort:** None.
**Risk:** Low, but the D3 commit's stated goal ("preserving diagnostic value") remains unmet in practice until then.

## Recommended Action

**To be filled during triage.** This is a product-scope question (is Real Chrome backend activation planned soon?) as much as a code question — recommend checking with whoever owns that backend's rollout before choosing between Option 1 and Option 2/3.

## Technical Details

**Affected files:**
- `src/backlink_publisher/cli/_bind/chrome_backend.py` (`RealChromeBrowserRunner`, construction sites)
- `src/backlink_publisher/cli/_bind/_driver_impl.py:87-104` (`ChromeLaunchError` definition), `:268+` (`run_bind`)

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (correctness, kieran-python, adversarial reviewers — cross-reviewer agreement), 2026-07-06.

## Acceptance Criteria

- [ ] A decision is recorded (wire it up now, surface `.detail` some other way, or explicitly defer) with rationale.
- [ ] If wired up: `run_bind()` has a `ChromeLaunchError` except clause and the activation path is tested.
- [ ] If deferred: `.detail`'s current unreachability is acknowledged in a comment or the debt registry, so a future reader doesn't assume it's already load-bearing.

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review synthesis of 3 independent reviewer findings)

**Actions:**
- Cross-checked correctness/kieran-python/adversarial reviewer findings against each other and against direct grep of the codebase — all three converged on the same underlying fact independently.

---

## Notes

- Not a security bug — the D3 fix itself is correct and the `error_code` contract is genuinely safe now. This is about the unread `detail` escape hatch and the backend's production-wiring status.
