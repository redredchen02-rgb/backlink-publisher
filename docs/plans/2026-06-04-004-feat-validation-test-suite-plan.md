---
title: "feat: Validation test suite — SQLite migration, LITE edition, keep-alive, payload typing"
type: feat
status: active
date: 2026-06-04
deepened: 2026-06-04
claims: {}
---

# Validation Test Suite — SQLite Migration, LITE Edition, Keep-Alive, Payload Typing

## Overview

Four-area test plan covering confirmed coverage gaps across: SQLite store migration integrity (P0), LITE edition local-only attack surface (P1), bind-job async state machine (P2), and Pydantic as a real publish-pipeline gate (P3). The features are already implemented; this plan adds the missing verification layer.

## Problem Frame

The SQLite store migration completed in plan `2026-06-03-008` (status: completed) — all five operational stores now use `SqliteStore`. However several failure modes have no dedicated tests: corrupt/binary/non-UTF-8 input, cross-process concurrent writes, and rollback recovery. The LITE edition has basic loopback and nav-surface tests but lacks IPv6 acceptance, a launcher-bypass consistency check, and a meta-test confirming that CSRF test fixtures cannot silently contaminate sibling tests. The bind job state machine has happy-path and terminal-event coverage but no tests for cancel, `TimeoutExpired→kill`, duplicate-start rejection, or typed timeout errors. `BindJobRegistry` is a module-level in-memory singleton with no persistence (v1 design, documented as intentional); "server-restart rehydration" is a v2 feature — Unit 6 instead tests that the documented in-memory limitation holds and `reap_orphans()` is a true no-op. Pydantic has a documented divergence gap: rows that pass legacy dict validators but fail Pydantic have no dedicated test, and the WebUI validate-route warning path is untested.

## Requirements Trace

- R1. SQLite migration: old store data survives migration intact; corrupt/binary/non-UTF-8 input starts with clean defaults without crash; pending queue tasks survive restart; WAL snapshot is restorable as a rollback path
- R2. LITE edition: `127.0.0.1` and `::1` both accessible; LAN IP rejected; Pro routes 404 regardless of test fixture state; CSRF guard hook ordering is not bypassable by raw `app.config` writes; nav hiding and route gating are consistent
- R3. Keep-alive bind job: all lifecycle states — start, poll, done, cancel, timeout→kill, duplicate start, backend failure — terminate in a deterministic typed state; false-success (success returned before completion) is impossible; v1 in-memory-only limitation is documented and asserted (no persistence across restart)
- R4. Payload typing: every invalid input reaching the publish pipeline is rejected with a machine-readable typed error; plan→validate→publish round-trip uses typed payloads at every seam; legacy-vs-Pydantic divergence path is explicitly exercised

## Scope Boundaries

- Tests only — no feature implementation changes
- `history_store` (JSON + events.db hybrid) excluded — its SQLite migration is PARKED
- JS frontend polling timing and multi-tab JS behavior excluded — server-side state machine only
- External publishing adapter network calls excluded — mocked by autouse fixtures

## Context & Research

### Relevant Code and Patterns

**Store layer (P0):**
- `webui_store/sqlite_base.py` — `WebUIDatabase` (WAL mode, `0o600`, sidecar tighten, backup xattr), `SqliteStore` (RLock, `load/save/update`, backward-compat `path` property)
- `webui_store/schedule.py` — `ScheduleSqliteStore` (single-row blob, `settings` table, sentinel-protected migration)
- `webui_store/profiles.py`, `webui_store/queue_store.py`, `webui_store/drafts.py`, `webui_store/campaign_store.py` — same sentinel pattern per store
- Existing tests for pattern reference: `tests/test_webui_store_schedule_sqlite.py` (`TestStartupMigration` class, corrupt JSON skip, sentinel idempotency, crash recovery)

**LITE edition (P1):**
- `webui_app/helpers/edition.py` — `is_lite_edition()`, `LITE_HIDDEN_BLUEPRINTS = frozenset({"copilot", "seo_viz", "metrics", "pr_queue"})`
- `webui_app/helpers/security.py` — `_resolve_bind_host()` (loopback enforcement, raises `RuntimeError` on non-loopback), `_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})`
- `webui_app/__init__.py` — `_global_csrf_guard` registered as `before_request` **before** `_lite_surface_gate` (E3 invariant)
- Existing tests: `tests/test_webui_lite_loopback_enforced.py`, `tests/test_webui_lite_nav_surface.py`, `tests/test_webui_csrf_ordering.py`

**Bind job (P2):**
- `webui_app/services/bind_job.py` — `BindJobRegistry`, `_drain_stdout` daemon thread; states: `running → done | failed`; fallback `stream_closed_no_terminal_event`
- `webui_app/routes/bind.py` — `POST /settings/channels/<channel>/bind` starts; `GET .../bind/<job_id>` polls (short-polling, not SSE)
- Existing tests: `tests/test_webui_bind_job_service.py` (`_FakeProc`, `_wait_until` patterns)

