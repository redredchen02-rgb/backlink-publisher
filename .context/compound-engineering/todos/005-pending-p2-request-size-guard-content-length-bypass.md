---
status: pending
priority: p2
issue_id: "005"
tags: [backend, error-reporting, security]
dependencies: []
---

# Request-size guard trusts Content-Length only — absent/spoofed header bypasses the 100KB cap

## Problem Statement

`webui_app/api/v1/error_reports.py`'s `_guard_request_size()` (`_MAX_REQUEST_BYTES=100_000`) only checks `request.content_length`. If that header is absent (e.g. a non-browser caller using chunked transfer-encoding — exactly the threat the function's own docstring says it's guarding against) the cap is skipped entirely and `request.get_json()` reads an unbounded body into memory.

## Findings

- Found independently by both the `correctness` reviewer (confidence 0.66) and `security` reviewer (confidence 0.6, P3) during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`) — cross-reviewer agreement, severity taken as the higher of the two (P2).
- `webui_app/api/v1/error_reports.py` around line 145-153.
- No test exercises a missing/spoofed `Content-Length` against this endpoint.
- `kieran-python`'s review separately noted this mirrors an existing accepted pattern in `channel_bind_api.py` — so this is not a new regression pattern, but a pre-existing gap now newly relevant on a public-input endpoint.

## Proposed Solutions

### Option 1: Bounded stream read (Recommended)

**Approach:** Read the body via a bounded stream read (e.g. `request.stream.read(_MAX_REQUEST_BYTES + 1)`, 413 if it exceeds the cap) instead of relying solely on `Content-Length` before `request.get_json()`.

**Pros:** Closes the gap regardless of whether the client sends a header at all.

**Cons:** Slightly more code than the current header check; needs care to not break the existing happy-path parsing.

**Effort:** 1 hour including a chunked-encoding test.

**Risk:** Low-medium — touches request body handling, needs solid test coverage before landing.

### Option 2: App-wide Flask MAX_CONTENT_LENGTH

**Approach:** Set Flask's `MAX_CONTENT_LENGTH` globally so Werkzeug rejects an oversized body regardless of `Content-Length` presence.

**Pros:** Framework-level fix, covers every endpoint, not just this one.

**Cons:** `correctness`'s review explicitly cautions against a blanket app-wide cap since other endpoints may need a different ceiling than 100KB.

**Effort:** 15 minutes.

**Risk:** Medium — could break unrelated large-payload endpoints elsewhere in the app; needs an audit of every existing endpoint's expected body size before enabling globally.

## Recommended Action

Prefer Option 1, scoped to this endpoint only, to avoid the blanket-cap risk `correctness` flagged in Option 2.

## Technical Details

**Affected files:**
- `webui_app/api/v1/error_reports.py` — `_guard_request_size()`
- `tests/test_webui_api_v1_error_reports.py` — add a chunked-transfer-encoding / missing-Content-Length test

## Resources

- Review artifacts: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/correctness.json`, `security.json`, `kieran-python.json`

## Acceptance Criteria

- [ ] `_guard_request_size()` (or its replacement) rejects an oversized body even when `Content-Length` is absent or understated
- [ ] New test sends a POST with no `Content-Length` header and an oversized body, asserts a 413
- [ ] `pytest tests/test_webui_api_v1_error_reports.py` passes

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Independently flagged by two reviewers converging on the same function
- Confirmed this mirrors a pre-existing pattern elsewhere in the codebase (channel_bind_api.py), not a new regression
- Classified `gated_auto` (concrete fix exists but touches request-parsing behavior, not auto-applied in this review pass)

## Notes

None.
