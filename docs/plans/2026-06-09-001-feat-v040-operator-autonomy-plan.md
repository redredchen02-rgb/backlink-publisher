---
date: 2026-06-09
status: active
type: feat
origin: docs/brainstorms/2026-06-09-v040-operator-autonomy-requirements.md
claims:
  paths:
    - webui_app/scheduler.py
    - webui_store/channel_status.py
    - webui_app/routes/health.py
    - pyproject.toml
    - webui_store/__init__.py
    - webui_app/templates/_tab_history.html
  shas: []
---

# feat: v0.4.0 Operator Autonomy

## Problem Frame

0.3.1 delivered the core keep-alive loop and SQLite store migration. Every
operation still requires heavy operator involvement: each publish target needs
individual clicks, keep-alive failures must be spotted and re-queued manually,
batch cross-target work means repeating the same steps N times, and credential
expiry is only discovered at publish-failure time.

The operator's job should be to express intent once and let the system execute
the repetitive loop. This plan closes the gap between "the pipeline runs" and
"the pipeline runs itself."

(see origin: docs/brainstorms/2026-06-09-v040-operator-autonomy-requirements.md)

## Requirements Coverage

| Req | Unit | Topic |
|-----|------|-------|
| R1–R4 | U7, U8 | Autopilot scheduling + frontend |
| R5–R7 | U6 | Batch target operations |
| R8–R11 | U4 | Channel credential health |
| R12–R14 | U5 | Streamlined publish defaults |
| R15–R17 | U3 | Health endpoint + dashboard card |
| R18 | U1 | CI coverage gate |
| R19 | U1 | Test tier markers |
| R20 | U2 | Test file split |

## High-Level Technical Design

### Site identity

Sites in the WebUI are keyed by `main_url` (a domain URL string from
`config.target_three_url`). There is no integer `target_id`. Throughout this
plan, "site key" means the `main_url` string value. All new stores and routes
that reference a site use `site_url` / `site_key` parameter names.

### Autopilot execution model

Autopilot intent is stored in `schedule_store` alongside the existing draft
schedule entries, using a new `autopilot_targets` key in the store blob. On
every startup, `_restore_scheduled_jobs()` reads this key and registers one
APScheduler `interval` job per enabled site. The job calls a new
`run_keepalive_for_site(site_url)` synchronous function extracted from
`keepalive_job.py` (see U7 for extraction approach).

```
startup
  ↓ _restore_scheduled_jobs()
    ↓ read schedule_store["autopilot_targets"]
      ↓ for each enabled site → _scheduler.add_job(
            _keepalive_cycle_job(site_url),
            trigger='interval', seconds=interval,
            id=f'autopilot_{hash(site_url)}',
            replace_existing=True
        )

_keepalive_cycle_job(site_url)
  1. write run record to history_store with extra_json={"source":"autopilot"}
  2. call run_keepalive_for_site(site_url) — new synchronous primitive in keepalive_job.py
  3. on failure → write error to history_store
               → set dashboard_alert flag in schedule_store
  4. on store.update() failure → _scheduler.remove_job() rollback
     (split-state guard — see docs/solutions/ux-honesty/webui-false-success-resolution.md)
```

Note: `_scheduler` is a module-level singleton in `webui_app/scheduler.py`;
access via `from webui_app.scheduler import _scheduler` (no `get_scheduler()`
accessor exists — do not invent one).

### Health endpoint response shape

```json
GET /health → 200 / 503
{
  "healthy": true,
  "webui": "ok",
  "last_pipeline_run": "2026-06-09T12:34:56Z",   // null if never
  "scheduler_running": true,
  "scheduler_job_count": 3,
  "channels": {
    "medium": "bound",
    "blogger": "expired",
    "velog": "unreachable"
  },
  "degraded_reasons": []
}
```

503 when any channel is `"expired"` or `"unreachable"`, or scheduler is not
running, or last_pipeline_run is null. All fields always present.

Channel statuses come from `channel_status_store.list_all()` (the `.status`
field on each row). `scheduler_running` reads `_scheduler.running` and
`_scheduler.get_jobs()` directly (module-level singleton import).

### Batch operation flow

