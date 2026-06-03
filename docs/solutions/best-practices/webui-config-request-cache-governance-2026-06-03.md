---
module: webui
date: 2026-06-03
problem_type: best_practice
component: development_workflow
severity: medium
applies_when:
  - Adding a new WebUI route handler that reads config
  - Reviewing whether a handler should use _g_cache or direct load_config()
  - Extending complexity_budget.toml or test_no_complexity_regrowth.py coverage
  - Auditing webui_app/ for redundant disk reads per HTTP request
tags:
  - request-cache
  - load-config
  - webui
  - complexity-budget
  - g-cache
  - write-handler-exclusion
  - governance
  - per-request-memoization
---

# WebUI Config Loading — Per-Request Memoization and Write-Handler Exclusion Rule

## Context

`load_config()` was called fresh on every HTTP request in five WebUI route files (`equity_ledger.py`, `medium_login.py`, `sites.py`, `settings_basic.py`, `image_gen.py`). A per-request memoization helper `_g_cache` already existed in `webui_app/helpers/_request_cache.py` and was used inconsistently — present in `contexts.py`, `channel_probes.py`, and `health.py`, absent in the five route files above.

The result: redundant TOML parse + filesystem stat on every request, and no CI gate ensuring uniform adoption. Additionally, `webui_app/` was not covered by the project's CC-30 complexity backstop gate (only `src/` was gated), leaving `sites_save_three_url` at CC 38 silently ungoverned. The refactor (PR #399, 2026-06-03) unified all read-path handlers onto `_g_cache`, established a write-handler exclusion rule, and added two CI gates to keep that discipline in place.

## Guidance

### Read-path handlers — use `_g_cache`

Handlers that read config but do not save or mutate it should use `_g_cache('config', load_config)`:

```python
# Before — fresh disk read on every request
from backlink_publisher.config import load_config

def api_channel_status():
    cfg = load_config()
    ...

# After — memoized per request, falls back to fn() outside request context
from backlink_publisher.config import load_config
from ..helpers._request_cache import _g_cache

def api_channel_status():
    cfg = _g_cache('config', load_config)
    ...
```

The helper stores the result on `flask.g._ctx_cache` so subsequent calls within the same request return the already-parsed object at dictionary-lookup cost. It falls back to `fn()` outside a request context (CLI, background workers, tests).

### Write-path handlers — keep direct `load_config()`

**This is a hard rule, not a preference.** Handlers that mutate config state must call `load_config()` directly to get a fresh object before writing:

```python
# Correct: direct call so the save operates on current disk state
def settings_save_medium_token():
    cfg = load_config()          # must be fresh
    save_config(cfg, medium_token=request.form["token"])

def settings_revoke_blogger():
    cfg = load_config()          # must be fresh
    cfg.blogger_token_path.unlink()
```

### Write-handler detection checklist

A handler is a write-handler if its body contains any of:
- `save_config(...)`
- `save_blogger_token(...)` / `save_notion_token(...)`
- `credential_service.*` mutation calls
- `cfg.*` filesystem mutations (e.g. `.unlink()`, `.write_*()`)

When a handler's read/write status is ambiguous, default to direct `load_config()`.

### Complexity backstop for `webui_app/`

`tests/test_no_complexity_regrowth.py` now includes `test_backstop_webui_unlisted_functions()` which enforces CC ≤ 30 on every unlisted function in `webui_app/`. When a new function exceeds CC 30, you must either reduce complexity or add an explicit `complexity_budget.toml` entry (with ≥80-char rationale) in the same PR.

## Why This Matters

**Redundant reads:** A single page render can trigger multiple handlers or helpers that each invoke `load_config()`. Without memoization, every invocation performs a TOML parse + filesystem stat inside the same Flask application context — wasted I/O that compounds as routes grow.

**Stale-write risk:** If a write-handler uses `_g_cache`, it receives a cached (potentially stale) config object, applies mutations, then writes that stale object back to disk — silently overwriting any field that changed between the cached read and the save. The CI gate exists specifically to make this class of mistake impossible to merge undetected.

