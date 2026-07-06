# AGENTS.md — webui_app (Flask WebUI)

Flask app factory at repo root (not under `src/`). `create_app()` in `__init__.py` returns configured app with blueprints, scheduler, and CSRF guard.

Since v0.5.0 this app serves **two frontends**: the legacy Jinja templates below (`templates/`, `static/`) and a Vue 3 SPA at `/app/*` built from the sibling `frontend/` directory (Vite output lands in `webui_app/spa_dist/`, served outside `static/` to avoid route collision). The SPA is flag-gated by `BACKLINK_PUBLISHER_SPA` (default `"1"`). New pages should generally be added to the SPA rather than as new Jinja templates — see `CLAUDE.md → Dual-frontend` and `ARCHITECTURE.md → Vue 3 SPA` for the full migration state and which legacy routes still lack an `/app/*` redirect.

## Structure

```
webui_app/
├── __init__.py          # create_app() factory — CSRF guard, scheduler, blueprint registration
├── routes/              # 36 route modules, registered via register_blueprints() (count stale before 2026-07-02 recount — was previously documented as 20)
├── api/                 # /api/v1/* seam layer — 19 top-level modules (spec.py is the SSoT for the 63
│                         # registered endpoints) plus a v1/ subpackage; scanned by D2/C1b for bare-except cleanup
├── services/            # 22 modules incl. bind_job, browser_login, recheck/keep_alive/keepalive_job,
│                         # 4 copilot_* advisory modules, credential/oauth services, health_projection,
│                         # settings_service, survival, seo_viz, medium_liveness_service, pipeline_service,
│                         # work_themed_service, url_verify_throttle (count stale before 2026-07-02 — was "5")
├── helpers/             # 9 modules: _request_cache, channel_probes, channel_tiers, cli_runner, contexts, edition, history, security, url_meta
├── binding_status.py    # Channel binding badge state
├── medium_liveness.py   # Medium session health check
├── medium_login.py      # Medium login flow
├── scheduler.py         # APScheduler + job restore
├── spa_dist/             # Vite production build output for the /app/* SPA (generated, not hand-edited)
└── templates/           # Jinja2 templates (legacy frontend, being migrated to the SPA page by page)
```

## Where to look

| Task | Location |
|---|---|
| Add a new page/route | `routes/` + `register_blueprints()` auto-registers |
| Add a background service | `services/` + wire in `create_app()` startup |
| CSRF / security | `helpers/security.py` — `_global_csrf_guard` in `__init__.py` |
| Store access | `current_app.extensions['webui_stores']` or direct `webui_store.X_store` |
| Template context | `@app.context_processor` in `__init__.py` (`platforms`, `csrf_token`) |

## Conventions

- **CSRF**: Global guard on every POST/PUT/PATCH/DELETE. Tests opt out via `app.config['CSRF_ENABLED'] = False` or `WTF_CSRF_ENABLED = False`. OAuth callbacks excluded.
- **Stores**: Module-level singletons (`webui_store/`) backed by JSON files in config dir. Lazy-resolved on first access. Access via `current_app.extensions['webui_stores']` (Plan 2026-05-22 P7 C1).
- **Platform list**: Reverse-driven from `publishing.registry.registered_platforms()` — no hardcoded platform lists in templates.
- **Scheduler**: Starts automatically unless under pytest (`PYTEST_CURRENT_TEST`).
- **Binding**: Loopback-only (`Blueprint.before_request` rejects non-127.0.0.1/::1 with 403). `BACKLINK_PUBLISHER_ALLOW_NETWORK=1` for off-loopback (unsupported, emits warning).

## Anti-patterns

- Do NOT add hardcoded platform lists in templates — they come from `registered_platforms()`.
- Do NOT add inline per-route CSRF checks — the global guard covers all state-mutating verbs.
- Do NOT add modules under `services/` that duplicate `webui_store` singletons — stores are the persistence layer; services orchestrate.
- Do NOT import `webui_store` stores eagerly at module level — use `_LazyStore` or `current_app.extensions`.