The existing `QueueSqliteStore` / `_process_queue_job` is a publish-only queue
and cannot dispatch `keep_alive`, `recheck`, or `channel_health` tasks without
breaking its schema. Batch operations use a **separate lightweight table** in
`webui.db` — not the publish queue.

```
POST /sites/batch-queue  { site_urls: [...], operation: "keep_alive" }
  ↓ write N rows to batch_ops table in webui.db
      (site_url, operation, status="pending", created_at)
  ↓ return { queued: N }

Background APScheduler job `_drain_batch_ops` (one-minute interval):
  - reads one pending row per tick
  - dispatches: keep_alive → run_keepalive_for_site(site_url)
               recheck    → ReCheckService.run(site_url)
               channel_health → probe_channel_liveness(channel)
  - updates row status to "done" or "failed"

Frontend polls GET /sites/batch-status (new endpoint) for per-site progress.
```

This keeps the existing publish queue untouched and avoids throttle collisions
by serialising through a single-worker APScheduler job.

## Implementation Units

### Unit 1 — Pre-existing test repair + CI coverage gate
**Prereq:** none — land this first, it unblocks the 80% gate for all later units.

**Problem:** 34 pre-existing test failures prevent the coverage gate from
landing cleanly. The failures are old CLI entry-point regressions from the
`weights` consolidation (0.3.1).

**Files:**
- `pyproject.toml` — change `fail_under = 0` → `fail_under = 80` (line 127)
- `.github/workflows/ci.yml` — add a "Full-suite coverage gate" step to the
  integration job that runs pytest without `-m` filter, with `--cov-fail-under=80`
  on the CLI (NOT in addopts — see docs/solutions/test-failures/
  strict-markers-addopts-noop-conftest-module-load-2026-06-01.md).
  The unit-only run measures ~73% because it excludes integration tests; the
  83.2% baseline was measured on the full suite.
- `tests/test_cli_weights.py` — fix entry-point references (9 tests)
- `tests/test_cli_show_optimization_state.py` — fix entry-point refs (6 tests)
- `tests/test_collect_signals.py` — fix entry-point refs (4 tests)
- `tests/test_optimization_rules.py` — fix entry-point refs (4 tests)
- `tests/test_optimization_e2e.py` — fix entry-point refs (2 tests)
- `tests/test_cli_timing_regression.py` — fix import timing (1 test)
- `tests/test_footprint_engine.py` — fix hash-seed sensitive test (1 test)
- `tests/test_keepalive_plist.py` — fix working-dir assertion (1 test)
- `tests/test_webui_inject_platforms_non_empty.py` — fix cold-boot test (1 test)
- Top 10 highest-value test files — add `__tier__ = "unit"` or `"integration"`
  module-level attribute where missing (R19)

**Approach for entry-point failures:** Diagnose each failure class before
patching. Expected root cause: tests call the old `backlink_publisher.cli.weights`
entry or import paths deleted in the consolidation. Patch the import path or
mock target in each test to match the current `weights` dispatcher.

Note on `pyproject.toml fail_under`: set to `80` for local `pytest --cov` runs
without the explicit CLI flag. CI uses `--cov-fail-under=80` on the command
line for the reasons documented in the test-failures solution; both settings
are needed so local and CI behaviour are consistent.

**Test scenarios:**
- `pytest tests/ -m unit` passes at ≥80% coverage after fix
- All 34 formerly-failing tests pass
- `pytest tests/ -m unit --co | grep -c "no mark"` returns 0 for top-10 files
  (tier markers applied)

---

### Unit 2 — Split `test_webui_route_contract.py`
**Prereq:** Unit 1 (coverage gate must be green before this reorganization)

**Problem:** Single file is 1791 SLOC, 28 test classes — violates the 500-SLOC
guidance ceiling and makes CI noise hard to diagnose.

**Current class → target file mapping:**

