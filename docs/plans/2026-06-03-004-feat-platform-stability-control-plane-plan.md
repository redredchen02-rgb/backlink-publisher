---
title: "feat: Platform Stability Control Plane — unified health source, platform-health CLI, and circuit breaker expansion"
type: feat
status: completed
date: 2026-06-03
deepened: 2026-06-03
claims: {}  # new modules under src/; no SLOC/CC claims pre-merge; budget entries validated at execution time
---

# feat: Platform Stability Control Plane

## Overview

Health signals for the publishing pipeline currently live in five separate places
(`health_metrics.py`, `channel_status`, `circuit.py`, `canary/`, `binding_status`),
none of which share a unified per-platform last-state record. The result: the
`/ce:health` dashboard shows 30-day aggregates but cannot answer "when did Medium
last succeed?" or "is Dev.to circuit-tripped right now?".

This plan builds the **control plane** in three phases:

- **Phase 1 (this PR scope):** Unified health aggregate source → per-platform
  `last_*` records; cross-process-safe locked store; `platform-health` CLI verb;
  `/ce:health` display refresh to consume the new source.
- **Phase 2:** Maintenance actions (pause/resume channel, one-click re-verify,
  circuit reset from WebUI); pre-publish probe gate (block publish if platform
  health unknown or red).
- **Phase 3:** Circuit breaker expansion — currently browser-tier only + ban-only
  trip; expand to all platforms + consecutive `AuthExpiredError` / `ExternalServiceError`
  trip without explicit ban keyword.

## Problem Frame

### Five scattered health signals

| Source | What it knows | Gap |
|--------|--------------|-----|
| `health_metrics.build_health()` | 30-day window aggregates (success rate, per-adapter counts, error distribution) | No per-platform last-success/last-failure timestamp; aggregates over all targets, not one per platform |
| `webui_store.channel_status` | Last bind result (status, identity, last_verified_at) | Only tracks channels that ran the bind flow; Medium/Velog/Blogger only |
| `circuit.py` | Trip state + tripped_at | Browser-tier platforms only; not integrated into health display |
| `canary/` | Per-adapter config-contract check | Read-only; no runtime outcome tracking |
| `binding_status.get_channel_status()` | config-completeness per platform | Stateless; no history |

### Current breakage pattern

An operator opens `/ce:health` after a failed overnight run. They see the
success-rate hero number dropped from 91% to 60%. But they cannot tell:
- Which platform started failing?
- When did it first fail?
- Is the circuit open or closed?
- What was the last error message?

They have to correlate `events.db`, `publish-circuit-state.json`, and
channel-status manually.

## Requirements Trace

- **R1.** A single `PlatformHealthRecord` dataclass captures: `last_success_at`,
  `last_failure_at`, `last_error_msg` (redacted of secrets), `consecutive_failures`,
  `circuit_tripped`, `circuit_tripped_at` per platform. Populated from `EventStore`
  + `circuit.py` reads. No network.
- **R2.** `health/aggregate.py` exposes `build_platform_health(config) ->
  dict[str, PlatformHealthRecord]` as the single canonical source. All consumers
  (WebUI route, CLI, future scheduler push) call this one function.
- **R3.** Health state that must survive process boundaries (consecutive failure
  counter, operator-set pause flag) is stored in `<config_dir>/platform-health.json`
  via a new `LockedHealthStore` that uses `fcntl.LOCK_EX` flock on a sibling
  `.lock` file — same pattern as `circuit.py`.
- **R4.** `platform-health` CLI verb prints a per-platform table to stdout
  (JSON with `--json` flag). Reads from `build_platform_health()`. Runs from any
  cwd — no implicit `os.getcwd()` assumptions (see Known Traps).
- **R5.** `/ce:health` route updated to consume `build_platform_health()` for
  the per-platform panel; existing 30-day hero and error-distribution panels
  unchanged.
- **R6.** `last_error_msg` stored in `LockedHealthStore` is redacted: strips any
  token-looking substring (`[A-Za-z0-9_\-]{20,}`) before write.
- **R7.** No behavior change to existing publish pipeline, circuit breaker, or
  binding flow in Phase 1.

## Scope Boundaries

- **Phase 1 only.** Pause/resume, one-click re-verify, circuit reset from WebUI
  are Phase 2 — do not implement.
- **Not** expanding the circuit breaker trip conditions in Phase 1 (Phase 3).
- **Not** adding a `platform-health` scheduler push (Phase 2).
- **Not** adding SLOC ceilings for `webui_app/` to `monolith_budget.toml`.
- **Not** changing `health_metrics.py` `build_health()` — it stays as-is;
  `/ce:health` route calls both during the transition.

## Context & Research

### Existing patterns to follow

