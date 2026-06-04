---
title: "feat: Validation test suite — SQLite migration, LITE edition, bind-job completeness, payload typing"
type: feat
status: completed
date: 2026-06-04
deepened: 2026-06-04
claims: {}
---

# Validation Test Suite — SQLite Migration, LITE Edition, Bind-Job Completeness, Payload Typing

## Overview

Four-area test plan covering confirmed coverage gaps across: SQLite store migration integrity (P0), LITE edition local-only attack surface (P1), bind-job async state machine completeness (P2), and Pydantic as a real publish-pipeline gate (P3). The features are already implemented; this plan adds the missing verification layer.

## Problem Frame

The SQLite store migration completed in plan `2026-06-03-008` (status: completed) — all five operational stores now use `SqliteStore`. Several failure modes have no tests: corrupt/binary/non-UTF-8 input, cross-process `update()` RMW lost-update risk. The LITE edition has basic loopback tests but lacks `::1` and `fe80::` route-level enforcement, `localhost` per-request verification, tokenless POST on real core routes, and blueprint-gating consistency. The bind job state machine lacks `TimeoutExpired→kill` coverage; `cancel` does not exist in v1. `BindJobRegistry` is a module-level in-memory singleton with no persistence. Pydantic has a confirmed divergence gap: `validate_output_payload` (legacy) does NOT check `url_mode`/`publish_mode` enum values, but `PlannedPayload` enforces them — never tested.

## Requirements Trace

- R1. SQLite migration: old store data survives intact; corrupt/binary/non-UTF-8 input starts with clean defaults; pending queue tasks survive restart; cross-process `update()` RMW behavior documented
- R2. LITE edition: `127.0.0.1`, `::1`, `localhost` accessible; LAN IP and `fe80::` rejected; Pro routes 404 regardless of fixture state; CSRF enforced on real core routes (not just structurally ordered); nav/route gating consistent
- R3. Bind job: `TimeoutExpired→kill` tested; false-success impossible; v1 in-memory limitation documented; `reap_orphans()` is a true no-op
- R4. Payload typing: `url_mode='D'` divergence exercised; every invalid input rejected with machine-readable typed error; pipeline round-trip uses typed payloads; error messages bounded and HTML-escaped

## Scope Boundaries

- Tests only — no feature implementation changes
- `history_store` excluded — SQLite migration PARKED
- `cancel`/`stop` method excluded — v1 has no such method; deferred to future feature plan
- JS frontend timing excluded — server-side state machine and HTTP route layer only
- External adapter network calls excluded — mocked by autouse fixtures
- `VACUUM INTO` / WAL snapshot restore excluded — no application code calls this

## Context & Research

### Relevant Code and Patterns

**Store layer (P0):**
- `webui_store/sqlite_base.py` — `WebUIDatabase` (WAL, `0o600`), `SqliteStore` (RLock, `update()` is load→fn→save RMW cycle; `save()` is delete-all+bulk-insert — different semantics)
- `webui_store/schedule.py`, `profiles.py`, `queue_store.py`, `drafts.py`, `campaign_store.py` — five sentinel-protected migration stores
- Existing tests: `tests/test_webui_store_schedule_sqlite.py` (corrupt JSON skip, sentinel idempotency, crash recovery)

**LITE edition (P1):**
- `webui_app/helpers/edition.py` — `LITE_HIDDEN_BLUEPRINTS = frozenset({"copilot", "seo_viz", "metrics", "pr_queue"})`
- `webui_app/helpers/security.py` — `_resolve_bind_host()`, `_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})`. Route enforcement checks `request.remote_addr` NOT Host header.
- `webui_app/__init__.py` — `_global_csrf_guard` registered **before** `_lite_surface_gate` (E3 invariant); `_restore_global_state_net` is function-scoped and operates on `webui.app` singleton only
- Route enforcement pattern: `tests/test_webui_bind_routes.py` line 171 — `environ_overrides={'REMOTE_ADDR': '10.0.0.5'}` (NOT `headers={'HOST': ...}`)
- Existing tests: `tests/test_webui_lite_loopback_enforced.py`, `tests/test_webui_lite_nav_surface.py`, `tests/test_webui_csrf_ordering.py`, `tests/test_conftest_state_net.py` (CSRF restore already proven)