| Target file | Classes |
|-------------|---------|
| `test_webui_core_routes.py` | TestGetRoutes, TestCsrfGuard, TestSecretLeakRegression |
| `test_webui_pipeline_routes.py` | TestPipelineRoutes, TestCheckpointRoutes, TestPreviewRoutes |
| `test_webui_history_routes.py` | TestHistoryRoutes, TestHistoryBulkRoutes, TestDraftRoutes |
| `test_webui_settings_routes.py` | TestSettingsRoutes, TestBindRoutes, TestChannelBindingAPIRoutes, TestTokenPasteRoutes, TestChannelBindSaveRoutes, TestNotionTokenRoutes |
| `test_webui_sites_routes.py` | TestSitesPostRoutes, TestCampaignRoutes, TestScheduleRoutes, TestPrQueueRoutes |
| `test_webui_content_routes.py` | TestUrlVerifyRoutes, TestSeoVizRoutes, TestLlmRoutes, TestEquityLedgerRoutes, TestEquityLedgerOptRoutes |
| `test_webui_service_routes.py` | TestKeepAliveRoutes, TestQueueDashboardRoutes, TestCopilotRoutes, TestMetricsRoutes, TestHealthActionRoutes, TestVelogApiRoutes |

**Files:**
- `tests/test_webui_route_contract.py` — delete (or keep as thin re-export shim
  if plan-claims-gate requires it; check with `plan-check` before deleting)
- 7 new `tests/test_webui_*.py` files (net-new, exempt from SHA claims)

**Decisions:**
- Shared fixtures (`_isolated_config_dir`, `_app`, `csrf`) move into a new
  `tests/conftest_webui.py` or into each split file's module scope — whichever
  avoids circular conftest imports. Check existing `conftest.py` first.
- Each split file gets `__tier__ = "integration"` (all route tests hit the
  Flask test client).
- SLOC of each split file must be verified with radon before merging; none
  may exceed 500.
- Shared fixtures (`_isolated_config_dir`, `_isolated_webui_state`,
  `_no_real_subprocess`, `client`, `csrf_client`) must move into the
  **existing** `tests/conftest.py` — pytest only auto-discovers files named
  exactly `conftest.py`; a `conftest_webui.py` file is ignored by pytest's
  fixture resolution. Do not create a `conftest_webui.py`.

**Test scenarios:**
- `pytest tests/test_webui_*.py` passes with same pass/fail count as original
- Each new file is ≤500 SLOC (`python -m radon raw -s tests/test_webui_*.py`)
- `pytest tests/ -m integration` still collects the same route contract tests

---

### Unit 3 — `GET /health` endpoint + dashboard health card (R15–R17)
**Prereq:** Unit 1 (coverage gate green)

**Files:**
- `webui_app/routes/health.py` — add `GET /health` JSON route to existing
  `health_bp` blueprint (file already has `/ce:health` HTML route)
- `webui_app/services/health_projection.py` — add or extend
  `compute_health_json()` that returns the payload shape defined above;
  reuse existing `project_platform_health()` for channel statuses
- `templates/dashboard.html` or equivalent — add health summary card driven
  by the same data (R17); card polls `GET /health` via `fetchJson` from api.js
- `tests/test_webui_health_routes.py` (new, or add to a split file from U2)

**Key decisions:**
- `/health` must be excluded from the global CSRF guard (it's GET, so the guard
  already skips it — confirm in `webui_app/__init__.py`)
- Loopback gate: the existing health blueprint is loopback-only by default;
  document that `BACKLINK_PUBLISHER_ALLOW_NETWORK=1` extends this (R16)
- `scheduler_running` / `scheduler_job_count`: read from
  `get_scheduler().running` and `len(get_scheduler().get_jobs())`
- `last_pipeline_run`: query `history_store` for the most recent entry
- `channels`: iterate `channel_status_store.list_all()`
- 503 conditions: any channel `expired`/`unreachable`, scheduler not running,
  or last_pipeline_run is None

**Test scenarios:**
- `GET /health` returns 200 with all expected JSON keys
- Returns 503 when channel_status_store has an expired entry
- Returns 503 when mock scheduler is not running
- Dashboard card renders without 500 error
- Response arrives within 500 ms under normal test-client load (timing
  assertion optional; document as a manual post-ship check)

---

### Unit 4 — Channel credential health: TTL badge + liveness probe + re-bind shortcut (R8–R11)
**Prereq:** Unit 1