- **`circuit.py` flock pattern** (`src/backlink_publisher/publishing/reliability/circuit.py:61–115`):
  `_acquire_lock` / `_release_lock` / `_read_state_unsafe` / `_write_state_unsafe`
  with `atomic_write_json`. `LockedHealthStore` mirrors this exactly.
- **`EventStore` query pattern** (`webui_app/health_metrics.py:132–170`):
  `per_adapter()` queries `publish.*` terminal kinds grouped by platform.
  Use the same `since_utc` approach but query ALL history (no window) for
  `last_success_at` / `last_failure_at`.
- **CLI entrypoint pattern** (`src/backlink_publisher/cli/plan_backlinks/__init__.py`):
  `argparse` + `main()` registered in `pyproject.toml [project.scripts]`.
- **Config-dir CLI pattern** (`src/backlink_publisher/cli/_bind/chrome_backend.py`):
  always derive config from `load_config()`, never `os.getcwd()`.

### Known implementation traps (code-verified)

1. **`build_health()` aggregates are window-scoped, not per-platform last-state.**
   `per_adapter()` in `health_metrics.py` returns counts over a 30-day window —
   it does NOT return the timestamp of the last event per platform. To get
   `last_success_at` / `last_failure_at`, query `EventStore` directly with
   `ORDER BY ts_utc DESC LIMIT 1` per platform per terminal kind.

2. **Circuit breaker is browser-tier only.** `policy.py` only calls `is_tripped()`
   / `trip()` for browser-tier platforms. `build_platform_health()` must read
   `circuit.py::is_tripped()` for ALL registered platforms but treat non-browser
   platforms as always `circuit_tripped=False` until Phase 3.

3. **`verify_adapter_setup` live probe is implemented for telegraph/ghpages/blogger/velog
   only.** Do not call it for other platforms in Phase 1.

4. **Cross-process lost-update.** `LockedHealthStore.update(platform, fn)` must
   hold the flock across the full read-modify-write cycle (same as `circuit.py`).
   The `atomic_write_json` + flock pattern is the correct shape — see
   `[[atomic-write-not-cross-process-rmw-safe]]`.

5. **`last_error_msg` may contain auth tokens.** Strip token-looking substrings
   before storing. Pattern: `re.sub(r'[A-Za-z0-9_\-]{20,}', '[REDACTED]', msg)`.

6. **`platform-health` CLI must not assume cwd.** Load config via
   `load_config()` (which reads `BACKLINK_PUBLISHER_CONFIG_DIR` env or
   `~/.config/backlink-publisher/`). Never use `Path.cwd()` for data paths.
   See `[[webui-lives-at-repo-root-not-src]]`.

7. **`adapters/__init__.py` is near its SLOC ceiling (584/600).** Do not add
   new functions there — add platform-health logic to `health/aggregate.py`.

## Key Technical Decisions

- **Single aggregate function:** `build_platform_health(config)` in `health/aggregate.py`
  is the single canonical source. It reads EventStore (last events per platform)
  + `circuit.py::is_tripped()` + `LockedHealthStore` (consecutive_failures,
  paused flag). Returns `dict[str, PlatformHealthRecord]`.
- **`LockedHealthStore` for mutable state only:** Immutable facts (last_success_at,
  last_failure_at, last_error_msg) are derived live from EventStore. Only
  mutable operator state (consecutive_failures counter, paused flag) needs the
  locked store — this keeps the store small and avoids stale reads.
- **`platform-health` output format:** Default is a human-readable table to
  stdout. `--json` emits JSONL (one record per platform) for downstream piping.
  Exit 0 always unless config load fails.
- **WebUI render strategy:** `/ce:health` route calls `build_platform_health()`
  in addition to `build_health()`. The Jinja template gets a new
  `platform_health` dict alongside the existing `health` object. No template
  refactor in Phase 1 — just add a new panel below the existing ones.

## Implementation Units

```
U1 (health/aggregate.py) ──► U3 (platform-health CLI)
U2 (LockedHealthStore)   ──┘
U1 + U2 ──► U4 (/ce:health display)
```

---

- [x] **Unit 1: `health/aggregate.py` — unified per-platform health source**

**Goal:** `build_platform_health(config) -> dict[str, PlatformHealthRecord]`
that combines EventStore last-events + circuit state + LockedHealthStore
into one callable with no side effects.

**Requirements:** R1, R2, R7

**Dependencies:** U2 (LockedHealthStore); can stub with `{}` to land U1 first
if needed

**Files:**
- Create: `src/backlink_publisher/health/__init__.py`
- Create: `src/backlink_publisher/health/aggregate.py`
- Test: `tests/test_platform_health_aggregate.py`