**Bind job (P2):**
- `webui_app/services/bind_job.py` — `BindJobRegistry` module-level singleton (`registry = BindJobRegistry()` line 226); purely in-memory `dict[str, BindJob]`; `_drain_stdout` calls `proc.wait(timeout=10)` in `finally` block AFTER `for line in proc.stdout` loop exits; `reset_for_tests()` clears `_jobs`
- `webui_app/routes/bind.py` — `POST .../bind` starts; `GET .../bind/<job_id>` polls
- Existing tests: `tests/test_webui_bind_job_service.py` (`_FakeProc`, `_wait_until`; `TestRegistryStart::test_concurrent_bind_same_channel_rejected` already covers duplicate-start)

**Payload / schema (P3):**
- `src/backlink_publisher/_payload_types.py` — Pydantic v2 `PlannedPayload`: `url_mode ∈ {A, B, C}`, content_html ≤1 MiB
- `src/backlink_publisher/_schema_output.py` — `validate_output_payload` (legacy): does NOT check `url_mode`/`publish_mode` enum — confirmed divergence gap
- `webui_app/api/pipeline_api.py` — `publish()` via `run_pipe_capture` (returns dict, never raises); existing mock pattern: `side_effect=Exception(stderr)` (see `test_webui_typed_error_surfacing.py` line 40)
- `webui_app/routes/pipeline.py` — `{{ publish_error }}` autoescaped by Flask/Jinja default (confirmed); no `| safe` annotation

### Institutional Learnings

- **Negative assertion trap**: pair every `assert old_json_not_present` with positive complement — row count + semantic round-trip (`docs/solutions/test-failures/inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md`)
- **CONFIG_DIR pollution**: never `del os.environ[...]` — always `monkeypatch.setenv`/`monkeypatch.delenv` (`docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`)
- **Cross-process RMW**: `threading.Barrier(2)` falsely passes — use two OS `subprocess.run()` processes (memory: `atomic-write-not-cross-process-rmw-safe.md`)
- **Typed error envelope**: every `ValidationError` path must emit `__BLP_ERR__` JSON on stderr (`docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md`)
- **False-success trap**: running job must not return success before completion (`docs/solutions/ui-bugs/webui-blocking-subprocess-and-missing-progress-feedback-2026-05-12.md`)
- **HALF_OPEN dead code**: plant circuit state with `circuit.trip()` directly (memory: `reliability-policy-circuit-facts.md`)

## Key Technical Decisions

- **New file per area**: each of the 8 units creates its own new test file. Risk: Units 3, 4, 8 each call `create_app().test_client()` independently — per-file setup must stay synchronized with `webui_app/__init__.py` factory contract.
- **`subprocess.run` for cross-process safety (Unit 2)**: two OS processes required — `threading.Barrier` falsely passes. Env inheritance: `_isolate_user_dirs` uses `os.environ` direct mutation; capture `env = {**os.environ, "PYTHONHASHSEED": "0"}` INSIDE test body after fixtures run. Use `update()` (RMW) not `save()` (delete-all) — correct method for the known cross-process risk.
- **`monkeypatch` exclusively**: no raw `os.environ[...] =` or `app.config[...] =` in any new test file. CSRF contamination meta-test **removed** (duplicates `test_conftest_state_net.py`; architecturally broken — `_restore_global_state_net` only cleans `webui.app` singleton, not a local `create_app()` instance).
- **`REMOTE_ADDR` not `HOST` header for route enforcement**: `_enforce_loopback()` checks `request.remote_addr`. Use `environ_overrides={'REMOTE_ADDR': '...'}` — NOT `headers={'HOST': '...'}`.
- **`url_mode='D'` as divergence payload**: `canonical_url` injection-char check is IDENTICAL in both legacy and Pydantic (same regex) — NOT a divergence. `url_mode`/`publish_mode` enum values are not checked by `validate_output_payload` — confirmed real gap.
- **`_HangingProc` subclass required for Unit 5**: existing `_FakeProc.wait()` ignores `timeout` — cannot trigger `TimeoutExpired→kill`. `_HangingProc` needs: (1) finite stdout (empty iterator); (2) `wait(timeout=N)` raises `TimeoutExpired`; (3) `wait(timeout=None)` returns `-9`. The hang is in process exit, not stdout.
- **Platform alias via `supported_platforms()` with `importorskip`**: `pytest.importorskip("backlink_publisher.publishing.adapters")` at module top — prevents collection-time `ImportError` blocking entire file.
- **`__tier__` marker**: `"unit"` for store/payload tests; `"integration"` for route/cross-layer tests.

