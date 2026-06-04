---
title: "refactor: Complete _g_cache adoption in WebUI routes and extend complexity governance to webui_app/"
type: refactor
status: completed
date: 2026-06-03
deepened: 2026-06-03
claims: {}  # refactor of existing call sites; no new SLOC/CC claims pre-merge; budget entries validated at execution time per post-2026-05-20 policy.
---

# refactor: Complete _g_cache adoption in WebUI routes and extend complexity governance to webui_app/

## Overview

Two closely related WebUI hardening tasks:

1. **Config cache completion.** `webui_app/helpers/_request_cache.py` ships a `_g_cache(key, fn)` primitive that memoizes per-request in Flask's `g`. `contexts.py` and `channel_probes.py` already use it for `load_config()`. But ~25 direct `load_config()` calls remain across 9 route files — ~15 in read-path handlers (safe to cache) and ~10 in write-handler functions that must stay direct per the exclusion rule. The fix is to replace the read-path calls with `_g_cache('config', load_config)`, matching the established helper pattern.

2. **Governance gap for `webui_app/`.** `tests/test_no_complexity_regrowth.py` (Rule b) scans only `src/backlink_publisher/` with a CC-30 backstop. `webui_app/routes/sites.py::sites_save_three_url` is CC 38 (E-rated) with no budget ceiling — it can grow silently without CI failing. The fix is to extend the backstop test to also scan `webui_app/` and seed the one over-backstop outlier in `complexity_budget.toml`.

## Problem Frame

### Config cache

`load_config()` (CC 24 / D-rated) opens `config.toml` from disk via `tomllib.load()`, dispatches through 12+ sub-parsers, and returns a `Config` dataclass. This is non-trivial per call. In `contexts.py` and `channel_probes.py` it is already gated behind `_g_cache('config', load_config)` so repeated calls within one request are free. The routes layer bypasses this.