**Approach:**
- `PlatformHealthRecord` frozen dataclass: `platform: str`, `last_success_at:
  str | None`, `last_failure_at: str | None`, `last_error_msg: str | None`,
  `consecutive_failures: int`, `circuit_tripped: bool`, `circuit_tripped_at:
  str | None`, `paused: bool`.
- Query EventStore for last terminal event per platform:
  `SELECT platform, kind, ts_utc, detail FROM events WHERE kind IN
  ('publish.confirmed','publish.unverified','publish.failed') AND platform=?
  ORDER BY ts_utc DESC, id DESC LIMIT 1` — run once per terminal kind per
  platform. Use `registered_platforms()` as the platform list.
- Call `circuit.is_tripped(platform, config)` for all registered platforms;
  treat non-browser-tier as `False` (circuit returns False for unknown platforms
  already — verify at implementation time).
- Merge with `LockedHealthStore` data for `consecutive_failures` and `paused`.
- `last_error_msg`: take from EventStore `detail` field of last `publish.failed`
  event, apply redaction (R6).

**Test scenarios:**
- Happy path: platform with confirmed + failed events → correct last_success_at,
  last_failure_at, last_error_msg populated.
- Edge case: platform with zero events → all `None` / 0, no crash.
- Edge case: EventStore missing or corrupt → returns empty dict (function must
  not raise).
- Redaction: `last_error_msg` containing a 25-char token → token replaced with
  `[REDACTED]`.
- Circuit: monkeypatch `circuit.is_tripped` to return True → record shows
  `circuit_tripped=True`.

**Verification:**
- `pytest tests/test_platform_health_aggregate.py` passes.
- `from backlink_publisher.health.aggregate import build_platform_health`
  importable from any cwd.

---

- [x] **Unit 2: `LockedHealthStore` — cross-process-safe mutable health state**

**Goal:** File-backed store for mutable per-platform state (consecutive_failures,
paused) protected by flock — same pattern as `circuit.py`.

**Requirements:** R3, R6, R7

**Dependencies:** None (independent)

**Files:**
- Create: `src/backlink_publisher/health/persistence/__init__.py`
- Create: `src/backlink_publisher/health/persistence/locked_store.py`
- Test: `tests/test_locked_health_store.py`

**Approach:**
- Mirror `circuit.py` flock pattern exactly:
  `_acquire_lock` / `_release_lock` / `_read_state_unsafe` / `_write_state_unsafe`.
  State file: `<config_dir>/platform-health.json`.
  Lock file: `<config_dir>/platform-health.lock`.
- `LockedHealthStore.get(platform) -> dict` — returns `{consecutive_failures, paused}`
  with safe defaults if key absent.
- `LockedHealthStore.update(platform, fn: Callable[[dict], dict]) -> None` —
  holds flock across full RMW cycle.
- Fail-CLOSED: read failure returns `{consecutive_failures: 0, paused: False}` —
  does not raise; logs a warning.

**Test scenarios:**
- Happy path: `update` + `get` round-trip returns updated value.
- Concurrent write: spawn two OS processes both calling `update` simultaneously;
  no lost-update (flock serializes them).
- Missing file: `get` on nonexistent path returns safe defaults, no crash.
- Corrupt JSON: `get` returns safe defaults + logs warning.

**Verification:**
- `pytest tests/test_locked_health_store.py` passes.
- Two-process concurrent test passes without flaky failures.

---

- [x] **Unit 3: `platform-health` CLI verb**

**Goal:** `platform-health` entrypoint prints per-platform health table. Reads
from `build_platform_health()`. Respects `--json` for machine-readable output.

**Requirements:** R4, R7

**Dependencies:** U1 (build_platform_health)

**Files:**
- Create: `src/backlink_publisher/cli/platform_health.py`
- Modify: `pyproject.toml` (add console_script entry)
- Test: `tests/test_cli_platform_health.py`

**Approach:**
- `argparse` with `--json` flag and optional `--platform <name>` filter.
- Default output: tabular (platform | last_success | last_failure |
  consecutive_fails | circuit | paused).
