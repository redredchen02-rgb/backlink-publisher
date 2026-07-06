---
status: pending
priority: p2
issue_id: "014"
tags: [correctness, adapters, hardening-sweep]
dependencies: []
---

# medium_browser.py's Save Draft fix conflates click failure with settle-wait failure, risking a false failure report on an actually-successful draft

## Problem Statement

D2's fix to `publishing/adapters/medium_browser.py` correctly stops reporting a false "drafted" success when the Save Draft button click fails. However, the adversarial code-review pass found the fix's try/except block wraps BOTH `page.locator(sel.SAVE_DRAFT).click()` AND the subsequent `page.wait_for_timeout(_SAVE_DRAFT_SETTLE_MS)` in the same handler. If the click genuinely succeeds (draft is saved) but the settle-wait step then throws for an unrelated reason (a known Playwright failure mode — e.g. an SPA navigation triggered by the click closing the current execution context), the new fix misreports this as "Save Draft click failed" and aborts the whole publish with `ExternalServiceError`, even though the draft may have been saved successfully.

## Findings

- `src/backlink_publisher/publishing/adapters/medium_browser.py:343-359` — the try block spans both `.click()` and `.wait_for_timeout()`.
- The new test (`test_save_draft_click_failure_raises_instead_of_reporting_drafted`) only mocks `.click()` itself raising — it does not cover the "click succeeds, settle-wait fails" scenario.
- This doesn't reintroduce the ORIGINAL bug (false "drafted" success) — it trades it for a different, lower-severity issue (a false failure on an actual success), which is a real UX/reliability regression risk but not a data-integrity or security issue.

## Proposed Solutions

### Option 1: Split the try/except so only `.click()` raising triggers the new `ExternalServiceError`; wrap the settle-wait separately with best-effort handling (matching the module's existing "best-effort settle" patterns elsewhere in the file)

**Approach:** Two narrower try blocks instead of one.
**Pros:** Directly fixes the conflation with minimal code change.
**Cons:** Needs a test for the "click succeeds, settle-wait fails" scenario to verify the split actually behaves as intended.
**Effort:** 1-2 hours.
**Risk:** Low.

### Option 2: Leave as-is; the failure mode is rare and results in an operator-visible retry-safe error rather than silent data loss

**Effort:** None.
**Risk:** Low-medium — an operator may see spurious "draft failed" errors for genuinely-saved drafts, which is a UX cost but not a correctness/security issue.

## Recommended Action

**To be filled during triage.** Option 1 is a small, low-risk fix that closes a real gap in the D2 fix's precision — recommend applying it as a quick follow-up to D2 rather than leaving it open-ended.

## Technical Details

**Affected files:**
- `src/backlink_publisher/publishing/adapters/medium_browser.py:343-359`
- `tests/test_adapter_medium_browser.py` (needs a new test for the click-succeeds/settle-fails path)

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (adversarial reviewer), 2026-07-06.
- Related commit: `a5f8ba3a` (D2, the original fix this refines).

## Acceptance Criteria

- [ ] A test proves: click succeeds, settle-wait throws -> the publish does NOT report a hard failure that contradicts an actual save (or at minimum, does not raise `ExternalServiceError` with a message implying the click itself failed).
- [ ] The existing red-then-green test for the original silent-swallow bug still passes unchanged.

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review adversarial persona)

**Actions:**
- Read the exact try/except boundaries in the D2 diff and identified the two distinct failure sources sharing one handler.

---

## Notes

- Low urgency: this is a refinement of an already-net-positive fix (D2), not a regression to the pre-fix state.