An operator GET to `/settings` triggers: route handler calls `load_config()` directly (parse #1), then `_settings_context()` calls `_g_cache('config', load_config)` (parse #2, even though key `'config'` is now set). Net result: 2 disk reads per settings GET where 1 suffices.

### Governance gap

`test_no_complexity_regrowth.py:232` scans `REPO_ROOT / "src" / "backlink_publisher"` only. `webui_app/routes/`, `webui_app/services/`, and `webui_app/helpers/` are not scanned. The most complex function in the WebUI layer is `sites_save_three_url` (CC 38, E-rated, ~129-line function; 246 SLOC is the full `sites.py` file, not the function). CC 38 with no ceiling means it can grow to CC 45 with no CI signal.

## Requirements Trace

- **R1.** Within any single HTTP request, `load_config()` is called at most once (the remaining calls hit `_g_cache`). Test: `test_webui_request_cache.py` already passes for `/settings`; extend coverage to `/sites`.
- **R2.** All `load_config()` calls within route handler functions whose bodies contain any call that persists config-derived state to disk — including `save_config(…)`, `save_blogger_token(…)`, `save_notion_token(…)`, `credential_service.save_token/save_token_fields/clear_credential`, or filesystem mutations via `cfg.*` (e.g., `cfg.blogger_token_path.unlink()`) — are left as direct calls (not wrapped in `_g_cache`). This covers inline `save_config(load_config(), …)` patterns and multi-line RMW patterns alike.
- **R3.** `webui_app/` is scanned by the CC backstop test. `sites_save_three_url` CC 38 is seeded in `complexity_budget.toml` with rationale ≥80 chars.
- **R4.** No behavior change — routing, response shapes, redirect targets, config mutations are identical.
- **R5.** Full test suite remains green.

## Scope Boundaries

- **Not** decomposing `sites_save_three_url` (CC seed tracks it for future decomposition).
- **Not** decomposing `_generate_payload` (CC 50, explicitly deferred).
- **Not** decomposing `_project_checkpoint` (CC 39, explicitly deferred).
- **Not** changing `save_config` behavior or its known non-round-trip sections.
- **Not** adding new `[network]` or `[webui]` config sections.
- **Not** adding `webui_app/` SLOC ceilings in `monolith_budget.toml`.

## Context & Research

### Relevant Code and Patterns

- **Existing `_g_cache` infrastructure:** `webui_app/helpers/_request_cache.py` — `_g_cache(key, fn)` uses `flask.g._ctx_cache` dict; falls back to direct `fn()` outside a request context. Zero changes needed to this module.
- **Established usage pattern:** `webui_app/helpers/contexts.py:94` — `cfg = _g_cache('config', load_config)`. `webui_app/helpers/channel_probes.py:61,96` — same. `webui_app/routes/health.py:18,295-303` — `_g_cache` for 9 other aggregations.
- **Exclusion rule (write-handler policy):** Any route handler function whose body contains a call that persists config-derived state to disk must keep ALL its `load_config()` calls as direct calls (not wrapped in `_g_cache`). The exclusion covers: `save_config(…)`, `save_blogger_token(…)`, `save_notion_token(…)`, `credential_service.save_token/save_token_fields/clear_credential`, or filesystem mutations using `cfg.*` (e.g., `cfg.blogger_token_path.unlink()`).
- **Confirmed write-handler exclusions (ALL `load_config()` in these handler functions stay direct):**
  - `webui_app/routes/settings_basic.py` — multiple POST handlers (`save_config` at lines 121, 155, 169, 182)
  - `webui_app/routes/sites.py::sites_save_three_url` — `cfg = load_config()` at line 203, `save_config(cfg, …)` at line 206
  - `webui_app/routes/oauth.py::settings_blogger_save_credentials` and `settings_blogger_oauth_start` — `save_config` at lines 58–69 and 88–100
  - `webui_app/routes/oauth.py::settings_blogger_oauth_callback` — line 193: `save_blogger_token(…, cfg.blogger_token_path)`
  - `webui_app/routes/settings_basic.py::settings_revoke_blogger` — line 194: `cfg.blogger_token_path.unlink()`
  - `webui_app/routes/llm.py::_sync_image_gen_config` — `load_config()` at line 93 and `save_config(…)` at lines 98 and 115
  - `webui_app/routes/token_paste.py::save_notion_channel_token` — lines 115 and 155: `save_notion_token` / `credential_service.save_token`
  - `webui_app/routes/token_paste.py::save_channel_token` — line 47: `credential_service.save_token_fields/clear_credential`
  - `webui_app/routes/channel_bind_save.py` — lines 116, 166, 246, 322 are inside `_save_token`, `_save_token_fields`, `_save_paste_blob`, `_save_userpass` helpers which use `credential_service` with `cfg`
- **Confirmed read-path call sites (replace with `_g_cache`):**
  - `webui_app/routes/equity_ledger.py:40` — GET display handler, no disk-write operations using cfg
  - `webui_app/routes/medium_login.py:39,62,90` — login helpers; safe because `config_dir` does not change within a request lifecycle (see Risks table)
  - `webui_app/routes/sites.py:48,241` — GET handlers separate from `sites_save_three_url`
  - `webui_app/routes/settings_basic.py:57,69,83` — `api_channel_status/verify/dry_run` single-call GET handlers
  - `webui_app/routes/image_gen.py:32` — API GET handler
- **Existing test coverage:** `tests/test_webui_request_cache.py` (100 lines) — tests `_g_cache` unit behavior and has one integration test verifying `/settings` calls `load_config()` once per request.
- **Backstop test scan scope:** `tests/test_no_complexity_regrowth.py:232` — `scan_root=REPO_ROOT / "src" / "backlink_publisher"`. Adding a sibling test `test_backstop_webui_unlisted_functions` with `scan_root=REPO_ROOT / "webui_app"` extends the governance net (the existing test is a plain function, not parametrized — add a sibling, do NOT add a `@pytest.mark.parametrize` decorator).

### Institutional Learnings

- `docs/solutions/test-failures/tests-coupled-to-operator-config-state-2026-05-18.md` — config tests must use sandbox config dirs + `monkeypatch.setenv`; the autouse sandbox fixture already handles this.
- `docs/solutions/best-practices/extract-cli-epilogue-block-2026-05-26.md` — non-behavior-changing refactors: carry mock seams, update budget ratchet in same PR.

## Key Technical Decisions

- **Cache key `'config'`**: Use the same cache key already used in `contexts.py` and `channel_probes.py`. A route handler replacing `load_config()` with `_g_cache('config', load_config)` hits the same cache slot that `_settings_context` populates — parse-once semantics across helpers and routes in the same request.
- **Do not cache write-handler loads**: Any handler function whose body contains a call that persists config-derived state to disk must use direct `load_config()` calls only. Full exclusion surface: `save_config`, `save_blogger_token`, `save_notion_token`, `credential_service.*`, `cfg.*` filesystem mutations. See confirmed exclusion list in Context & Research.
- **Import placement**: Add `from ..helpers._request_cache import _g_cache` to files being modified that don't already have it.
- **webui_app/ backstop scope**: Add sibling test `test_backstop_webui_unlisted_functions` to scan `webui_app/`. Budget entry and scan must land in the same PR.

## Open Questions

### Resolved During Planning

- **Can POST handlers safely cache `load_config()`?** Yes for read-only handlers; write handlers excluded per R2.
- **Are there webui_app functions between CC 30-38?** No. Only `sites_save_three_url` exceeds CC 30.
- **Does `_g_cache` work outside Flask request context?** Yes — `except RuntimeError` fallback calls `fn()` directly.

### Deferred to Implementation

- **Exact parse savings per endpoint**: Which handlers have 2+ calls in a single function. Confirm count before changing.
- **`pipeline_api.py` calls**: Two calls at lines 291 and 456 in background worker threads (outside request context). Leave as-is.

## Implementation Units

```
Unit 1 ──► Unit 2 (independent; can land in either order or same PR)
```

- [ ] **Unit 1: Replace read-path `load_config()` calls with `_g_cache('config', load_config)` in WebUI routes**

**Goal:** Every confirmed read-path `load_config()` call in `webui_app/routes/` uses `_g_cache` so parse-once semantics hold across the request.

**Requirements:** R1, R4, R5

**Dependencies:** None (infrastructure already in place)

**Files:**
- Modify: `webui_app/routes/equity_ledger.py`
- Modify: `webui_app/routes/medium_login.py`
- Modify: `webui_app/routes/sites.py`
- Modify: `webui_app/routes/settings_basic.py` (read-only handlers only; write handlers stay direct)
- Modify: `webui_app/routes/image_gen.py`
- No-op (write-handlers only): `webui_app/routes/llm.py`, `webui_app/routes/token_paste.py`, `webui_app/routes/channel_bind_save.py`, `webui_app/routes/oauth.py` — all their `load_config()` calls are inside write-handler functions; confirm with expanded exclusion rule before touching
- Test: `tests/test_webui_request_cache.py`

**Approach:**
- Apply the expanded write-handler exclusion rule: for each handler function, check if its body contains `save_config`, `save_blogger_token`, `save_notion_token`, `credential_service.*`, or `cfg.*` filesystem mutations. If yes, leave ALL `load_config()` calls direct. If no write operations, replace with `_g_cache('config', load_config)`.
- Concretely excluded (entire handler body stays direct): `settings_basic.py` POST/write handlers, `sites_save_three_url` (lines 203-241), `oauth.py` credential handlers (lines 58-100 and 193), `settings_revoke_blogger` (line 194), `llm.py::_sync_image_gen_config`, `token_paste.py` write handlers, `channel_bind_save.py` `_save_*` helpers.
- Safe to cache: `equity_ledger.py:40`, `medium_login.py:39,62,90`, `sites.py:48,241`, `settings_basic.py:57,69,83`, `image_gen.py:32`.
- Add `from ..helpers._request_cache import _g_cache` import to files being modified that don't already have it.

**Patterns to follow:**
- `webui_app/helpers/contexts.py:94` — `cfg = _g_cache('config', load_config)` (canonical usage)
- `webui_app/routes/health.py:18,295` — import pattern + _g_cache usage in a routes file

**Test scenarios:**
- Happy path: GET `/sites` — `load_config()` called at most once per request. Extend `test_load_config_called_once_per_settings_request` pattern for `/sites`. Monkeypatch `load_config` at the route module level (`monkeypatch.setattr(sites_mod, 'load_config', counting_fn)`) in addition to helper modules — otherwise the counting wrapper won't intercept direct route-level calls.
- Happy path: `_g_cache` falls back to direct `fn()` outside request context — existing tests cover this.
- Edge case: Requests with no `config.toml` on disk — `_g_cache` propagates `Config()` empty default correctly.
- Invariant check (AST enforcement): add a test to `test_webui_request_cache.py` that reads source of each confirmed write-handler function and asserts `_g_cache('config'` does not appear in its body. Write-handler functions to enumerate: `settings_basic.py` POST handlers, `sites_save_three_url`, `oauth.py::settings_blogger_save_credentials/settings_blogger_oauth_start/settings_blogger_oauth_callback`, `settings_basic.py::settings_revoke_blogger`, `llm.py::_sync_image_gen_config`, `token_paste.py::save_channel_token/save_notion_channel_token`, `channel_bind_save.py::_save_token/_save_token_fields/_save_paste_blob/_save_userpass`.

**Verification:**
- `grep -rn "load_config()" webui_app/routes/` shows remaining direct calls only inside confirmed write-handler functions. Expected residual direct calls: `settings_basic.py` POST handler lines, `sites.py:203`, `oauth.py:58,88,193`, `settings_basic.py:194`, `llm.py:93`, `token_paste.py:47,115,155`, `channel_bind_save.py:116,166,246,322`.
- `tests/test_webui_request_cache.py` passes.
- Full suite (`pytest tests/`) passes.

---

- [ ] **Unit 2: Extend complexity backstop to `webui_app/` and seed `sites_save_three_url` CC ceiling**

**Goal:** CI fails if any new function in `webui_app/` exceeds CC 30 without a budget entry.

**Requirements:** R3, R5

**Dependencies:** None (independent of Unit 1)

**Files:**
- Modify: `tests/test_no_complexity_regrowth.py`
- Modify: `complexity_budget.toml`

**Approach:**
- Add sibling test `test_backstop_webui_unlisted_functions` in `test_no_complexity_regrowth.py` that calls the same scan helper with `scan_root=REPO_ROOT / "webui_app"`. The existing test `test_unlisted_functions_within_backstop` is a plain function at line ~229 — add a sibling, do NOT parametrize the existing test.
- Add one entry in `complexity_budget.toml` for `webui_app/routes/sites.py::sites_save_three_url` with ceiling 38 (exact CC, zero headroom per grandfathered policy) and rationale ≥80 chars.
- Verify no other unlisted webui_app functions exceed CC 30 before landing.

**Patterns to follow:**
- Existing `complexity_budget.toml` grandfathered entries (`_project_checkpoint`, `_generate_payload`) — exact TOML format.
- Existing `test_unlisted_functions_within_backstop` function — scan helper invocation shape.

**Test scenarios:**
- Happy path: `pytest tests/test_no_complexity_regrowth.py` passes with the new scan.
- Red-path guard: a hypothetical unlisted function in `webui_app/` with CC 35 would fail the new test.
- Edge case: `webui_app/` classes with methods — verify scan helper uses `radon.visitors.Class` (it already does).

**Verification:**
- `pytest tests/test_no_complexity_regrowth.py -v` passes.
- `complexity_budget.toml` has exactly one new `[functions."webui_app/…"]` entry.
- `python -m radon cc webui_app/ -s | grep -E " [CDEF] "` shows only `sites_save_three_url` above CC 30.

## System-Wide Impact

- **Interaction graph:** `_g_cache` called from route handlers and helpers in the same Flask request context. No cross-request state shared. No CLI paths, background jobs, or scheduled tasks affected.
- **Error propagation:** `_g_cache` propagates exceptions from `fn()` — `DependencyError` from malformed TOML surfaces as before.
- **State lifecycle risks:** Write-path exclusion in R2 ensures handlers with disk-write operations always use a fresh load. The `_g_cache` is per-request; `flask.g` is cleared between requests.
- **API surface parity:** `pipeline_api.py` calls in background worker threads unaffected (`_g_cache` falls back to direct call outside request context).
- **Unchanged invariants:** `_request_cache.py` contract unchanged; cache key `'config'` semantics unchanged.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Write-handler exclusion missed — a handler using cfg-derived writes has its `load_config()` replaced with `_g_cache` | Apply expanded exclusion rule (save_config, save_blogger_token, save_notion_token, credential_service.*, cfg.*.unlink/write/rename). AST enforcement test in test_webui_request_cache.py catches violations in CI. |
| `webui_app/` has surprise CC>30 function not surfaced in research | Run `python -m radon cc webui_app/ -s \| grep -E "[CDEF]"` before landing. Only `sites_save_three_url` at CC 38 found; verify at implementation time. |
| Budget entry for `sites_save_three_url` lands without the backstop test — or vice versa | Both changes must land in the same PR. CI fails immediately if scan is active but entry is missing. |
| `medium_login.py` handlers cached on assumption that `config_dir` is immutable within a request | `clear_browser_profile` / `probe_login_status` / `launch_login_window` use `cfg.medium_user_data_dir` (derived from `config_dir`) for path resolution. Safe today because `BACKLINK_PUBLISHER_CONFIG_DIR` does not change within a request. If `config_dir` ever becomes per-request configurable, these handlers must be moved to the exclusion list. Document in code comment when applying `_g_cache`. |

## Sources & References

- Related code: `webui_app/helpers/_request_cache.py` (infrastructure), `webui_app/helpers/contexts.py:94` (established pattern)
- Related tests: `tests/test_webui_request_cache.py` (existing; extend for Unit 1)
- Budget files: `complexity_budget.toml`, `tests/test_no_complexity_regrowth.py`
- Prior art: `docs/solutions/best-practices/extract-cli-epilogue-block-2026-05-26.md`
