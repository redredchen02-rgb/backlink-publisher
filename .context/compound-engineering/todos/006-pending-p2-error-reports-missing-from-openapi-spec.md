---
status: pending
priority: p2
issue_id: "006"
tags: [backend, error-reporting, api-contract, agent-native]
dependencies: []
---

# New /api/v1/error-reports surface was never added to the OpenAPI 3.1 contract

## Problem Statement

`webui_app/api/v1/error_reports.py` implements a fully-functional CRUD API (POST/GET list/GET one/PATCH/DELETE), but `webui_app/api/v1/spec.py`, `webui_app/api/v1/schemas.py`, and `openapi/backlink-api.yaml` — which this project's own docstring calls "the single source of truth" feeding CI lint, Schemathesis conformance testing, and eventual frontend mocks — were never updated. Every sibling resource module (history, drafts, campaigns, channels, oauth, llm, image_gen, monitor, pipeline, etc.) has schemas + declared paths; error-reports has none.

## Findings

- Found by the `ce-agent-native-reviewer` during Plan 2026-07-01-002's code review (run `20260702-111259-cdf3442d`), confidence 0.85.
- Confirmed via `git diff --stat <base> -- webui_app/api/v1/spec.py openapi/backlink-api.yaml webui_app/api/v1/schemas.py` showing zero changes on this branch.
- `tests/test_webui_api_v1.py::test_committed_openapi_spec_is_not_stale` doesn't catch this gap because it only diffs the committed YAML against `spec.py`'s own generator output — since `spec.py` itself was never updated, both sides silently agree the endpoint doesn't exist.
- Net effect: the endpoints work perfectly for a caller that already knows the URLs from reading source, but anything relying on the OpenAPI contract as the discovery surface (Schemathesis, generated client SDKs, or a future in-app agent enumerating callable tools from the spec) has zero visibility into this feature.

## Proposed Solutions

### Option 1: Add error-reports schemas/paths following the existing sibling-module pattern (Recommended)

**Approach:** Follow the same pattern already used for every other `/api/v1` resource — add request/response schemas to `webui_app/api/v1/schemas.py`, declare the 5 paths (POST/GET list/GET one/PATCH/DELETE) in `webui_app/api/v1/spec.py`, and regenerate `openapi/backlink-api.yaml` so `test_committed_openapi_spec_is_not_stale` actually exercises this endpoint going forward.

**Pros:** Closes the discoverability gap completely; makes the existing staleness test meaningful for this endpoint; follows an established, well-understood pattern with many existing examples to mirror.

**Cons:** Requires writing out the full schema shape (request/response bodies, status codes, error envelope references) matching this project's existing conventions exactly — not a mechanical find/replace.

**Effort:** 2-3 hours (5 operations × schema authoring + spec wiring + YAML regeneration + verifying the staleness test now covers it).

**Risk:** Low — purely additive documentation/contract metadata, no behavior change to the actual endpoint.

## Recommended Action

Implement Option 1 in a dedicated follow-up PR/session, using an existing recently-added resource module (e.g. the channels or image_gen API) as the direct template for schema shape and spec.py wiring conventions.

## Technical Details

**Affected files:**
- `webui_app/api/v1/schemas.py` — add error-report request/response schemas
- `webui_app/api/v1/spec.py` — declare the 5 error-reports paths
- `openapi/backlink-api.yaml` — regenerate from `spec.py`
- `tests/test_webui_api_v1.py` — `test_committed_openapi_spec_is_not_stale` should then cover this endpoint automatically

## Resources

- Review artifact: `.context/compound-engineering/ce-code-review/20260702-111259-cdf3442d/agent-native.json`
- Reference pattern: any existing sibling `/api/v1` module (history, channels, image_gen) for schema/spec conventions

## Acceptance Criteria

- [ ] All 5 error-reports operations are declared in `webui_app/api/v1/spec.py`
- [ ] Request/response schemas added to `webui_app/api/v1/schemas.py`
- [ ] `openapi/backlink-api.yaml` regenerated and committed
- [ ] `pytest tests/test_webui_api_v1.py::test_committed_openapi_spec_is_not_stale` passes and actually exercises the new paths

## Work Log

### 2026-07-02 - Initial Discovery

**By:** Claude Code (ce-code-review, autofix mode)

**Actions:**
- Surfaced by the ce-agent-native-reviewer during Plan 2026-07-01-002's Phase 3 code review
- Confirmed via git diff that none of the 3 contract files were touched by this branch
- Classified as a genuine, non-mechanical documentation/contract-authoring gap — not auto-applied in this review pass

## Notes

This is a real capability-hiding gap, not a broken endpoint — the API itself works correctly and is fully tested at the HTTP layer (`tests/test_webui_api_v1_error_reports.py`).