**Payload / schema (P3):**
- `src/backlink_publisher/_payload_types.py` — Pydantic v2 models: `SeedPayload`, `PlannedPayload`, `LinkModel`; validators: `canonical_url` injection-char check, 6–8 link count, content_html ≤1 MiB, `url_mode ∈ {A, B, C}`, `publish_mode ∈ {draft, publish}`
- `src/backlink_publisher/schema.py` / `_schema_input.py` / `_schema_output.py` — `validate_and_convert_input`, `validate_and_convert_output`, `validate_publish_payload`
- `webui_app/api/pipeline_api.py` — `PipelineAPI`; `plan()` in-process; `publish()` subprocess via `run_pipe_capture`; `PipeResult(error_class, exit_code, error)`
- `webui_app/routes/pipeline.py` — surfaces `result.error` → `publish_error`; `result.error_class` → `[ErrorClass]` prefix when not `"unrecognized"`
- Existing tests: `tests/test_payload_types.py` (`_valid_seed`/`_valid_planned` helper dict pattern), `tests/test_webui_typed_error_surfacing.py`

### Institutional Learnings

- **Negative assertion trap**: pair every `assert old_json_not_present` with positive complement — row count + semantic round-trip; both positive and negative assertions required to detect data loss (`docs/solutions/test-failures/inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md`)
- **CONFIG_DIR pollution**: `del os.environ[...]` poisons session-scoped fixture for all downstream tests — always use `monkeypatch.setenv`/`monkeypatch.delenv` (`docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`)
- **CSRF contamination**: raw `app.config["WTF_CSRF_ENABLED"] = False` leaks into sibling tests; use `monkeypatch.setitem`; run LITE tests in isolation to detect false-green contamination (`docs/solutions/best-practices/app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md`)
- **Cross-process RMW**: `threading.Barrier(2)` tests falsely pass for cross-process write safety due to in-process RLock serialization — use two OS `subprocess.run()` processes (memory: `atomic-write-not-cross-process-rmw-safe.md`)
- **Typed error envelope**: every `ValidationError` path must emit `__BLP_ERR__` JSON on stderr, not bare `SystemExit(1)` (`docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md`)
- **False-success trap**: a running job's status endpoint must not return success before the job completes (`docs/solutions/ui-bugs/webui-blocking-subprocess-and-missing-progress-feedback-2026-05-12.md`)
- **Publish-history invariant**: migration tests touching history rows must route through `_push_history_per_row` or run a post-migration invariant sweep (`docs/solutions/best-practices/publish-history-helper-invariant-2026-05-20.md`)
- **HALF_OPEN dead code**: do not test circuit-tripped behavior by accumulating failures — plant state with `circuit.trip()` directly (memory: `reliability-policy-circuit-facts.md`)

## Key Technical Decisions

