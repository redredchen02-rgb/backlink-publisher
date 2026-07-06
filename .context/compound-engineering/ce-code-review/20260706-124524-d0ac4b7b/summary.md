# Code Review: U3 batch-ops API parity + SPA presentation

**Scope:** `763d0280..1ba43546` (branch `feat/u3-batch-ops-api-parity`) — base is this branch's actual fork point; local `main` has since advanced due to concurrent activity elsewhere in this shared workspace.
**Files:** `webui_app/api/v1/{history,drafts,spec}.py`, `webui_app/api/v1/errors.py`, `monolith_budget.toml`, `openapi/backlink-api.yaml`, `frontend/src/api/{history,drafts}.ts`, `frontend/src/pages/{History,Drafts}/*.{vue,spec.ts}`, `tests/test_webui_api_v1_bulk_ops.py`, `tests/test_webui_lite_origin_guard_coverage.py`
**Reviewers (13):** correctness, testing, maintainability, project-standards, agent-native, learnings (always-on) + security, api-contract, reliability, adversarial, kieran-python, kieran-typescript, julik-frontend-races (diff touches new mutating endpoints, concurrency primitives, TypeScript/Vue, and Python)

## Findings and resolution

| # | Finding | Reviewer(s) | Severity | Resolution |
|---|---------|-------------|----------|------------|
| 1 | `BULK_CANCEL_FAILURE` mapped to the same "nothing changed" 502 bucket as `PERSISTENCE_FAILURE`, but `bulk_cancel` (unlike `bulk_publish_now`) has no rollback — a mid-batch failure can leave earlier items genuinely cancelled, hidden from the client since no refreshed list was returned | correctness, reliability, learnings (independently converged) | P2 (confidence ~0.85) | **Fixed** — moved to the soft-success bucket (200 + refreshed list + warning), same treatment as `SCHEDULER_SYNC_FAILED`. |
| 2 | Unbounded `ids` array — each id triggers real per-item work (scheduler job, store write, outbound check); no length cap | security, adversarial (converged) | P2 (confidence ~0.75) | **Fixed** — added `MAX_BULK_IDS=500`, applied uniformly via a shared `require_ids()` helper (also resolves the duplication finding below). |
| 3 | `_require_ids` duplicated verbatim across `drafts.py`/`history.py` | maintainability, kieran-python | P3 (confidence 0.6) | **Fixed** — extracted to `errors.require_ids()`, shared by both modules. |
| 4 | Bulk-action success unconditionally cleared the entire selection, wiping out a mid-flight reselection made while the request was still in progress — on both History and Drafts pages | julik-frontend-races (both pages, independently) | P2 (confidence 0.72) | **Fixed** — `run()` now only deselects the ids actually submitted; regression test added on both pages. |
| 5 | Single-flight lock test only proved same-thread recursion, not real concurrent request handling | testing | P2 (confidence 0.72) | **Fixed** — added a real multi-threaded test using `threading.Barrier`, mirroring the established pattern in `tests/test_idempotency_store.py`. |
| 6 | 409 test mocked a plain object instead of a real `ApiError` instance, deviating from every other `ApiError` test in the repo | kieran-typescript | P2 (confidence 0.65) | **Fixed** — now constructs `new ApiError(...)`; also added a busy-state-reset assertion for the failure path (testing). |
| 7 | Single-flight lock only guards the new `/api/v1/drafts/bulk-publish-now` route — the legacy `/ce:draft/bulk-publish-now` route reaches the same `DraftAPI.bulk_publish_now` mutation with no lock at all | maintainability, correctness, adversarial (3-way convergence, adversarial P1 confidence 0.85) | P1 | **Documented, not fixed** — requires touching the legacy route/facade, outside U3's declared file scope. Comment added explaining the gap and why it's low practical urgency today (`webui.py`'s `app.run()` has no `threaded=True`, confirmed via `webui.py:113`). Recorded as backlog. |
| 8 | Single-flight lock has no timeout — if the underlying call genuinely hangs, the lock is never released, permanently wedging the endpoint until process restart | reliability | P1 (confidence 0.82) | **Deferred to backlog** — needs an architectural decision (background job + poll, vs. a bounded executor with timeout). |
| 9 | `bulk-publish-now` lacks the `_refuse_when_allow_network()` hard-stop that credential-write endpoints have, despite triggering real external publish side effects | security | P1 (confidence 0.65) | **Deferred to backlog** — the same gap exists on the pre-existing single-item `/drafts/publish-now`; fixing only the new bulk endpoint would be an inconsistent partial fix. Needs a policy decision spanning both. |
| 10 | Duplicate ids within a single `bulk_publish_now` call can corrupt the rollback bookkeeping | adversarial | P2 (confidence 0.7) | **Deferred to backlog** — facade-layer fix (`drafts_api.py`), outside U3's scope. |
| 11 | New `bulk-recheck` 422s on "no items matched"; sibling `bulk_delete`/`bulk_publish_now`/`bulk_cancel` facades silently return 200 with a 0-count message for the same scenario | api-contract | P2 (confidence 0.68) | **Deferred to backlog** — cross-facade semantic policy decision, not an endpoint-layer fix. |
| 12 | Cross-endpoint race: `bulk-cancel` and `bulk-publish-now` on an overlapping draft id have no shared coordination | adversarial | P2 (confidence 0.62, advisory) | **Deferred to backlog** — lower confidence, would need a broader per-item locking scheme. |

## Cross-references confirmed clean

- **project-standards**: zero findings — independently re-verified the `monolith_budget.toml` SLOC math (1307, ceiling 1340) and the CSRF-only snapshot bump (96→99) both via `radon`/`pytest`.
- **agent-native**: no new gap introduced. Surfaced two pre-existing, systemic observations out of scope for this diff: the OpenAPI spec has no `securitySchemes`/CSRF documentation anywhere on the `/api/v1` surface, and there's no CLI parity for the drafts/history domain (unlike PR-queue's `pr-opportunities`).
- **learnings**: confirmed via `webui.py:113` that this app runs single-process, single-threaded (`app.run()`, no `threaded=True`) — resolves the "does a `threading.Lock` even work" question favorably for today's deployment, though `medium_auth.py`'s existing `fcntl.flock` precedent shows this codebase has previously needed cross-process locking elsewhere.
- **adversarial**: confirmed the app runs single-process (no gunicorn/multi-worker evidence in this worktree); tried hard to break B4-equivalent generation-guard-style logic here and found the two P2s above (duplicate ids, cross-endpoint race) rather than anything more severe.

## Verification after fixes

- `tests/test_webui_api_v1_bulk_ops.py`: 14/14 (including the new real-concurrency test, stable across 5 repeated runs).
- Full backend sweep (`api_v1`/`bulk`/`drafts`/`history` keyword filter): 615/620 — 5 pre-existing, unrelated Windows chmod-permission failures, confirmed via `git stash` comparison against the pre-fix commit.
- Full frontend suite: 248/248. Typecheck: same 3 pre-existing unrelated errors (`ArticleReviewRow.spec.ts`, `KeepAlivePage.vue`).

**Verdict: Ready with fixes — all P2/P3 findings with in-scope, well-corroborated fixes are resolved (7 items). Three P1s and two P2s require either touching files outside U3's declared scope (legacy route/facade) or a policy decision spanning old+new endpoints — recorded as backlog items in the plan doc rather than expanding this unit's scope further.**
