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

- `webui_app/` — Flask app (36 route modules, `create_app()` factory), including `webui_app/api/` (the `/api/v1/*` seam layer — see ARCHITECTURE.md and D2/C1b for its bare-except cleanup work)
- `webui_store/` — state persistence. **10** `_LazyStore`-backed singleton stores total (live-recomputed 2026-07-02, method: `grep -rn "_LazyStore(" webui_store/*.py`; supersedes a stale "9" figure that missed one): the 8 declared in `webui_store/__init__.py` (`history_store`, `profiles_store`, `drafts_store`, `schedule_store`, `queue_store`, `campaign_store`, `publish_defaults_store`, `batch_ops_store`), plus `channel_status_store` (`webui_store/channel_status.py`), plus `verify_health_store` (`webui_store/verify_health.py`) — a pre-existing `_LazyStore` singleton that was never re-exported through `__init__.py.__all__` and so was previously left out of the count. (A separate, not-yet-landed plan, `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`, would add an 11th store, `webui_store/error_reports.py` — it has not landed in this worktree/repo as of this count, so it is not included here.)
- `webui_app/services/` — backend logic (22 modules: bind jobs, browser login, recheck/keep-alive, alerting, app_meta, 4 `copilot_*` advisory modules, credential/oauth services, health projection, settings, survival, SEO viz, medium liveness, pipeline, themed-content, url-verify throttle, `_keepalive_engine`)
- `templates/base.html` — owns the single `<head>`; every legacy Jinja page `{% extends 'base.html' %}`
- `static/js/lib/` — shared ESM layer for legacy Jinja pages (`api.js`, `dom.js`, `profiles.js`)
- `static/css/tokens.css` — single `:root` token source, shared by both frontends

CSRF guard (`_global_csrf_guard`) enforces tokens on every POST/PUT/PATCH/DELETE. Tests opt out via `app.config['CSRF_ENABLED'] = False`.

### Dual-frontend: Vue 3 SPA (primary) + legacy Jinja (fallback)

Since v0.5.0 the primary UI is a **Vue 3 SPA** at `/app/*`, built by Vite from `frontend/` and served by Flask at a single origin (no CORS). It coexists with the legacy Jinja templates in a strangler-fig migration (see `ARCHITECTURE.md` for the full architectural writeup):

- **Flag-gated**: `BACKLINK_PUBLISHER_SPA` env var (default `"1"`; `"0"` falls back to Jinja-only, used by LITE mode).
- **Migrated routes** (13 `navItems`, all `isMigrated: true` as of the B1 SPA Route Audit, 2026-07-02): `/`, `/monitor`, `/history`, `/drafts`, `/sites`, `/schedule`, `/batch-campaign`, `/settings`, `/pr-queue`, `/survival`, `/optimization-status`, `/equity-ledger`, `/keep-alive`. Of these, `/schedule` and 7 others already 302-redirect their legacy Flask route to `/app/<page>`; **`/`, `/ce:history`, `/sites`, `/batch-campaign` have an SPA page but the Flask route does not yet redirect to it** — a known, deliberately deferred gap (flash-message query-string contracts aren't wired into the SPA yet for the first three; see the plan doc's B1 section for the full risk breakdown).
- **Jinja-only, not migrated**: `/ce:health` and its 6 sub-panels (scorecard/publish-metrics/canary/forward-path/storage/GSC) — a deliberate decision, not an oversight; `/monitor`'s SPA page consumes different (`command_center`) aggregate data, not `health.py`'s data surface.
- `frontend/` layout: `src/router/` (routes), `src/pages/` (per-page `.vue`), `src/api/` (typed Axios modules), `src/stores/` (Pinia), `src/layout/` (AppShell/SideNav/TopBar).
- Build: `cd frontend && npm ci && npm run typecheck && npm run test && npm run build` → `webui_app/spa_dist/`. CI: `.github/workflows/frontend.yml` (path-filtered) plus `ci.yml`'s `frontend-lint` job (unfiltered, typecheck+build only) — see `AGENTS.md → CI (GitHub Actions)`.

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