## Open Questions

### Resolved During Planning

- **`::1` route test**: use `environ_overrides={'REMOTE_ADDR': '::1'}` on test client (not `HOST` header); no OS socket bind needed
- **`history_store` scope**: excluded — migration PARKED
- **JS polling scope**: excluded — server-side and HTTP route layer only
- **`BindJobRegistry` model**: module-level singleton, purely in-memory, `reset_for_tests()` is test hook, no persistence
- **Divergence gap candidate**: `url_mode='D'` — `validate_output_payload` confirmed NOT to check enum values; `canonical_url` uses identical regex in both validators (not a gap)
- **CSRF meta-test removed**: `test_conftest_state_net.py` already proves `_restore_global_state_net` on `webui.app` singleton; `create_app()` local instance not managed by that fixture — meta-test would be architecturally broken

### Deferred to Implementation

- **Unit 3 LAN IP behavior**: verify whether `_resolve_bind_host(LAN_IP)` raises `RuntimeError` or returns loopback; assert actual contract
- **Unit 3 launcher import-identity**: verify `webui.py` exposes `_resolve_bind_host` as module-level attribute; if local import, substitute AST check
- **Unit 5 duplicate-start**: `TestRegistryStart::test_concurrent_bind_same_channel_rejected` already covers this — confirm before writing any duplicate
- **Unit 8 validation warning payload**: read `validate_and_convert_output` for warning-returning conditions; `pytest.skip` if none found
- **channel_status_store (Unit 1)**: confirm whether it has existing migration edge-case coverage or should be added as sixth store

## High-Level Technical Design

> *Directional guidance for review, not implementation specification.*

```
P0 ──┬── Unit 1: Store migration edge cases (5 stores, single process)
     └── Unit 2: Cross-process update() RMW documentation

P1 ──┬── Unit 3: Host enforcement matrix (127.0.0.1, ::1, localhost, LAN, fe80::)
     └── Unit 4: Route gating + tokenless POST CSRF enforcement

P2 ──┬── Unit 5: Bind job TimeoutExpired→kill + false-success
     └── Unit 6: Bind job in-memory boundary + reset  [uses U5 patterns]

P3 ──┬── Unit 7: url_mode divergence + typed error envelope
     └── Unit 8: WebUI pipeline round-trip + error surfacing + HTML escaping  [uses U7 patterns]
```

Units 1, 2, 3, 4, 5, 7 are independent. Units 6 and 8 use preceding unit patterns.

## Implementation Units

- [x] **Unit 1: SQLite store migration edge cases**

