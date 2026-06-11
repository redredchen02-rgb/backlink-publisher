---
date: 2026-06-03
topic: notion-duplicate-except-cleanup
---

# Notion Adapter: Remove Redundant try/except in HTTP 400 Handler

## Problem Frame

`execute()` in `notion_api.py` has two separate `except ValueError` blocks for `resp.json()`:

1. **Lines 249–254** (HTTP 400 branch) — silently swallows `ValueError`, falls back to `resp.text[:200]`
2. **Lines 262–267** (success branch) — correctly converts `ValueError` → `ExternalServiceError`

The HTTP 400 branch's inner `try/except` is redundant: after catching the error it raises `ExternalServiceError` anyway, so the JSON parsing was only to extract a nicer message. The same `resp.text[:200]` fallback is used by the 401 and non-200/201 handlers — no inner try needed there.

## Requirements

- R1. Remove the inner `try/except ValueError` block from the HTTP 400 branch in `execute()`.
- R2. Replace it with `resp.text[:200]` inline — matching the 401 and non-200/201 patterns.
- R3. The remaining `except ValueError as exc` for success-body parsing (lines 262–267) is unchanged.
- R4. Existing tests must continue to pass without modification.

## Scope Boundaries

- Only `notion_api.py` lines 249–257.
- No change to retry logic, outer `except (DependencyError, ExternalServiceError)`, or any other adapter.

## Success Criteria

- `pytest tests/test_notion_adapter.py` green.
- `execute()` contains exactly one `except ValueError` block (for success-body parsing).

## Next Steps

→ Proceed directly to work (lightweight, single-file, no open questions)