**Files:**
- `webui_store/channel_status.py` — add `credential_age_days()` helper that
  computes days since `bound_at`; add `is_near_expiry(threshold_days=7)` that
  uses `credential_age_days()` (R8, R11 — `bound_at` already stored)
- `webui_app/services/credential_service.py` (existing) — add
  `probe_channel_liveness(channel: str) -> Literal["alive","expired","unreachable"]`
  that dispatches to per-channel probe functions and **translates their
  heterogeneous return dicts** to the three-literal schema:
  - `_get_blogger_token_status()` returns `{"state": "none"|"ok"|"expiring"|"expired"}`
    → translate `"ok"/"expiring"` → `"alive"`, `"expired"` → `"expired"`,
      `"none"` → `"unreachable"`
  - `_get_velog_status()` returns `{"state": "err"|"ok"|"warn"|...}`
    → translate `"ok"/"warn"/"fresh"` → `"alive"`, `"permission_denied"` → `"expired"`,
      `"err"` → `"unreachable"`
  - Other channels: fall back to `channel_status_store.get_status(channel).status`
  Read each probe function in `channel_probes.py` before implementing — the
  return shapes vary by channel.
- `webui_app/routes/settings.py` or a new `routes/channel_probes.py` — add
  `POST /settings/channels/<channel>/probe-liveness` route that calls
  `probe_channel_liveness()` and returns `{"status": "alive"|"expired"|"unreachable"}`
  (R9)
- `templates/_settings_channel_*.html` — add credential-age badge next to
  each channel binding status; highlight in amber when `is_near_expiry()` (R8)
- `templates/_tab_history.html` or error card partial — add one-click
  "Re-bind now" link in `AuthExpiredError` history entries that opens the
  bind modal for the affected channel (R10); use `data-action="open-bind-modal"`
  + delegated listener per frontend anti-rot rules
- `tests/test_channel_health.py` (new)

**Key decisions:**
- TTL estimate is best-effort; `bound_at` timestamp is the only signal for
  non-OAuth adapters. Surface as "bound N days ago" badge, not as a guarantee.