**Goal:** Corrupt/binary/non-UTF-8 input files, empty startup for all five stores, queue pending-task recovery.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_store_migration_edge_cases.py`

**Approach:**
- `_store(tmp_path, StoreClass)` helper using `monkeypatch.setenv` for `BACKLINK_PUBLISHER_CONFIG_DIR`
- Corrupt input: write raw bytes (`b'\xff\xfe\x00\x01'`) to JSON path before `migrate_from_json`; assert sentinel NOT written, store returns empty default
- Non-UTF-8 JSON: write valid JSON byte-encoded in latin-1; same safe-skip behavior
- Empty startup: no JSON, no SQLite; assert documented empty default
- Queue recovery: write JSON with one `{"status": "pending"}` task → `migrate_from_json` → construct SECOND instance pointing at same `config_dir` and call `poll_next()` (do NOT call `migrate_from_json` on second instance — sentinel already written)
- Pair every absent-file assertion with positive SQLite content assertion

**Patterns to follow:**
- `tests/test_webui_store_schedule_sqlite.py` — `TestStartupMigration`, `_corrupt_json` helper, sentinel + `.json.migrated` pairing

**Test scenarios:**
- Happy path: `ScheduleSqliteStore.migrate_from_json` with well-formed JSON → row in settings table, sentinel written, original renamed; second instance reads back original values
- Happy path: empty startup for each of five stores → documented empty default, no exception
- Edge case: binary bytes at JSON path → migration skips; sentinel NOT written; original untouched; empty default returned
- Edge case: latin-1 encoded JSON → same safe-skip
- Edge case: zero-byte JSON → same safe-skip
- Edge case: `.json.migrated` exists but sentinel absent → sentinel written; no re-migration; existing SQLite preserved
- Integration: `QueueSqliteStore` JSON with one `status=pending` task → migrate → second instance `poll_next()` returns task

**Verification:**
- Passes under `PYTHONHASHSEED=0`
- No raw `os.environ[...]` assignment
- Every absent-file assertion paired with positive SQLite assertion

---

- [x] **Unit 2: Cross-process SQLite update() RMW safety**

**Goal:** Document whether two OS processes calling `update()` (load→fn→save RMW) produce a lost update; confirm WAL integrity for non-conflicting row writes.

**Requirements:** R1

**Dependencies:** Unit 1 patterns

**Files:**
- Create: `tests/test_webui_store_concurrency.py`

**Approach:**
- Use `update()` not `save()` — `save()` is delete-all+bulk-insert, concurrent saves destroy each other by design
- **Cross-process RMW**: two `subprocess.run` worker scripts each call `drafts_store.update(lambda d: {**d, 'key_N': 'val_N'})` with distinct keys; parent reads both. A test comment states: "if only one key survives, this documents the known cross-process lost-update limitation of `update()` — this test documents behavior, not a bug"
- **Non-conflicting writes**: two processes write independent rows; assert WAL-mode guarantees both survive
- Worker scripts generated as `tmp_path / "worker_N.py"`; `env = {**os.environ, "PYTHONHASHSEED": "0"}` captured INSIDE test body

**Patterns to follow:**
- `tests/test_cli_footprint.py` line 127 — canonical subprocess env pattern

**Test scenarios:**
- Integration: two OS subprocesses each `update()` adding a distinct key → parent reads both → document result (both survive or one lost — known limitation either way)
- Integration: two OS subprocesses write non-conflicting rows → both present, no corruption
- Edge case: two in-process `SqliteStore` instances → sequential `update()` via `RLock` → no deadlock

**Verification:**
- `subprocess.run` (not `threading`) for cross-process scenarios
- No `threading.Barrier`, no `VACUUM INTO`
- Cross-process test has comment documenting what a lost-update result means

---

- [x] **Unit 3: LITE edition host enforcement and network matrix**

**Goal:** `127.0.0.1`, `::1`, `localhost` accessible; LAN IP and `fe80::` blocked; `ALLOW_NETWORK=1` does not bypass; launcher consistency.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_lite_host_matrix.py`

**Approach:**
- `_resolve_bind_host()` unit tests for each candidate host string
- Route-level tests: use `environ_overrides={'REMOTE_ADDR': '...'}` (NOT `headers={'HOST': ...}`) — `_enforce_loopback()` checks `request.remote_addr`. Pattern: `test_webui_bind_routes.py` line 171.
- Launcher consistency: see deferred item (verify module-level attribute first)

**Patterns to follow:**
- `tests/test_webui_lite_loopback_enforced.py` — `monkeypatch.setenv` fixture
- `tests/test_webui_bind_routes.py` line 171 — `environ_overrides={'REMOTE_ADDR': ...}` pattern