- **New file per area**: each of the 8 units creates its own new test file rather than appending to existing files — the coverage gap is visible as a distinct commit and the new file runs cleanly in isolation (detecting contamination from the suite). Risk: Units 3, 4, and 8 each call `create_app().test_client()` independently; if `create_app()` gains a new required teardown step, all three files need the same fix. Accepted maintenance cost — per-file setup must stay synchronized with `webui_app/__init__.py`'s factory contract.
- **`subprocess.run` for cross-process safety in Unit 2**: two OS processes are the minimum — `threading.Barrier` tests falsely pass because in-process RLock serializes both threads, exercising only the single-process path. The `_isolate_user_dirs` fixture uses `os.environ` direct mutation at module-level and session-scope; child processes spawned with `env = {**os.environ}` (captured inside the test body, after the fixture runs) automatically inherit the sandboxed `BACKLINK_PUBLISHER_CONFIG_DIR`. Do NOT capture `os.environ` at module import time — the fixture has not run yet. Pattern: `env = {**os.environ, "PYTHONHASHSEED": "0"}` (see `test_cli_footprint.py` line 127 for the canonical form).
- **`monkeypatch` exclusively throughout**: no raw `os.environ[...] =`, `del os.environ[...]`, or `app.config[...] =` in any new test file. **Single intentional exception**: Unit 4's CSRF contamination meta-test deliberately writes `app.config["WTF_CSRF_ENABLED"] = False` without monkeypatch to verify that `_restore_global_state_net` restores it — this is the subject of the test, not a pattern to copy.
- **Platform alias via `supported_platforms()` with `importorskip` guard**: the real registry is called (adapter side-effect is intentional — if adapters aren't importable, the failure is meaningful). Risk: if any adapter's import chain fails (optional dependency absent in CI), `ImportError` at collection blocks the entire test file, not just the alias test. Mitigation: add `pytest.importorskip("backlink_publisher.publishing.adapters")` at module top in Unit 7; if adapters are unconditionally importable in CI (confirm via `tox.ini`/CI requirements), the guard can be removed.
- **`__tier__` marker on every new module**: `"unit"` for store/payload tests; `"integration"` for route/cross-layer tests — per repo `pytest_collection_modifyitems` convention
- **P2 state machine tested via `_FakeProc`**: no real subprocess for state transitions — the injected fake proc is the correct abstraction; subprocess is reserved for Unit 2 cross-process SQLite writes only. Critical prerequisite: the existing `_FakeProc.wait()` ignores the `timeout` parameter and returns immediately. The `TimeoutExpired→kill` path in Unit 5 requires a subclass (`_HangingProc` or similar) whose `wait(timeout=N)` raises `subprocess.TimeoutExpired`. This subclass must be created in `test_webui_bind_job_completeness.py` — it is not a deferred item but a prerequisite for the timeout scenario.

## Open Questions

### Resolved During Planning

- **Does `::1` test need a real socket bind?** No — Unit 3 tests string membership in `_LOOPBACK_HOSTS` and route-level enforcement via `REMOTE_ADDR: ::1` environ override; no OS IPv6 socket needed
- **Is `history_store` in scope for P0?** No — its SQLite migration is PARKED (`docs/plans/2026-05-28-007`); test scope is the five `SqliteStore`-backed stores only (excluding `channel_status_store` — see deferred note below)
- **Is JS frontend polling timing in scope for P2?** No — server-side state machine and HTTP route layer only; JS timing is outside the pytest harness
- **`BindJobRegistry` instantiation model**: module-level singleton (`registry = BindJobRegistry()` at line 226 of `bind_job.py`); `create_app()` only calls `reap_orphans()` (a documented no-op). The registry is **purely in-memory** (`dict[str, BindJob]`) — no SQLite, no JSON persistence. Terminal states are **not** recoverable after process restart (v1 design, intentional). Test hook: `registry.reset_for_tests()` clears `_jobs`. Unit 6 is rewritten accordingly — it tests the documented in-memory limitation, not recovery.

### Deferred to Implementation

- **Duplicate-start HTTP status code and response structure (Unit 5)**: check `webui_app/routes/bind.py` for whether concurrent same-channel start returns 409 or another status AND what response body/headers are included; assert both status code and response structure
- **Validation warning-path payload (Unit 8)**: read `validate_and_convert_output` for conditions that return `(PlannedPayload, [warning_strings])` — confirm a warning-triggering payload can be constructed before writing the test; if none exist, mark with `pytest.skip`
- **Unit 3 LAN IP and route behavior**: verify whether `_resolve_bind_host(LAN_IP)` raises `RuntimeError` or returns loopback, and whether the route returns 403 or redirect; assert the actual contract found
- **Unit 3 launcher import-identity**: verify `webui.py` exposes `_resolve_bind_host` as a module-level attribute (not a local import inside a function body); if local import, substitute an AST check instead of a runtime identity assertion
- **channel_status_store scope (Unit 1)**: confirm whether `channel_status_store` has existing migration edge-case coverage or should be added as a sixth store to Unit 1's parametrize list

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
Dependency graph (TB = top-to-bottom, arrows = must-exist-first):

P0 ──┬── Unit 1: Store migration edge cases (single process)
     └── Unit 2: Cross-process write safety + WAL rollback

P1 ──┬── Unit 3: Host enforcement matrix (127.0.0.1, ::1, LAN, ALLOW_NETWORK)
     └── Unit 4: Route gating + CSRF fixture contamination resistance

P2 ──┬── Unit 5: Bind job state machine completeness (all transitions)
     └── Unit 6: Bind job in-memory boundary + reset assertions  [depends on U5 patterns]

P3 ──┬── Unit 7: Legacy-vs-Pydantic divergence + typed error envelope
     └── Unit 8: WebUI pipeline payload round-trip + error surfacing  [depends on U7 patterns]
```

Units 1, 2, 3, 4, 5, 7 are independent and can be implemented in parallel. Units 6 and 8 each depend on the preceding unit in their phase for pattern reference.

## Implementation Units

- [ ] **Unit 1: SQLite store migration edge cases**

**Goal:** Cover corrupt/binary/non-UTF-8 input files, empty startup for all five stores, and queue pending-task recovery across a store reconstruction.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_store_migration_edge_cases.py`

**Approach:**
- Construct a `_store(tmp_path, StoreClass)` helper that sets `BACKLINK_PUBLISHER_CONFIG_DIR` via `monkeypatch.setenv` and instantiates the store
- For corrupt input: write raw bytes (`b'\xff\xfe\x00\x01'`) to the JSON path before calling `migrate_from_json`; assert sentinel NOT written, store returns empty/default value
- For non-UTF-8 JSON: write a syntactically valid JSON payload byte-encoded in latin-1 (not UTF-8); assert same safe-skip behavior as corrupt
- For empty startup: no JSON file, no SQLite file; assert each of the five stores returns its documented empty default (`{}`, `[]`, no pending tasks, etc.)
- For queue pending-task recovery: write JSON payload with one `{"status": "pending"}` task → `migrate_from_json` → construct a second `QueueSqliteStore` instance pointing at same `config_dir` → assert `poll_next()` returns the task
- Every assertion about absent-old-file must be paired with a positive assertion about SQLite content

**Patterns to follow:**
- `tests/test_webui_store_schedule_sqlite.py` — `TestStartupMigration` class structure, `_corrupt_json` helper pattern, sentinel + `.json.migrated` assertion pairing

**Test scenarios:**
- Happy path: `ScheduleSqliteStore.migrate_from_json` with well-formed JSON → settings table has expected row, sentinel written, original renamed to `.json.migrated`; read back via second instance equals original
- Happy path: empty startup (no JSON, no DB) for each of the five stores → documented empty default returned; no exception raised
- Edge case: binary (non-UTF-8) bytes at JSON path → `migrate_from_json` skips; sentinel NOT written; original file untouched; store returns empty default
- Edge case: non-UTF-8 encoded JSON content (latin-1 encoding) → same safe-skip behavior
- Edge case: zero-byte JSON file → same safe-skip behavior
- Edge case: `.json.migrated` exists but sentinel absent (crash recovery path) → sentinel written; migration NOT re-run; existing SQLite data preserved
- Integration: `QueueSqliteStore` JSON payload with one `status=pending` task → migrate → new store instance → `poll_next()` returns that task with original data intact

**Verification:**
- `pytest tests/test_webui_store_migration_edge_cases.py -x` passes under `PYTHONHASHSEED=0`
- No raw `os.environ[...]` assignment in the file
- Every assertion of absent JSON file is paired with a positive SQLite content assertion

---

- [ ] **Unit 2: Cross-process SQLite write safety and WAL rollback**

**Goal:** Confirm two OS processes writing to the same `webui.db` via the `update()` RMW cycle do not produce lost updates; confirm WAL-mode SQLite OS-level integrity under concurrent non-conflicting row writes.

**Requirements:** R1

**Dependencies:** Unit 1 patterns (store construction via `tmp_path`)

**Files:**
- Create: `tests/test_webui_store_concurrency.py`

**Approach:**
- Use `update()` (the `load→fn→save` RMW cycle, not `save()`) — this is the method that has the cross-process lost-update risk documented in memory `atomic-write-not-cross-process-rmw-safe.md`. `save()` is a delete-all+bulk-insert with different semantics.
- **Cross-process lost-update test**: use `subprocess.run` to launch two Python worker scripts (written to `tmp_path`) in parallel; each calls `drafts_store.update(lambda d: {**d, 'key_N': 'val_N'})` with a distinct key; parent reads both keys and asserts both are present. This exercises whether the in-process `RLock` is insufficient across OS processes (the known gap).
- **Non-conflicting concurrent row writes**: two processes write to completely independent rows via row-level `insert_first()` (not `update()`); assert WAL-mode OS locking guarantees both rows survive without corruption.
- Worker scripts generated via `tmp_path / "worker_N.py"`; use `env = {**os.environ}` (captured inside test body after fixtures run) to inherit the sandboxed `BACKLINK_PUBLISHER_CONFIG_DIR`
- Do NOT use `threading.Barrier` — cross-process safety requires two OS processes

**Patterns to follow:**
- `circuit.py` flock-across-RMW pattern (the cross-process safety idiom in this codebase)
- `tests/test_webui_store_sqlite_base.py` — existing concurrency class
- `tests/test_cli_footprint.py` line 127 — `env = {**os.environ, "PYTHONHASHSEED": "0"}` canonical subprocess env pattern

**Test scenarios:**
- Integration: two OS subprocesses each call `update()` adding a distinct key to `DraftsSqliteStore` → parent reads both keys → assert both survive (or document that one is lost — this test verifies the KNOWN LIMITATION, not absence of it; result documents the behavior)
- Integration: two OS subprocesses write non-conflicting rows via `insert_first()` → both rows present, no WAL-level corruption
- Edge case: two in-process `SqliteStore` instances (same process, same DB file) → sequential `update()` via `RLock` → no deadlock, consistent state

**Verification:**
- Test uses `subprocess.run` (not `threading`) for cross-process scenarios
- No `threading.Barrier` usage in the file
- No `VACUUM INTO` or snapshot/restore logic — this is out of scope (no application code calls `VACUUM INTO`)
- The cross-process `update()` test documents the behavior (lost-update or survived) regardless of outcome — a test comment explains the known limitation

---

- [ ] **Unit 3: LITE edition host enforcement and network matrix**

**Goal:** Confirm `127.0.0.1` and `::1` are accepted; LAN IP is blocked; `BACKLINK_PUBLISHER_ALLOW_NETWORK=1` does not bypass loopback enforcement; launcher uses the same `_resolve_bind_host` function.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_lite_host_matrix.py`

**Approach:**
- Test `_resolve_bind_host()` directly from `webui_app.helpers.security` for each candidate host string
- For route-level enforcement: `_enforce_loopback()` checks `request.remote_addr` (NOT the Host header). Use `environ_overrides={'REMOTE_ADDR': '::1'}` on the test client — NOT `headers={'HOST': '[::1]'}`. The existing codebase pattern (see `test_webui_bind_routes.py` line 171: `environ_overrides={'REMOTE_ADDR': '10.0.0.5'}`) confirms this.
- For LAN IP: `environ_overrides={'REMOTE_ADDR': '192.168.1.100'}` → assert 403
- For `ALLOW_NETWORK=1 + LITE=1`: `monkeypatch.setenv` both; assert `_resolve_bind_host()` still returns a loopback host (or raises)
- Launcher consistency: verify `webui.py` exposes `_resolve_bind_host` as a module-level attribute first (deferred item); if confirmed, assert import identity; if local import, substitute AST check

**Patterns to follow:**
- `tests/test_webui_lite_loopback_enforced.py` — `monkeypatch.setenv("BACKLINK_PUBLISHER_LITE", "1")` fixture
- `tests/test_webui_bind_routes.py` line 171 — `environ_overrides={'REMOTE_ADDR': '10.0.0.5'}` pattern for route-level enforcement tests

**Test scenarios:**
- Happy path: `_resolve_bind_host("127.0.0.1")` → `"127.0.0.1"`
- Happy path: `_resolve_bind_host("::1")` → `"::1"`
- Happy path: GET core route with `REMOTE_ADDR: 127.0.0.1` → 200
- Happy path: GET core route with `REMOTE_ADDR: ::1` → 200
- Happy path: GET core route with `REMOTE_ADDR: localhost` → 200 (confirms the `"localhost"` string in `_LOOPBACK_HOSTS` is intentionally allowed at the per-request enforcement layer)
- Error path: `_resolve_bind_host("192.168.1.100")` → raises `RuntimeError` (or returns loopback — verify behavior from implementation, deferred item)
- Error path: GET any route with `REMOTE_ADDR: 192.168.1.100` → 403
- Error path: GET any route with `REMOTE_ADDR: fe80::1` → 403 (link-local is not loopback; regression guard for future `_LOOPBACK_HOSTS` expansion)
- Error path: `ALLOW_NETWORK=1` + `LITE=1` → `_resolve_bind_host` still returns loopback or raises; LAN IP route request still 403
- Integration (deferred): launcher import-identity — see deferred item

**Verification:**
- All env writes use `monkeypatch.setenv` only
- `BACKLINK_PUBLISHER_LITE` and `BACKLINK_PUBLISHER_ALLOW_NETWORK` are restored after each test by autouse fixture

---

- [ ] **Unit 4: LITE route gating, nav consistency, and CSRF fixture contamination resistance**

**Goal:** Pro routes 404 regardless of test fixture state; nav hiding and route gating are consistent; CSRF fixture restore guard (`_restore_global_state_net`) is verified to work.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_lite_surface_hardening.py`

**Approach:**
- **Route gating per blueprint**: for each of the four Pro blueprints in `LITE_HIDDEN_BLUEPRINTS` (`copilot`, `seo_viz`, `metrics`, `pr_queue`), pick one representative route and assert it returns 404 with `BACKLINK_PUBLISHER_LITE=1` and non-404 without LITE
- **POST to Pro route in LITE mode**: POST to a Pro route → should return 404 (gated before the CSRF handler for that blueprint; proves ordering: gate fires before CSRF check)
- **Tokenless POST to LITE-accessible core route**: POST to `/ce:generate` (or another pipeline mutation route) WITHOUT a CSRF token while `LITE=1` → assert 403. This is stronger than the hook-ordering test: it confirms CSRF enforcement actually fires on real core routes in LITE mode, not just that hooks are in the right order.
- **Nav consistency**: GET any core page with LITE=1 → assert rendered HTML does not contain Pro blueprint links; `lite_edition=True` present in Jinja context
- **CSRF hook ordering**: read `app.before_request_funcs[None]` from a freshly created app; assert the list index of `_global_csrf_guard` is less than the list index of `_lite_surface_gate` — this is the E3 invariant
- **Blueprint exhaustiveness note**: the gating test covers the 4 listed blueprints. The plan does NOT assert that all other 23+ registered blueprints are safe to expose in LITE mode — that would require a product-level attestation. Document in a test comment that `LITE_HIDDEN_BLUEPRINTS` is the authoritative gating list and any new Pro blueprint must be added there deliberately.
- No CSRF contamination meta-test: `test_conftest_state_net.py` already covers `_restore_global_state_net` behavior on the `webui.app` singleton, and a `create_app()`-local instance is not managed by that fixture. Removed to avoid redundancy and architectural confusion.

**Patterns to follow:**
- `tests/test_webui_csrf_ordering.py` — E3 hook ordering assertion
- `tests/test_webui_lite_nav_surface.py` — LITE fixture pattern

**Test scenarios:**
- Happy path: LITE=off, GET `copilot` blueprint route → not 404
- Happy path: LITE=on, GET core route (e.g., `/`) → 200
- Error path: LITE=on, GET each of four Pro blueprint routes → 404
- Error path: LITE=on, POST to Pro blueprint route → 404 (not 403 CSRF error; gate fires first)
- Error path: LITE=on, tokenless POST to `/ce:generate` (or another core mutation route) → 403 (CSRF enforced on real core routes, not just structural ordering)
- Integration: `app.before_request_funcs[None]` list → `_global_csrf_guard` index < `_lite_surface_gate` index
- Integration: rendered HTML with LITE=1 → no Pro blueprint nav links present

**Verification:**
- All four Pro blueprints (copilot, seo_viz, metrics, pr_queue) have at least one route tested
- E3 ordering assertion present and explicit
- Tokenless POST scenario present (not just ordering test) — this distinguishes structural verification from behavioral enforcement verification

---

- [ ] **Unit 5: Bind job state machine completeness**

**Goal:** Test lifecycle transitions not covered in existing `test_webui_bind_job_service.py`: `TimeoutExpired→kill`, multi-caller concurrent poll, and typed error for backend failures. Note: cancel/stop method does not exist in v1 (`BindJobRegistry` has only `start`, `poll`, `reset_for_tests`); cancel is deferred to a future feature plan. Note: duplicate-start rejection is already tested in `test_webui_bind_job_service.py::TestRegistryStart::test_concurrent_bind_same_channel_rejected` — do not duplicate it.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Create: `tests/test_webui_bind_job_completeness.py`

**Approach:**
- All scenarios use `_FakeProc` injection pattern from `test_webui_bind_job_service.py` — no real subprocess
- **TimeoutExpired→kill** (prerequisite: `_HangingProc`): create `_HangingProc` at module scope (above test classes) — a subclass of `_FakeProc` with TWO required behaviors: (1) `stdout` iterator terminates (empty or no-terminal-event lines, so `_drain_stdout`'s `for line in proc.stdout` loop exits); (2) `wait(timeout=N)` where N > 0 raises `subprocess.TimeoutExpired`; (3) `wait(timeout=None)` returns an exit code (e.g., `-9`). The production `_drain_stdout` calls `proc.wait(timeout=10)` in the `finally` block AFTER the stdout loop exits — the hang is in the process's exit, not its stdout. Inject `_HangingProc`; assert `.kill()` was called and status becomes `"failed"` with a timeout error indicator in `error_code`.
- **Concurrent poll**: two `threading.Thread` callers call `registry.poll(job_id)` simultaneously → both return identical snapshots; no exception
- **Backend failure via event**: `_FakeProc` emits `{"event": "channel.bind.failed", "error_code": "auth_rejected"}` → assert `status="failed"`, `error_code="auth_rejected"`
- **False-success prevention**: while a job is running (before terminal event), `poll()` must return `status="running"` — never `status="done"`

**Patterns to follow:**
- `tests/test_webui_bind_job_service.py` — `_FakeProc`, `_wait_until(predicate, timeout=)`, `registry._popen = _make_popen(...)` injection
- Do not test circuit-tripped HALF_OPEN via accumulated failures — plant state via `circuit.trip()` if needed

**Test scenarios:**
- Happy path: start → `channel.bind.persisted` event → `poll()` returns `status="done"` (confirm existing test covers; cross-reference, do not duplicate)
- Error path: `channel.bind.failed` event with `error_code="auth_rejected"` → `poll()` returns `status="failed"`, `error_code="auth_rejected"`
- Error path: stdout closes without terminal event → `status="failed"`, `error_code="stream_closed_no_terminal_event"`
- Error path: `_HangingProc` injected → stdout terminates, `proc.wait(timeout=10)` raises `TimeoutExpired` → `.kill()` called → `status="failed"` with timeout error indicator in `error_code`
- Edge case: concurrent `poll(job_id)` from two threads → both return same snapshot; no exception raised
- Edge case: `poll()` while job is `status="running"` → returns `"running"`, never prematurely returns `"done"` (false-success prevention)
- Not included: cancel (v1 has no cancel method — deferred to future feature plan); duplicate-start (already in `TestRegistryStart::test_concurrent_bind_same_channel_rejected`)

**Verification:**
- All `_FakeProc` terminal scenarios reach their assertion within `_wait_until` polling timeout
- No `time.sleep` in test body — `_wait_until` predicate only
- `_HangingProc` is defined at module scope before test classes, with all three `wait()` behaviors documented

---

- [ ] **Unit 6: Bind job in-memory limitation and reset boundary**

**Goal:** Assert that `BindJobRegistry` is v1 in-memory-only; job state does not survive `reset_for_tests()`; `reap_orphans()` is a true no-op; unknown job_id queries return not-found cleanly. These tests serve as a v2 compliance gate: if persistence is ever added, these assertions become the spec.

**Requirements:** R3

**Dependencies:** Unit 5 patterns (job lifecycle)

**Files:**
- Create: `tests/test_webui_bind_job_in_memory_boundary.py`

**Approach:**
- Registry is a module-level singleton in `bind_job.py`; test hook is `registry.reset_for_tests()` (clears `_jobs`)
- **Post-reset state**: complete a job → call `reset_for_tests()` → assert `poll(job_id)` returns not-found (the job is gone)
- **Running job post-reset**: start a job → `reset_for_tests()` before terminal event → assert job is gone; no dangling references
- **`reap_orphans()` is a no-op**: call `reap_orphans()` with jobs in the registry → job count unchanged
- **Unknown job_id**: call `poll("nonexistent-id")` on empty registry → returns appropriate not-found response (no `KeyError`, no 500)
- **After reset, re-start is allowed**: after `reset_for_tests()`, starting a new job for a previously-seen channel succeeds (no channel-lock ghost)

**Patterns to follow:**
- `tests/test_webui_bind_job_service.py` — `_FakeProc`, `registry.reset_for_tests()` usage

**Test scenarios:**
- Integration: start → terminal event → `reset_for_tests()` → `poll(job_id)` → not-found (job does not survive reset)
- Integration: start (running, no terminal event) → `reset_for_tests()` → job gone; no hung channel lock
- Edge case: `reap_orphans()` with two completed jobs in registry → registry still has same count; no jobs removed
- Edge case: `poll("abc-unknown")` on empty registry → not-found response, no exception
- Integration: `reset_for_tests()` → start new job for same channel as before → start succeeds (no ghost channel lock)
- Documentation: test docstring explicitly states "v1 in-memory only — if persistence is added in v2, this test must be updated to reflect recovery behavior"

**Verification:**
- No test in this file attempts to recover state across `reset_for_tests()` (that would be testing a feature that doesn't exist)
- All scenarios use `registry.reset_for_tests()` as teardown (via `autouse` fixture at class level) to prevent state leakage to other tests

---

- [ ] **Unit 7: Legacy-vs-Pydantic divergence gap and typed error envelope**

**Goal:** Test the documented gap where rows pass legacy dict validators but fail Pydantic; confirm all `ValidationError` paths emit a typed `__BLP_ERR__` envelope rather than bare `SystemExit`.

**Requirements:** R4

**Dependencies:** None

**Files:**
- Create: `tests/test_payload_types_divergence.py`

**Approach:**
- **Divergence gap**: construct a raw dict that passes `validate_output_payload` (legacy) but violates a Pydantic constraint in `PlannedPayload`. Use `url_mode='D'` (invalid enum) — `validate_output_payload` does NOT check `url_mode`/`publish_mode` enum values, but `PlannedPayload` enforces `url_mode ∈ {A, B, C}`. Call `validate_publish_payload(row)` and assert it raises `ValidationError`. Note: `canonical_url` injection-char check uses the SAME regex in both legacy and Pydantic — NOT a divergence gap; do not use it as the test input.
- **Content_html size boundary**: `content_html` at exactly 1 MiB (1,048,576 bytes) → accepted; at 1 MiB + 1 byte → `ValidationError`
- **Platform alias normalization**: call `validate_and_convert_input` with a platform alias (discover from `supported_platforms()` and adapter `aliases` if they exist); assert `SeedPayload.platform` is the canonical name. If no aliases exist, mark test with explicit `pytest.skip("no platform aliases registered")`
- **AST envelope guard**: walk `_schema_input.py` and `_schema_output.py` for `except ValidationError` sites; assert each site either calls the typed envelope emitter or returns `(None, [message])` — no site calls `sys.exit` or `raise SystemExit`
- Use `_valid_planned(**overrides)` helper pattern from `test_payload_types.py`

**Patterns to follow:**
- `tests/test_payload_types.py` — `_valid_seed`/`_valid_planned` helpers, `pytest.raises(ValidationError)` pattern
- `tests/test_cli_typed_error_emission.py` — AST guard pattern (if present; adapt if absent)

**Test scenarios:**
- Happy path: well-formed `PlannedPayload` passes both legacy and `validate_publish_payload` — no exception
- Error path (divergence): `url_mode='D'` → passes legacy `validate_output_payload` (which does not check enum values) → raises `ValidationError` in `validate_publish_payload` Pydantic path. Confirm first that `validate_output_payload` does NOT check `url_mode` (grep `_schema_output.py`)
- Error path: `link_count < 6` → `ValidationError` in `PlannedPayload` validation
- Error path: `content_html` at 1 MiB + 1 byte → `ValidationError`
- Error path: `url_mode = "D"` (invalid enum) → `ValidationError` raised
- Edge case: `content_html` at exactly 1 MiB → accepted (boundary inclusive)
- Edge case: platform alias → `SeedPayload.platform` is canonical form (or `pytest.skip` if no aliases)
- Integration: AST scan of `_schema_input.py` and `_schema_output.py` → no `except ValidationError` site calls `sys.exit` or raises bare `SystemExit`
- Integration: `validate_publish_payload` on divergence-gap row → `ValidationError` message is human-readable and contains the violated field name

**Verification:**
- The divergence-gap test exploits a row constructed to specifically pass legacy checks (not a trivially invalid row that both would catch — confirm the legacy path first)
- Platform alias test uses `pytest.skip` (explicit, not omitted) if no aliases exist in the registry
- AST guard test imports and walks source, does not use subprocess

---

- [ ] **Unit 8: WebUI pipeline payload round-trip and error surfacing**

**Goal:** Confirm plan→validate→publish uses typed payloads at every seam; validation warnings are surfaced (not silently dropped); publish errors carry typed class prefix; error messages are length-bounded.

**Requirements:** R4

**Dependencies:** Unit 7 (typed error envelope patterns)

**Files:**
- Create: `tests/test_webui_pipeline_typing_closure.py`

**Approach:**
- Use `create_app().test_client()` for all route tests; use `disable_csrf` fixture for POST routes
- **Validate warning path**: construct a `PlannedPayload` that triggers a warning (not an error) from `validate_and_convert_output` (read implementation first — deferred; if no warning-triggering payload found, use `pytest.skip`); POST to `/ce:validate`; assert `session['validated']` is set and the rendered HTML contains the warning indicator
- **Typed publish error**: mock `run_pipe_capture` to return a `__BLP_ERR__` JSON on stderr with `error_class="PayloadValidationError"`; POST to `/ce:publish`; assert rendered HTML contains `"[PayloadValidationError]"` prefix
- **QUARANTINE fallback**: mock `run_pipe_capture` to return plain non-envelope stderr; assert rendered HTML contains raw error text without `[...]` prefix and `error_class="unrecognized"` in the route's computed state
- **Error length bound**: mock publish to emit a stderr message of 5000 chars; assert rendered `publish_error` is ≤ 4000 chars
- **Session guard**: call `/ce:validate` without prior `/ce:plan` (no `session['plans']`) → appropriate redirect or error response, not `KeyError` crash; same for `/ce:publish` without `session['validated']`

**Patterns to follow:**
- `tests/test_webui_typed_error_surfacing.py` — `run_pipe_capture` mock pattern, `PipelineAPI` test setup
- `tests/test_webui_false_success.py` — false-success detection pattern

**Test scenarios:**
- Happy path: plan → validate → publish with all-valid payload → no error state in rendered HTML
- Happy path (conditional): validate with warning-only payload → `session['validated']` set, warning text visible in template — `pytest.skip` if no warning-triggering payload can be constructed (deferred)
- Error path: publish with typed `PayloadValidationError` envelope → rendered `publish_error` contains `"[PayloadValidationError]"` prefix
- Error path: publish with plain non-envelope stderr → rendered error has no `[...]` prefix, `error_class="unrecognized"`
- Error path: publish with 5000-char error message → rendered `publish_error` is ≤ 4000 chars
- Edge case: GET `/ce:validate` without session plans → no `KeyError`; response is redirect or error
- Edge case: GET `/ce:publish` without session validated → no `KeyError`; response is redirect or error
- Integration: `PipelineAPI.validate()` on a valid plan → result rows each pass `validate_publish_payload` without `ValidationError`

**Verification:**
- All POST tests use `disable_csrf` fixture, not raw `app.config["WTF_CSRF_ENABLED"] = False`
- Warning-path test uses explicit `pytest.skip` if no warning-triggering payload found (not silently omitted)
- Error-length-bound assertion uses `len(rendered_error) <= 4000`, not a substring match

## System-Wide Impact

- **Interaction graph:** Unit 4's CSRF contamination meta-test deliberately mutates `app.config` — it must use a dedicated per-test `app` fixture (not a module-level shared app) so other tests in the file are not affected. The autouse `_restore_global_state_net` fixture is what the meta-test is validating.
- **Error propagation:** Units 7 and 8 exercise the Pydantic→Flask route→template error chain; no part of this chain should call `sys.exit` — the AST guard in Unit 7 enforces this at source level.
- **State lifecycle risks:** Unit 6 tests `registry.reset_for_tests()` which mutates the module-level singleton — each test class must call `reset_for_tests()` in teardown (via autouse fixture) to prevent state leaking to other tests in the same session. No SQLite involved (registry is in-memory only).
- **API surface parity:** Unit 3 (host enforcement) and Unit 4 (CSRF/route gating) both set `BACKLINK_PUBLISHER_LITE` — running in separate files ensures the `_restore_global_state_net` autouse fixture cleanly restores state between them.
- **Integration coverage:** Unit 2's cross-process test is the only test in the plan requiring two OS `subprocess.run` calls. Verify that the autouse `_isolate_user_dirs` fixture (sets `BACKLINK_PUBLISHER_CONFIG_DIR`) propagates to subprocesses via `env=os.environ.copy()` — subprocess workers must inherit the config dir.
- **Unchanged invariants:** Existing tests in `test_webui_store_schedule_sqlite.py`, `test_webui_lite_loopback_enforced.py`, `test_webui_bind_job_service.py`, and `test_payload_types.py` remain canonical. New tests add to coverage — they do not replace or duplicate existing scenarios.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 2 cross-process SQLite test is flaky on CI due to file-locking races | Use WAL mode (already default) + explicit `PRAGMA synchronous=FULL` in worker scripts; if still flaky, add to known-flaky list and open a dedicated fix issue |
| Unit 5 `TimeoutExpired→kill` path requires `_FakeProc` subclass not in existing codebase | Create `_HangingProc` subclass at top of `test_webui_bind_job_completeness.py` before test classes — prerequisite, not deferred |
| Unit 7 adapter import at collection fails if any adapter has an absent optional dependency | Add `pytest.importorskip("backlink_publisher.publishing.adapters")` at module top; confirm CI requirements cover all adapter dependencies |
| Unit 8 warning-path test has no confirmed warning-triggering payload | Explicit `pytest.skip` with description preserves test intent; implementer should search `validate_and_convert_output` return sites |
| Platform alias test in Unit 7 may find no aliases registered | Explicit `pytest.skip("no platform aliases registered")` — not a silent omission |
| Unit 4 CSRF contamination meta-test order-sensitive with other tests in the class | Use a dedicated `app` fixture per test class in Unit 4; do not share module-level `app` |

## Documentation / Operational Notes

- All new test files must carry `PYTHONHASHSEED=0` sensitivity awareness — they will be run under that constraint in CI
- Unit 2's cross-process subprocess scripts should be generated via `tmp_path`-scoped `.py` files, not written to the repo permanently
- Once Unit 7 confirms the legacy-vs-Pydantic divergence gap, consider filing a follow-up issue to close the gap at the source (adding the injection-char check to the legacy validator or deprecating the legacy validator)

## Sources & References

- Related code: `webui_store/sqlite_base.py`, `webui_app/helpers/edition.py`, `webui_app/helpers/security.py`, `webui_app/services/bind_job.py`, `src/backlink_publisher/_payload_types.py`
- Institutional: `docs/solutions/test-failures/inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md`
- Institutional: `docs/solutions/best-practices/app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md`
- Institutional: `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
- Institutional: `docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md`
- Memory: `atomic-write-not-cross-process-rmw-safe.md`
- Memory: `reliability-policy-circuit-facts.md`
- Origin plans: `2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md` (SQLite migration completed), `2026-05-28-007-refactor-history-store-events-db-migration-plan.md` (PARKED)