- Probe endpoint must be CSRF-protected (it's POST) — no exclusion needed,
  the global guard covers it automatically.
- `credential_age_days()` returns `None` when `bound_at` is None (never bound).
- Re-bind shortcut opens existing bind modal in settings — no new modal needed.

**Test scenarios:**
- `is_near_expiry()` returns True when `bound_at` is 8 days ago, False at 6 days
- `probe_channel_liveness("blogger")` returns one of the three literals
- `POST /settings/channels/blogger/probe-liveness` returns 200 `{"status":"alive"}`
  when probe returns alive
- History error card renders the Re-bind link when `error_class == "AuthExpiredError"`
- `credential_age_days()` returns None when `bound_at` is None

---

### Unit 5 — Publish defaults store + quick-publish button (R12–R14)
**Prereq:** Unit 1

**Files:**
- `webui_store/publish_defaults.py` (new — net-new, exempt from SHA claims) —
  `PublishDefaultsSqliteStore` following the `SqliteStore` base class pattern
  in `webui_store/`. Schema: single row per user (key/value), storing
  `last_platforms` (JSON list) and `last_target_ids` (JSON list)
- `webui_store/__init__.py` — add `publish_defaults_store` singleton following
  the `_LazyStore` pattern
- `webui_app/routes/publish_defaults.py` (new — net-new blueprint, register
  in `webui_app/routes/__init__.py`'s `register_blueprints()`) — expose
  `GET /publish/defaults` and `POST /publish/quick`; on successful publish
  start in the existing batch/pipeline routes, write used platforms + targets
  to `publish_defaults_store` (hook the write into the existing
  `/ce:batch` or queue-task route, not a separate publish.py)
- `templates/sites.html` or site detail page — add quick-publish button per
  row; button calls `GET /publish/defaults` to check if defaults exist, then
  either starts publish directly or opens the full flow (R13)
- `templates/publish_progress_overlay.html` (or existing overlay) — ensure
  real-time per-platform status is shown without page navigation (R14);
  confirm existing overlay already does this or extend it
- `tests/test_publish_defaults.py` (new)

**Key decisions:**
- Store persists in `webui.db` (existing SQLite DB used by all webui stores)
  following the same `SqliteStore` base class — no new database file.
- `last_platforms` and `last_target_ids` are JSON blobs in a `settings` key/
  value table or a dedicated `publish_defaults` table — match whatever schema
  pattern `schedule_store` uses after the 0.3.1 migration.
- Quick-publish button shows spinner immediately (frontend long-op pattern
  from docs/solutions/ui-bugs/webui-blocking-subprocess-and-missing-progress-
  feedback-2026-05-12.md).
- If no defaults exist, button opens the full publish flow modal (R13 fallback).

**Test scenarios:**
- Writing defaults and reading them back returns the same platforms/targets
- `POST /publish/quick` with no stored defaults returns 400 "no defaults saved"
- `POST /publish/quick` with defaults starts a run and returns 202
- Defaults survive a store reload (persist across Python process restart)
- `GET /publish/defaults` returns `{"platforms": [...], "target_ids": [...]}`

---

### Unit 6 — Batch target operations (R5–R7)
**Prereq:** Unit 1

**Files:**
- `templates/sites.html` — add multi-select checkbox column + bulk-action-bar
  (reuse `_tab_history.html` `form#draftBulkForm` + `bulk-action-bar` pattern
  directly; bulk-action-bar already has the JS + CSS for this)
- `webui_store/batch_ops.py` (new — net-new SqliteStore for batch operations)
  — schema: `(id, site_url, operation, status, created_at, updated_at)`;
  operations: `keep_alive`, `recheck`, `channel_health` (not publish — publish
  goes through the existing publish queue). Do NOT extend `QueueSqliteStore`
  or `_process_queue_job`; the publish queue schema is incompatible.
- `webui_app/routes/batch_sites.py` (new — net-new blueprint) — add
  `POST /sites/batch-queue` accepting `{ site_urls: [...], operation: str }`,
  writing rows to `batch_ops` store; add `GET /sites/batch-status` returning
  per-site status for the frontend to poll; register blueprint in
  `webui_app/routes/__init__.py`
- `webui_app/scheduler.py` — register a `_drain_batch_ops` APScheduler interval
  job (60s) that processes one pending batch row per tick, dispatching to the
  appropriate service function; honours platform throttle settings
- `static/js/sites.js` — wire checkboxes to bulk-action-bar via
  `data-action` + delegated listener; poll `GET /sites/batch-status` for
  progress
- `tests/test_webui_batch_routes.py` (new)

**Key decisions:**
- The existing `QueueSqliteStore` and `_process_queue_job` are publish-only;
  creating a separate `batch_ops` table is the safe path that avoids breaking
  the publish queue schema (R7 throttle respected by single-worker drain job).
- `operation` must be one of `["keep_alive", "recheck", "channel_health"]`;
  publish is excluded — operators use quick-publish (U5) for that.
  Server rejects unknown values with 422.
- Checkbox state is local to the page session — no persistence needed.
- Per-site progress is visible via `GET /sites/batch-status` polling
  (no WebSocket needed; existing history panel uses the same pattern).

**Test scenarios:**
- `POST /sites/batch-queue` with 3 site_urls writes 3 rows to batch_ops store
- Unknown operation returns 422
- Empty `site_urls` returns 400
- `GET /sites/batch-status` returns per-site status rows
- `_drain_batch_ops` processes one row per tick and updates status to
  `"done"` or `"failed"` accordingly

---

### Unit 7 — Autopilot backend (R1–R4)
**Prereq:** Unit 1 (coverage gate). Unit 6 is NOT a prereq — autopilot dispatches
directly to `run_keepalive_for_site()`, not through the batch_ops queue.

**Files:**
- `webui_app/services/keepalive_job.py` — extract a new
  `run_keepalive_for_site(site_url: str) -> KeepAliveResult` synchronous
  function. The existing `KeepaliveJobRegistry.start_recheck()` spawns its own
  thread and has no per-site filter — it cannot be called from an APScheduler
  thread. The new function must: (a) acquire a per-site lock to prevent
  concurrent runs, (b) run the recheck cycle synchronously for one site only,
  (c) return a structured result. Read `KeepaliveJobRegistry` carefully before
  extracting — the locking pattern (`_running` guard and `UsageError`) must be
  preserved for the single-site case.
- `webui_store/schedule_store.py` or the `SettingsSqliteStore` equivalent —
  add `autopilot_targets` key to the settings blob; schema per site:
  `{ enabled: bool, interval_seconds: int, last_run: str|null, alert_pending: bool }`
- `webui_app/scheduler.py` — extend `_restore_scheduled_jobs()` to scan
  `autopilot_targets` and register one `interval` job per enabled site using
  `_keepalive_cycle_job`; add `_keepalive_cycle_job(site_url)` function that
  calls `run_keepalive_for_site(site_url)`. Access scheduler via `_scheduler`
  (module-level singleton — no `get_scheduler()` wrapper exists).
- `webui_store/history_store.py` or equivalent — autopilot run records write
  `{"source": "autopilot"}` into the `extra_json` field (JSON blob approach,
  no schema migration needed — the templates must read `extra_json` to display
  the source badge). Confirm the history row schema supports `extra_json`
  before writing; add it if missing.
- `tests/test_autopilot_scheduler.py` (new)

**Key decisions:**
- Job ID convention: `f'autopilot_{site_url}'` or a URL-safe hash —
  allows targeted `_scheduler.remove_job()` when autopilot is disabled for
  one site. Use consistent slugification (e.g., `site_url.replace("://","_")`)
  so the job ID is deterministic across restarts.
- Global pause (R4): store a `maintenance_mode: bool` flag in `schedule_store`;
  `_restore_scheduled_jobs()` skips autopilot registration when set; individual
  per-site config is preserved.
- Split-state rollback (critical): wrap `schedule_store.update()` +
  `_scheduler.add_job()` in try/except; on scheduler failure, call
  `schedule_store.update()` again to revert the enabled flag and return a 500
  to the caller.
- Alert flag: when a cycle ends with unresolved failures, set
  `alert_pending: true` in the site's autopilot config; the dashboard reads
  this flag to render the error banner (R3).
- Misfire grace: the existing scheduler uses `misfire_grace_time=3600` — jobs
  missed during maintenance mode still run within 1 hour of re-enabling.

**Test scenarios:**
- `_restore_scheduled_jobs()` registers N interval jobs when N sites are
  enabled in `autopilot_targets`
- Disabling autopilot removes the job from the scheduler
- `_keepalive_cycle_job` writes history entry with `extra_json={"source":"autopilot"}`
- `_keepalive_cycle_job` sets `alert_pending: true` when `run_keepalive_for_site` fails
- `_keepalive_cycle_job` does NOT set `alert_pending` on success
- Rollback: when `_scheduler.add_job()` raises, `schedule_store` is reverted to
  `enabled: false` and a 500 is returned
- Maintenance mode: `_restore_scheduled_jobs()` with `maintenance_mode: true`
  registers 0 autopilot jobs
- `run_keepalive_for_site` with a site not in config returns a graceful error
  (does not crash the APScheduler thread)

---

### Unit 8 — Autopilot frontend (R1–R4)
**Prereq:** Unit 7 (backend store + job management must exist first)

**Files:**
- `templates/sites.html` or site detail page — add per-site autopilot toggle
  (`<input type="checkbox" data-action="toggle-autopilot" data-site-url="...">`)
  and interval selector (daily / weekly / custom seconds input)
- `webui_app/routes/sites.py` — add `POST /sites/autopilot` accepting
  `{ site_url: str, enabled: bool, interval_seconds: int }` and updating
  `autopilot_targets` in schedule_store + `_scheduler` (calls Unit 7 logic)
- `templates/dashboard.html` — add persistent error banner / badge when any
  site has `alert_pending: true`; banner includes per-site detail and a
  "dismiss" action that clears `alert_pending` (R3)
- `webui_app/routes/dashboard.py` — add `POST /dashboard/autopilot-alert/dismiss`
  accepting `{ site_url: str }` to clear the alert flag for that site
- `static/js/sites.js` — handle toggle-autopilot data-action; POST to
  `/sites/autopilot`; show spinner during save; update UI on success
- `tests/test_webui_sites_routes.py` (extend split file from U2)

**Key decisions:**
- Interval picker: offer `daily` (86400s), `weekly` (604800s), and a numeric
  custom input in seconds. Validate server-side: minimum 3600s (1 hour),
  maximum 2592000s (30 days). Return 422 on out-of-range.
- The dashboard banner is a separate `<div id="autopilot-alert-banner">` in
  `base.html` or `dashboard.html`; it is hidden when no alerts are pending.
  It must NOT require a page reload to appear — the dashboard route must
  always include current alert state from `schedule_store`.
- "Dismiss alert" clears `alert_pending` but does NOT disable autopilot (R4).

**Test scenarios:**
- `POST /sites/autopilot` with `enabled=true` returns 200 and the site
  appears in `schedule_store["autopilot_targets"]`
- `POST /sites/autopilot` with `interval_seconds=3599` returns 422
- Dashboard route context includes alert data when any site has `alert_pending: true`
- `POST /dashboard/autopilot-alert/dismiss` clears the flag for that site
- Toggle with a scheduler failure returns 500 and store is rolled back
  (rollback from Unit 7 verified end-to-end here)

---

## Test Infrastructure Notes (R18–R20)

- **Coverage gate location**: `--cov-fail-under=80` belongs in the CI yml
  command line, not in `[tool.pytest.ini_options].addopts`. The conftest module
  load order silences addopts-level threshold flags
  (see origin: docs/solutions/test-failures/strict-markers-addopts-noop-
  conftest-module-load-2026-06-01.md).
- **Tier markers**: use `__tier__ = "unit"` / `"integration"` as a module-level
  attribute (not decorator) — this is the existing repo convention.
- **Coverage source**: `source = ["backlink_publisher"]` covers the src/ package
  only; `webui_app/` and `webui_store/` are measured via the test suite hitting
  them but are not in the source target. This is intentional.

## Risks

| Risk | Mitigation |
|------|-----------|
| 34 pre-existing failures mask new breakage | Fix all in U1 before gate lands |
| APScheduler split-state on autopilot toggle | Explicit rollback logic in U7 (per institutional learning) |
| `run_keepalive_for_site` extraction breaks existing thread-safety model | Read `KeepaliveJobRegistry` locking carefully before extracting; preserve `_running` guard |
| Batch ops starvation (long sites block later items) | `_drain_batch_ops` one-row-per-tick; document known limit |
| Channel TTL estimate misleads operators | Surface as "bound N days ago" not "expires in N days" |
| U2 split breaks existing import paths in conftest | Verify shared fixtures before deleting original file |
| `test_webui_route_contract.py` is in claims of other plans | Run `plan-check` on all active plans before deleting the file |

## Success Criteria (from origin doc)

- Operator configures autopilot for all active targets in under 2 minutes,
  then needs no WebUI interaction for a normal maintenance week.
- Credential expiry surfaced before publish failure ≥80% of the time for
  OAuth-based adapters.
- Batch keep-alive for 10 targets via a single operator action.
- `/health` returns a useful response within 500 ms under normal load.
- CI coverage gate active and green on main before v0.4.0 ships.

## Sequencing

```
U1 (test repair + coverage gate)
  ↓
U2 (test file split)   U3 (health endpoint)   U4 (channel health)   U5 (publish defaults)   U6 (batch ops)   U7 (autopilot backend)
                                                                                                                        ↓
                                                                                                              U8 (autopilot frontend)
```

U2–U7 can all land in any order after U1 (U7 is no longer gated on U6 —
autopilot dispatches directly, not through the batch_ops queue). U8 requires
U7 to be complete first.

## Outstanding Questions (Deferred to Implementation)

- [Affects R8][Technical] Which OAuth adapters expose a reliable credential
  expiry signal (`expires_at`, refresh timestamp)? Enumerate them in
  `webui_app/helpers/channel_probes.py` to set realistic scope for the TTL
  badge text.
- [Affects R20][Needs research] Verify that `test_webui_route_contract.py`
  is not referenced as a `claims:` path in any active plan before deletion.
  Run `grep -r "test_webui_route_contract" docs/plans/` first.