**Test scenarios:**
- Happy path: `_resolve_bind_host("127.0.0.1")` → `"127.0.0.1"`
- Happy path: `_resolve_bind_host("::1")` → `"::1"`
- Happy path: GET core route `REMOTE_ADDR: 127.0.0.1` → 200
- Happy path: GET core route `REMOTE_ADDR: ::1` → 200
- Happy path: GET core route `REMOTE_ADDR: localhost` → 200 (confirms `"localhost"` in `_LOOPBACK_HOSTS` intentionally allowed at per-request layer)
- Error path: `_resolve_bind_host("192.168.1.100")` → `RuntimeError` (verify contract, deferred)
- Error path: GET any route `REMOTE_ADDR: 192.168.1.100` → 403
- Error path: GET any route `REMOTE_ADDR: fe80::1` → 403 (link-local is not loopback; regression guard)
- Error path: `ALLOW_NETWORK=1` + `LITE=1` → `_resolve_bind_host` returns loopback or raises; LAN IP still 403
- Integration (deferred): launcher import-identity — see deferred items

**Verification:**
- All env writes via `monkeypatch.setenv` only
- Route tests use `environ_overrides={'REMOTE_ADDR': ...}`, never `headers={'HOST': ...}`

---

- [x] **Unit 4: LITE route gating and CSRF behavioral enforcement**

**Goal:** Pro routes 404 regardless of fixture state; CSRF behaviorally enforced on real core routes (not just structurally ordered); nav/route gating consistent.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_lite_surface_hardening.py`

**Approach:**
- **Route gating per blueprint**: each of four Pro blueprints → one representative route → 404 with LITE=1, non-404 without
- **POST to Pro route in LITE mode**: → 404 (gate fires before CSRF handler; proves ordering over CSRF)
- **Tokenless POST to core mutation route**: POST to `/ce:generate` WITHOUT CSRF token while LITE=1 → 403. This is stronger than the E3 ordering test: confirms CSRF fires on real routes, not just that hooks are in correct structural order.
- **CSRF hook ordering** (E3): `app.before_request_funcs[None]` → `_global_csrf_guard` index < `_lite_surface_gate` index
- **Nav consistency**: GET core page with LITE=1 → rendered HTML has no Pro blueprint links
- **No CSRF contamination meta-test**: `test_conftest_state_net.py` already proves `_restore_global_state_net` on `webui.app` singleton; a `create_app()` local instance is not managed by that fixture — would be architecturally broken

**Patterns to follow:**
- `tests/test_webui_csrf_ordering.py` — E3 hook ordering assertion
- `tests/test_webui_lite_nav_surface.py` — LITE fixture pattern

**Test scenarios:**
- Happy path: LITE=off, GET `copilot` route → not 404
- Happy path: LITE=on, GET core route → 200
- Error path: LITE=on, GET each of four Pro blueprint routes → 404
- Error path: LITE=on, POST to Pro blueprint route → 404 (not 403)
- Error path: LITE=on, tokenless POST to `/ce:generate` → 403 (CSRF enforcement on real core route)
- Integration: `app.before_request_funcs[None]` → `_global_csrf_guard` index < `_lite_surface_gate` index
- Integration: rendered HTML with LITE=1 → no Pro blueprint nav links

**Verification:**
- All four Pro blueprints tested
- E3 ordering assertion explicit
- Tokenless POST scenario present (distinguishes structural ordering from behavioral enforcement)

---

- [x] **Unit 5: Bind job state machine completeness**

**Goal:** `TimeoutExpired→kill`, concurrent poll safety, false-success prevention. Cancel does not exist in v1. Duplicate-start already tested in `test_webui_bind_job_service.py::TestRegistryStart::test_concurrent_bind_same_channel_rejected`.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_bind_job_completeness.py`