**Ungoverned complexity:** Without the `webui_app/` backstop, new route functions could grow past CC 30 unnoticed. The CC-30 backstop that already governed `src/` was blind to the entire WebUI layer.

## When to Apply

- **New read-only route handler**: adopt `_g_cache` from the start.
- **Code review of any WebUI route file**: verify every `load_config()` call is either via `_g_cache` (read-path) or direct (write-path).
- **Adding a function to `webui_app/` above CC 30**: add a `complexity_budget.toml` entry with rationale in the same PR, or reduce complexity first.
- **`medium_login.py` handlers** (`medium_launch_browser_login`, `medium_probe_browser_login`, `medium_clear_browser_login`): currently use `_g_cache` on the assumption that `config_dir` is immutable within a request (process-global). If `config_dir` ever becomes per-request configurable, move these to the write-handler exclusion list.

## Examples

**`settings_basic.py` — three read-path API handlers unified:**

```python
# Before — each handler parsed config independently
def api_channel_status():
    cfg = load_config()
    ...

def api_channel_verify():
    cfg = load_config()
    ...

def api_channel_dry_run():
    cfg = load_config()
    ...

# After — all three share the same parsed object for the request
def api_channel_status():
    cfg = _g_cache('config', load_config)
    ...

def api_channel_verify():
    cfg = _g_cache('config', load_config)
    ...

def api_channel_dry_run():
    cfg = _g_cache('config', load_config)
    ...
```

**`sites.py` — mixed file, write-handler left direct:**

```python
# Read-path — memoized
@bp.route("/sites", methods=["GET"])
def sites_form():
    cfg = _g_cache('config', load_config)
    ...

# Write-path — direct call preserved
@bp.route("/sites/save-three-url", methods=["POST"])
def sites_save_three_url():
    ...
    cfg = load_config()          # fresh read before save_config()
    merged = dict(cfg.target_three_url)
    save_config(cfg, target_three_url=merged)
```

**AST enforcement CI gate** (`tests/test_webui_request_cache.py`):

```python
@pytest.mark.parametrize("module_name,func_name", _WRITE_HANDLER_SPECS)
def test_write_handler_does_not_use_g_cache_for_config(module_name, func_name):
    """CI gate: write-handlers must NOT use _g_cache('config', ...) to avoid stale reads."""
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name, None)
    if fn is None:
        pytest.skip(f"{module_name}.{func_name} not found")
    source = inspect.getsource(fn)
    assert "_g_cache('config'" not in source
```

The `_WRITE_HANDLER_SPECS` list in that file is the authoritative registry of known write-handlers. Add new write-handlers there when creating them.

**`complexity_budget.toml` entry for grandfathered function:**

```toml
[functions."webui_app/routes/sites.py::sites_save_three_url"]
ceiling = 38
rationale = "WebUI three-URL form save: validates URL fields, applies gate checks, writes config, and redirects. CC 38 grandfathered at current value; decomposition deferred to the next PR that touches this route (reduce per-branch logic into URL-validator service layer at that point)."
```

## Related

- `webui_app/helpers/_request_cache.py` — `_g_cache` implementation
- `tests/test_webui_request_cache.py` — AST enforcement gate; `_WRITE_HANDLER_SPECS` list maintained here
- `tests/test_no_complexity_regrowth.py` — `test_backstop_webui_unlisted_functions` extends CC-30 backstop to `webui_app/`
- `complexity_budget.toml` — contains grandfathered entries requiring rationale
- `docs/solutions/logic-errors/save-config-write-paths-bypass-preservation-2026-05-15.md` — explains the underlying write-path preservation contract that makes write-handler direct-call rule necessary
- `docs/solutions/best-practices/never-smoke-test-real-save-endpoints-2026-05-19.md` — companion rule: save-endpoint routes are structurally special; test them with throwaway config dirs
