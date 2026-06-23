# SDK layering — `core ∌ webui_app`

> Plan: `docs/plans/2026-06-22-001-refactor-embeddable-sdk-extraction-plan.md`
> Guard: `tests/test_core_no_webui_app_import.py`

## The rule

`src/backlink_publisher/` (the **core** library) must never import `webui_app`
(the Flask app). It may import `webui_store` (the state-persistence singletons),
which is a legitimate shared dependency.

```
  webui_app/  (Flask routes, services, /api/v1)  ──imports──▶  backlink_publisher (core)
  backlink_publisher (core)                       ──imports──▶  webui_store (state)
  backlink_publisher (core)                       ──✗ NEVER ──▶  webui_app
```

The dependency arrow points one way: the app depends on the library, never the
reverse. This is what makes the library **embeddable** — `import
backlink_publisher` pulls in no Flask, no routes, no web server.

## How it is enforced

`tests/test_core_no_webui_app_import.py` is an AST gate over every
`src/backlink_publisher/**/*.py`. It flags any `import webui_app` /
`from webui_app… import …`, **top-level or in-function** (the way the historical
edges hid). The allowlist is **empty** — a new entry is a layering violation to
fix, not an allowlist to grow. It keys on `webui_app` only, so `webui_store`
imports are never flagged. Because it parses the AST, the several
`"Extracted from webui_app/…"` provenance notes in core docstrings/comments are
ignored.

## The layers

| Layer | Lives in | Role |
|-------|----------|------|
| **Facade** | `backlink_publisher/__init__.py`, `sdk/__init__.py` | `import backlink_publisher` → error taxonomy (eager) + lazy `plan`/`validate`/`publish`/`dispatch`. `sdk.plan/validate/publish` are thin `payload → PipeResult` wrappers. |
| **PipelineAPI** | `sdk/api.py` | Structured `PipeResult`-returning wrapper around each pipeline stage. In-process for plan/validate/publish (API-tier); CLI subprocess only for browser-tier publish + resume. |
| **Engines** | `cli/plan_backlinks/_engine.py` (`plan_rows`), `validate/engine.py` (`validate_rows`), `cli/publish_backlinks/_engine.py` (`publish_rows`) | Pure, `SystemExit`-free compute. The CLI shells and the SDK share the SAME engine, so their output is identical by construction. |
| **CLI shells** | `cli/*.py` | argparse / I/O / config-echo banner / exit-code discipline only. Thin adapters over the engines. |
| **Shim** | `webui_app/api/pipeline_api.py`, `webui_app/helpers/cli_runner.py` | Re-export the relocated core symbols so ~15 existing webui consumers keep working unchanged (U5a). |

## Why (requirements R4 / R8)

- **R4** — remove the 3 `core → webui_app` reverse edges and lock the boundary.
  All three were severed (U2: `keepalive/chain.py` `_ensure_article` +
  `RUNTIME_STICKY_PLATFORMS`; U5a: `chain.py` `PipelineAPI` edge), and this guard
  keeps them gone.
- **R8** — the existing `/api/v1` endpoints consume the core SDK (via the shim's
  re-exported core `PipelineAPI`), with no new endpoints added.

## Browser-tier boundary

The long-lived Flask process never spawns Chrome. In-process `publish_rows` runs
**API-tier** adapters only; **browser-tier** platforms (`medium`, `velog`,
`devto`, `mastodon`) are routed by the SDK wrapper to the `publish-backlinks`
CLI **subprocess**, which owns the `ChromeAttachSession` + PID file + SIGTERM
reclaim. This contains credential exposure (no cookie-bearing Chrome profile
attached inside Flask). See `sdk/_publish_runtime.py`.