**Approach:**
- All scenarios use `_FakeProc` injection — no real subprocess
- **`_HangingProc` subclass** (define at module scope, before test classes — prerequisite):
  - `stdout`: finite iterator with no terminal events (so `_drain_stdout`'s `for line in proc.stdout` loop exits)
  - `wait(timeout=N)` where N > 0: raises `subprocess.TimeoutExpired`
  - `wait(timeout=None)`: returns `-9`
  - The hang is in process exit, not stdout. `_drain_stdout` calls `proc.wait(timeout=10)` in `finally` block AFTER stdout closes.
- **TimeoutExpired→kill**: inject `_HangingProc`; `_drain_stdout` closes stdout loop → `finally` → `proc.wait(timeout=10)` raises `TimeoutExpired` → `proc.kill()` → `proc.wait()` returns -9; assert `status="failed"` with timeout indicator in `error_code`
- **Concurrent poll**: two `threading.Thread` callers `poll(job_id)` simultaneously → both return identical snapshots; no exception
- **Backend failure via event**: `_FakeProc` emits `{"event": "channel.bind.failed", "error_code": "auth_rejected"}` → `status="failed"`, `error_code="auth_rejected"`
- **False-success prevention**: while running, `poll()` returns `"running"`, never `"done"`

**Patterns to follow:**
- `tests/test_webui_bind_job_service.py` — `_FakeProc`, `_wait_until`, `registry._popen = _make_popen(...)` injection

**Test scenarios:**
- Error path: `channel.bind.failed` event `error_code="auth_rejected"` → `poll()` `status="failed"`, `error_code="auth_rejected"`
- Error path: stdout closes without terminal event → `status="failed"`, `error_code="stream_closed_no_terminal_event"`
- Error path: `_HangingProc` → stdout terminates, `proc.wait(timeout=10)` raises `TimeoutExpired` → `.kill()` → `status="failed"` with timeout indicator
- Edge case: concurrent `poll(job_id)` from two threads → same snapshot; no exception
- Edge case: `poll()` while `status="running"` → `"running"`, never `"done"` (false-success prevention)
- Not included: cancel (v1 no cancel method); duplicate-start (already covered)

**Verification:**
- All `_FakeProc` scenarios reach assertion within `_wait_until` timeout
- No `time.sleep` in test body
- `_HangingProc` at module scope with all three `wait()` behaviors in docstring

---

- [x] **Unit 6: Bind job in-memory limitation and reset boundary**

**Goal:** Assert v1 in-memory-only limitation; job state does not survive `reset_for_tests()`; `reap_orphans()` is true no-op. These tests are a v2 compliance gate.

**Requirements:** R3

**Dependencies:** Unit 5 patterns

**Files:**
- Create: `tests/test_webui_bind_job_in_memory_boundary.py`

**Approach:**
- Registry is module-level singleton; test hook: `registry.reset_for_tests()` (clears `_jobs`)
- Complete a job → `reset_for_tests()` → assert `poll(job_id)` returns not-found
- Start a job → `reset_for_tests()` before terminal event → assert job gone; no channel lock ghost
- `reap_orphans()` with jobs in registry → job count unchanged
- `poll("nonexistent")` on empty registry → not-found, no `KeyError`

**Patterns to follow:**
- `tests/test_webui_bind_job_service.py` — `_FakeProc`, `registry.reset_for_tests()`

**Test scenarios:**
- Integration: start → terminal event → `reset_for_tests()` → `poll(job_id)` → not-found
- Integration: start (running) → `reset_for_tests()` → job gone; no channel lock ghost
- Edge case: `reap_orphans()` with two completed jobs → count unchanged; no jobs removed
- Edge case: `poll("abc-unknown")` on empty registry → not-found, no exception
- Integration: `reset_for_tests()` → start new job for same channel → succeeds (no ghost lock)
- Documentation: docstring states "v1 in-memory only — if v2 adds persistence, update this test"

**Verification:**
- No test attempts state recovery across `reset_for_tests()`
- `reset_for_tests()` as teardown via autouse class fixture

---

- [x] **Unit 7: url_mode divergence gap and typed error envelope**

**Goal:** Test `url_mode='D'` divergence (passes legacy, fails Pydantic); confirm `ValidationError` paths emit typed `__BLP_ERR__` envelope.

**Requirements:** R4

**Dependencies:** None

**Files:**
- Create: `tests/test_payload_types_divergence.py`

**Approach:**
- `pytest.importorskip("backlink_publisher.publishing.adapters")` at module top
- **Divergence gap**: construct raw dict with `url_mode='D'` → passes `validate_output_payload` (legacy — does NOT check enum values, confirmed by grepping `_schema_output.py`) → call `validate_publish_payload(row)` → assert `ValidationError` raised. Note: `canonical_url` injection-char check is IDENTICAL in both validators — NOT a divergence; do not use as test input.
- **Content_html size boundary**: 1 MiB → accepted; 1 MiB + 1 byte → `ValidationError`
- **Platform alias**: call `validate_and_convert_input` with alias from `supported_platforms()`; assert canonical name returned; `pytest.skip("no platform aliases registered")` if none
- **AST envelope guard**: walk `_schema_input.py` and `_schema_output.py` for `except ValidationError` sites; assert each site calls typed envelope emitter or returns `(None, [message])`; no `sys.exit` or bare `SystemExit`

**Patterns to follow:**
- `tests/test_payload_types.py` — `_valid_planned(**overrides)`, `pytest.raises(ValidationError)` pattern
- `tests/test_cli_typed_error_emission.py` — AST guard pattern

**Test scenarios:**
- Happy path: well-formed `PlannedPayload` passes both validators
- Error path (divergence): `url_mode='D'` → passes `validate_output_payload` (legacy) → raises `ValidationError` in `validate_publish_payload` Pydantic path. Confirm `validate_output_payload` does NOT check `url_mode` first.
- Error path: `link_count < 6` → `ValidationError`
- Error path: `content_html` at 1 MiB + 1 byte → `ValidationError`
- Error path: `url_mode='D'` → `ValidationError` (boundary)
- Edge case: `content_html` exactly 1 MiB → accepted
- Edge case: platform alias → canonical form (or `pytest.skip`)
- Integration: AST scan → no `except ValidationError` site calls `sys.exit` or raises bare `SystemExit`
- Integration: divergence-gap `ValidationError` message contains violated field name

**Verification:**
- Divergence test uses payload that specifically passes legacy checks (confirm legacy path first)
- Platform alias test uses explicit `pytest.skip` if no aliases
- AST guard uses import + source walk (not subprocess)

---

- [x] **Unit 8: WebUI pipeline payload round-trip and error surfacing**

**Goal:** Typed error prefix present; error messages bounded and HTML-escaped; session guard prevents crashes.

**Requirements:** R4

**Dependencies:** Unit 7 patterns

**Files:**
- Create: `tests/test_webui_pipeline_typing_closure.py`

**Approach:**
- `create_app().test_client()` for route tests; `disable_csrf` fixture for POST routes
- Mock `run_pipe_capture` using `side_effect=Exception(stderr_text)` pattern (matching `test_webui_typed_error_surfacing.py` line 40 — the production `run_pipe_capture` returns a dict never raises, but `pipeline_api.py` wraps it in try/except)
- **Typed publish error**: `error_class="PayloadValidationError"` in `__BLP_ERR__` envelope → rendered HTML contains `"[PayloadValidationError]"` prefix
- **QUARANTINE fallback**: plain non-envelope stderr → no `[...]` prefix, `error_class="unrecognized"`
- **Error length bound**: 5000-char error → rendered `publish_error` ≤ 4000 chars
- **HTML escaping**: error containing `<script>alert(1)</script>` → rendered HTML has `&lt;script&gt;`, NOT bare `<script>` — regression-guards Jinja autoescape (future `| safe` annotation would break this)
- **Session guard**: `/ce:validate` without `session['plans']` → redirect or error, not `KeyError`; same for `/ce:publish` without `session['validated']`

**Patterns to follow:**
- `tests/test_webui_typed_error_surfacing.py` — `side_effect=Exception(stderr)` mock pattern
- `tests/test_webui_false_success.py` — false-success detection

**Test scenarios:**
- Happy path: plan → validate → publish with valid payload → no error state
- Happy path (conditional): validate with warning payload → `session['validated']` set, warning visible — `pytest.skip` if no warning payload (deferred)
- Error path: typed `PayloadValidationError` envelope → `"[PayloadValidationError]"` prefix in rendered error
- Error path: plain non-envelope stderr → no `[...]` prefix, `error_class="unrecognized"`
- Error path: 5000-char error message → rendered `publish_error` ≤ 4000 chars
- Error path: error containing `<script>alert(1)</script>` → rendered HTML has `&lt;script&gt;`, not bare `<script>` tag
- Edge case: `/ce:validate` without session plans → no `KeyError`
- Edge case: `/ce:publish` without session validated → no `KeyError`

**Verification:**
- All POST tests use `disable_csrf` fixture, not raw `app.config["WTF_CSRF_ENABLED"] = False`
- Warning-path test uses explicit `pytest.skip` if no payload found
- HTML escaping assertion checks response body string, not just status code

## System-Wide Impact

- **Interaction graph:** Unit 4 tokenless POST test must not inadvertently disable CSRF globally — verify the test client configuration does not call `disable_csrf` fixture for that specific scenario. Unit 6 mutates module-level singleton via `reset_for_tests()` — autouse class fixture required for teardown to prevent leakage.
- **Error propagation:** Units 7 and 8 exercise Pydantic→Flask route→template chain; no `sys.exit` on `ValidationError` — enforced by AST guard in Unit 7.
- **State lifecycle risks:** Unit 6 uses `reset_for_tests()` on the module-level singleton — must not leak state to other test files.
- **API surface parity:** Units 3 and 4 both set `BACKLINK_PUBLISHER_LITE` — separate files ensure clean autouse restore between them.
- **Integration coverage:** Unit 2 requires two OS `subprocess.run` calls; `_isolate_user_dirs` uses `os.environ` direct mutation so subprocess workers inherit the sandboxed config dir via `env = {**os.environ}`.
- **Unchanged invariants:** Existing tests in `test_webui_store_schedule_sqlite.py`, `test_webui_lite_loopback_enforced.py`, `test_webui_bind_job_service.py`, and `test_payload_types.py` remain canonical. New tests add coverage, not replacement.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 2 cross-process `update()` documents a lost-update (behavior, not a bug) | Test comment explicitly states this; test passes regardless of whether both keys survive |
| Unit 5 `_HangingProc` requires three behavioral contracts not obvious from name | Define at module scope with docstring listing all three `wait()` behaviors |
| Unit 7 adapter import at collection blocks entire file if optional dependency absent | `pytest.importorskip("backlink_publisher.publishing.adapters")` at module top |
| Unit 8 warning-path test has no confirmed warning-triggering payload | Explicit `pytest.skip` with description; implementer reads `validate_and_convert_output` first |
| Unit 7 alias test may find no aliases registered | Explicit `pytest.skip("no platform aliases registered")` — not a silent omission |
| Unit 4 tokenless POST may need special test client setup (avoid disabling CSRF globally) | Check existing test infrastructure; use a specific non-`disable_csrf` test client setup |

## Documentation / Operational Notes

- All new test files must carry `PYTHONHASHSEED=0` sensitivity awareness
- Unit 2's subprocess worker scripts are generated as `tmp_path`-scoped `.py` files at test time — not committed to repo
- Once Unit 7 confirms `url_mode` divergence gap, file a follow-up issue to add enum validation to `validate_output_payload` or deprecate it

## Sources & References

- Related code: `webui_store/sqlite_base.py`, `webui_app/helpers/edition.py`, `webui_app/helpers/security.py`, `webui_app/services/bind_job.py`, `src/backlink_publisher/_payload_types.py`, `src/backlink_publisher/_schema_output.py`
- Institutional: `docs/solutions/test-failures/inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md`
- Institutional: `docs/solutions/best-practices/app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md`
- Institutional: `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
- Institutional: `docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md`
- Memory: `atomic-write-not-cross-process-rmw-safe.md`, `reliability-policy-circuit-facts.md`
- Origin plans: `2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md` (SQLite migration completed), `2026-05-28-007-refactor-history-store-events-db-migration-plan.md` (PARKED)
