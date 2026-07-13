# Recipe: binding a channel (credential lifecycle)

> Moved verbatim from `AGENTS.md` on 2026-07-13 (condensation pass). The hard invariants
> stay summarized in `AGENTS.md → Binding a channel`; this file is the full flow.

Browser-based credential binding is **orthogonal** to publisher adapters. Adding a new publish-platform follows `docs/recipes/adding-a-publisher-adapter.md`; teaching the platform's credential lifecycle to the operator-facing surface follows this recipe. Plan: `docs/plans/2026-05-19-001-feat-settings-browser-binding-plan.md`.

## Channels

The closed set lives in one place: `src/backlink_publisher/cli/_bind/channels/__init__.py::CHANNELS = frozenset({"velog", "medium", "blogger"})`. Every entry point (CLI argparse, webui routes, `AuthExpiredError` ctor, `mark_bound` / `mark_expired`) imports from there and validates membership before constructing paths or argv — defense in depth against `channel=../traversal` injection. Adding a fourth channel means: (1) extend `CHANNELS`; (2) ship its `ChannelRecipe` in `src/backlink_publisher/cli/_bind/recipes/<name>.py`; (3) CLI argparse `--channel` choices are auto-derived from `CHANNELS`.

## Entry points

- `bind-channel --channel <velog|medium|blogger>` — single binding CLI, drives a headed Playwright session, emits RECON events on stdout as JSONL, writes `<config_dir>/<channel>-storage-state.json` with mode `0600`.
- `velog-login` — transparent alias for `bind-channel --channel velog` (backwards compatibility with plan-012; prints an alias banner to stderr).

Storage state always lands inside `BACKLINK_PUBLISHER_CONFIG_DIR` (defaults to `~/.config/backlink-publisher/`). The driver writes to a temp file then `os.rename`s — partial writes never leave a half-bound file. `mark_bound` happens after the rename so a kill in between leaves the file but keeps the status as `unbound` / `expired` (next click re-binds idempotently).

## Settings UI flow

`GET /settings` shows each channel card with a binding subsection (rendered from `webui_app/templates/_settings_channel_binding.html`):

- **Badge states** (rendered via `role="status" aria-live="polite"`):
  - `已绑定 ✓` — last `mark_bound` succeeded and the storage_state file still exists on disk.
  - `已过期 ⚠` — adapter raised `AuthExpiredError` at publish time, **or** `reconcile_on_load` found the storage_state file missing on app start.
  - `未绑定` — no record in `channel-status.json`.
  - `绑定中…` — JS poller saw `status: "running"` from `GET /settings/channels/<channel>/bind/<job_id>`.
- **Re-bind button** issues `POST /settings/channels/<channel>/bind` with the page CSRF token; both routes are loopback-only (`Blueprint.before_request` rejects non-`127.0.0.1`/`::1` with 403). The button writes `sessionStorage["bind:lastChannel"]` so a page reload re-opens the same card.
- **Failed binds** map their `error_code` to a Chinese operator message via `webui_app.services.bind_job.BIND_ERROR_MESSAGES` — adding a new `error_code` requires a Chinese mapping (the `tests/test_bind_error_messages.py` gate enforces this).

## Operator script — "how do I re-bind Medium?"

1. Open the WebUI (`webui` or `python webui.py`).
2. Navigate to `/settings`, expand the Medium card.
3. Click **重新绑定**. A headed Chromium window opens; complete the Medium login.
4. The badge transitions `绑定中…` → `已绑定 ✓`. The card stays open after the page reload thanks to `sessionStorage["bind:lastChannel"]`.

Alternative CLI path: `bind-channel --channel medium` (then complete login in the headed browser).

## Publish-time auth flip

When a publish adapter hits a 401/403 it raises `AuthExpiredError(channel="...", reason="...")` (the ctor revalidates `channel ∈ CHANNELS`). The `publish_backlinks` dispatch site catches this **before** the generic `except DependencyError`, calls `webui_store.channel_status.mark_expired(exc.channel)`, writes a checkpoint row with `error_class="auth_expired"`, then exits with code 3. Because `AuthExpiredError` inherits from `DependencyError`, callers that still `except DependencyError` keep working — they just lose the channel-specific side effects.

## Velog credential lifecycle

Velog is the **adapter** in plan-012 but its **credential lifecycle** lives here; plan 2026-05-19-001 unified the standalone `velog-login` flow with the cross-channel surface (see plan-012's inline amendment, Units 3-4, for the exact contract changes).

### Velog null-after-retry diagnostics (plan 2026-05-22-004)

When `writePost` returns `null` on both the initial attempt and the silent-drop retry, the adapter runs a lightweight `currentUser` liveness probe before deciding the error class:

- **Cookie dead** (`probe_reason=no_current_user|http_4xx|probe_unreachable`) → `AuthExpiredError` → channel flips to expired → operator must re-bind.
- **Cookie alive** (`probe_reason=<username>`) → `ContentRejectedError` → row fails, batch continues, channel status unchanged. The WebUI history card shows an amber "内容被拒（Cookie 有效）" hint. **Do not re-bind** — inspect the `debug/velog-null-<article_id>.json` artifact in `config_dir` instead (0600, written by `_save_null_artifact`; contains the full response body, headers, and any GraphQL `errors[]` — none of which appear in the truncated log).