- `--json`: emit one JSON object per line to stdout, one per platform.
- Config loaded via `load_config()` — no cwd assumption (Known Trap #6).
- Exit 0 on success; exit 1 if `load_config()` raises.
- stdout = data; stderr = diagnostics (matching existing CLI contract).

**Test scenarios:**
- Happy path: `platform-health` with monkeypatched `build_platform_health`
  returning two platforms → table has two rows on stdout.
- `--json` flag: output is valid JSONL, one object per platform.
- `--platform blogger` filter: only blogger row in output.
- Config missing: exit 1, error on stderr.

**Verification:**
- `pytest tests/test_cli_platform_health.py` passes.
- `python -c "from backlink_publisher.cli.platform_health import main"` works.
- `pyproject.toml` has `platform-health = "backlink_publisher.cli.platform_health:main"`.

---

- [x] **Unit 4: `/ce:health` display refresh**

**Goal:** `/ce:health` WebUI panel shows per-platform last-success, last-failure,
consecutive failures, and circuit state alongside the existing 30-day panels.

**Requirements:** R5, R7

**Dependencies:** U1 (build_platform_health)

**Files:**
- Modify: `webui_app/routes/health.py`
- Modify: `webui_app/templates/health.html`
- Test: `tests/test_webui_health_route.py` (extend or create)

**Approach:**
- In `ce_health()` route, call `build_platform_health(cfg)` inside the existing
  `_build()` inner function (already uses `_g_cache` for config).
- Pass `platform_health=build_platform_health(cfg)` to the template alongside
  existing `health` context.
- Add a new Bootstrap card below the existing "Per-platform health" card:
  "Platform Last-State" table with columns: Platform | Last Success | Last Failure
  | Consec. Failures | Circuit | Paused.
- Use `_g_cache('platform_health', lambda: build_platform_health(cfg))` so
  repeated template renders in one request don't re-query.
- If `build_platform_health` raises: log + pass empty dict — page must not 500.

**Test scenarios:**
- Happy path: GET `/ce:health` returns 200 with `platform_health` key in template
  context.
- Error tolerance: monkeypatch `build_platform_health` to raise → still returns 200.
- Table renders at least one row when monkeypatched data has one platform.

**Verification:**
- `pytest tests/test_webui_health_route.py` passes.
- `GET /ce:health` in test client returns 200 and HTML contains "Last Success".

---

## Phase 2 (shipped 2026-06-03) — Maintenance Actions

- [x] U5: Pause / resume channel — `locked_store.set_paused` / `is_paused` +
  `POST /ce:health/pause`; publish pipeline checks the flag pre-dispatch (U8).
- [x] U6: One-click re-verify button on `/ce:health` per platform —
  `POST /ce:health/reverify` calls `verify_adapter_setup` (offline mode: a
  synchronous web request must not block on a network probe; live probing is
  the pre-publish probe's job).
- [x] U7: Circuit reset button on `/ce:health` — `POST /ce:health/circuit-reset`
  calls the existing `circuit.reset_circuit`; button renders only when the
  breaker is OPEN.
- [x] U8: Pre-publish pause gate — `publish-backlinks` drops paused platforms
  via `_partition_paused` before lease acquisition; all-paused run exits 0 with
  a warning, no dispatch.

WebUI wiring: `webui_app/routes/health_actions.py` (loopback + app-level CSRF),
`static/js/health.js` (delegated `data-action`, CSRF via `postJson`), Actions
column in the Platform last-state panel.

## Phase 3 (shipped 2026-06-03) — Circuit Breaker Expansion

- [x] U9: Circuit breaker now covers ALL platforms — `publish_with_policy` no
  longer passes non-browser-tier platforms straight through; the health gate
  stays browser-scoped (API platforms have no session binding) but `is_tripped`
  now gates every platform.
- [x] U10: Consecutive non-ban `AuthExpiredError` trips after N failures
  (`BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD`, default 3).
- [x] U11: Consecutive `ExternalServiceError` trips after N failures
  (`BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD`, default 5).
- [x] U12: Circuit state surfaces for all platforms in `platform-health` CLI and
  `/ce:health` (shipped Phase 1; this phase made non-browser platforms reachable
  and fixed `circuit_tripped_at` reading the wrong key — `tripped_at_iso`).

Counting reuses `LockedHealthStore.consecutive_failures` (Phase 1's field, now
live): success or a trip resets it (the post-cooldown window starts fresh). All
trip accounting is fail-soft — a health-store fault never escalates a single
failure into a trip. Whole layer remains gated behind
`BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1` (default off).

## System-Wide Impact

- **New module `src/backlink_publisher/health/`**: Isolated; no existing code changes.
- **`pyproject.toml` new entrypoint**: Additive; no breakage.
- **`/ce:health` route**: Error-tolerant addition; existing panels unchanged.
- **`webui_app/` CC backstop**: `build_platform_health` is pure/simple; CC
  should stay below 30. Verify with `radon cc` before landing.
- **`EventStore` queries**: Read-only; no schema changes.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| EventStore `detail` field absent or contains raw exception with token | Redact before store (R6); treat absent as `None` |
| `circuit.is_tripped` raises for non-browser platform | Wrap in try/except; default to `False` |
| `LockedHealthStore` lock file left open on crash | Use `finally` block in acquire/release; same pattern as circuit.py |
| `/ce:health` 500 on `build_platform_health` failure | Catch all exceptions in route; pass `{}` to template |
| `pyproject.toml` entrypoint breaks existing pip install | Only additive; `pip install -e ".[dev]"` re-run required after adding entrypoint |
