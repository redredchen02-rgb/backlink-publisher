---
status: pending
priority: p2
issue_id: "016"
tags: [maintainability, python, hardening-sweep]
dependencies: []
---

# TransientError's *args-based dual-shape constructor is a maintainability smell vs. an explicit factory

## Problem Statement

D1 (`0fb3885d`) consolidated 4 previously-separate `_TransientHTTPError` classes into the shared `TransientError` in `publishing/adapters/base.py`, using a `__init__(self, *args: Any)` signature that runtime-dispatches on `isinstance(args[0], int)` to support three call shapes (bare status int, int+detail string, plain message string). Two independent reviewers (maintainability, kieran-python) independently flagged this as harder to reason about and less type-safe than an explicit multi-parameter constructor or a `@classmethod` factory would be — and noted `ChromeLaunchError`, introduced the same day in D3, solves an analogous multi-shape problem with a clean explicit signature (`error_code: str = ..., *, detail: str | None = None`), making the `TransientError` design look like an avoidable inconsistency within the same diff.

## Findings

- `src/backlink_publisher/publishing/adapters/base.py:31-41` — `def __init__(self, *args: Any) -> None:` with `isinstance(args[0], int) and not isinstance(args[0], bool)` branching.
- No dedicated unit test exercises the two-arg (`int`, `str`) shape or asserts on `.status_code` directly — coverage relies on the 4 migrated adapters' existing tests incidentally exercising it.
- `cli/_bind/_driver_impl.py:99-102`'s `ChromeLaunchError.__init__` (added the same day, D3) uses an explicit `error_code: str = ..., *, detail: str | None = None` signature for a structurally similar "compat + new field" problem — a clean contrast within the same review scope.

## Proposed Solutions

### Option 1: Refactor to a `@classmethod` factory (`TransientError.from_status(code: int, detail: str | None = None)`) alongside a plain-message constructor, replacing the `*args` dispatch

**Pros:** Type-safe, self-documenting call sites, matches the `ChromeLaunchError` precedent in the same diff.
**Cons:** Requires updating all 4 already-migrated call sites (`blogger_api.py`, `medium_api.py`, `velog_graphql.py`, `llm_anchor_provider.py`) to use the new factory method.
**Effort:** 1-2 hours.
**Risk:** Low-medium (mechanical rename across a small, well-tested set of call sites).

### Option 2: Leave the `*args` design but add explicit type hints/docstring plus a dedicated unit test for both call shapes and the `.status_code` attribute

**Pros:** Much smaller change; closes the testing gap without a broader refactor.
**Cons:** Doesn't address the underlying design-clarity concern.
**Effort:** 30-45 minutes.
**Risk:** Low.

## Recommended Action

**To be filled during triage.** Given this is functioning correctly today and both reviewers rate this as a design preference rather than a bug, Option 2 (add tests, keep the design) is the lower-risk near-term choice; Option 1 is worth doing if/when `base.py`'s adapter exception classes get touched again for another reason.

## Technical Details

**Affected files:**
- `src/backlink_publisher/publishing/adapters/base.py:13-41`
- Call sites: `blogger_api.py`, `medium_api.py`, `velog_graphql.py`, `llm_anchor_provider.py`

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (maintainability + kieran-python reviewers, cross-reviewer agreement), 2026-07-06.
- Related commit: `0fb3885d` (D1).

## Acceptance Criteria

- [ ] Either the constructor is refactored to an explicit-parameter design, or a direct unit test is added covering both call shapes and the `.status_code` attribute.

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review synthesis of 2 independent reviewer findings)

---

## Notes

- Not a bug — no reported call site is broken today. Purely a design/testing-completeness concern.
