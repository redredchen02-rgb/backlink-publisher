# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `AGENTS.md` before non-trivial edits** — it is the authoritative contributor guide covering CI, import conventions, env vars, the adapter extension recipe, and worktree cleanup.

## Commands

```bash
# Install
.venv/bin/python -m pip install -e ".[dev]"   # pip shebang broken — use python -m pip

# Test
PYTHONPATH=src pytest tests/                  # full suite (PYTHONHASHSEED=0 set by pytest-env)
pytest tests/test_foo.py -k "bar"             # single test

# WebUI dev server
python webui.py                               # :8888

# SLOC budget check (before editing monitored files)
python -m radon raw -s src/backlink_publisher/cli/plan_backlinks/core.py
```

CI uses `py_compile` + `ast.parse` (not Black/flake8). Black/flake8 are local-only.

## Pipeline Architecture

```
seeds.jsonl → plan-backlinks → validate-backlinks → publish-backlinks
                                                 └── report-anchors / footprint / phase0-seal
```

stdout = clean JSONL; stderr = diagnostics; exit 0 on success. Full entrypoint table in `AGENTS.md`.

## Adapter Registry (adding a new platform)

One line in `publishing/adapters/__init__.py`: `register("x", XAdapter)`. The CLI argparse layer, `schema.validate_publish_payload`, throttle gating, and tier matrix all read from `publishing.registry.registered_platforms()` dynamically. **Never edit `cli/*.py` or `schema.py` when adding a platform.** Full recipe in `AGENTS.md → "Adding a new publisher adapter"`.

## Import Paths

The legacy `_LegacyPathFinder` shim was physically deleted (PR #124, `a76ab1f`). `src/backlink_publisher/__init__.py` is 13 lines, no bridge. All imports must use canonical paths:

```python
# CORRECT
from backlink_publisher.anchor.something import X
from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher.publishing.adapters.image_gen import ImageGenAdapter

# WRONG — raises ImportError
from backlink_publisher.image_gen import ImageGenAdapter
```

## WebUI Layout

- `webui_app/` — Flask app (30+ route modules, `create_app()` factory)
- `webui_store/` — state persistence (5 singletons: `history_store`, `profiles_store`, `drafts_store`, `schedule_store`, `queue_store`)
- `webui_app/services/` — backend logic (10 modules incl. 4 `copilot_*` modules)
- `templates/base.html` — owns the single `<head>`; every page `{% extends 'base.html' %}`
- `static/js/lib/` — shared ESM layer (`api.js`, `dom.js`, `profiles.js`)
- `static/css/tokens.css` — single `:root` token source

CSRF guard (`_global_csrf_guard`) enforces tokens on every POST/PUT/PATCH/DELETE. Tests opt out via `app.config['CSRF_ENABLED'] = False`.

**Frontend anti-rot (enforced — do not regress):**
- No inline `on*` handlers — use `data-action="…"` + delegated `addEventListener`
- No `window.*` globals as API — use DOM `CustomEvent` for cross-component signals
- No untrusted `${…}` into `innerHTML` — use `createElement`/`textContent`/`esc()`
- `readCsrf()` reads `<meta>` per call — never cache in a module const
- Bootstrap stays a classic non-`defer` head script

## Complexity Budgets

Two TOML files gate growth:
- `monolith_budget.toml` — radon SLOC ceilings per file (`tests/test_no_monolith_regrowth.py`)
- `complexity_budget.toml` — cyclomatic-complexity ceilings per function (`tests/test_no_complexity_regrowth.py`)

Both require a `rationale` ≥80 chars and must be raised in the **same PR** that exceeds them.

## Config & Secrets

User config: `~/.config/backlink-publisher/config.toml`. LLM/API keys: `~/.config/backlink-publisher/llm-settings.json` (must be `0o600`). Use `safe_write.atomic_write` for writes. FRW token stored via `frw-login` CLI, loaded via `backlink_publisher._util.secrets.load_frw_token()`.

Key env vars: `PYTHONHASHSEED=0` (required for footprint tests), `BACKLINK_PUBLISHER_CONFIG_DIR`, `BACKLINK_NO_FETCH_VERIFY`, `BACKLINK_PUBLISHER_ALLOW_NETWORK=1` (WebUI off-loopback).
