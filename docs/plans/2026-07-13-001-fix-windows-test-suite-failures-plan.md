---
title: "fix: Windows local test-suite failures (122 failed / 11 errors)"
type: fix
status: active
date: 2026-07-13
claims: {}
# claims paths deferred until this work merges — plan-check validates claimed
# paths against origin/main; work happens on the current branch,
# feat/operation-progress, or a dedicated fix branch (see Scope Boundaries).
---

# Fix: Windows Local Test-Suite Failures (2026-07-13-001)

## Overview

A full local run of `pytest tests/` on this Windows 10 / Traditional-Chinese
(cp950-locale) machine produced **122 failed, 11 errored, 12960 passed, 68
skipped** out of ~13,161 collected tests (405s runtime, `PYTHONHASHSEED=0`).
This plan triages every failure/error into root-cause clusters and fixes them
in priority order: production-breaking bugs first, then test-safety bugs,
then correctness bugs, then test-portability/hygiene cleanup, with the known
Windows permission-semantics gap explicitly scoped out per the user's
decision (see Key Technical Decisions).

There is no pre-existing "current bug list" document — the three files under
`AppData/Local/backlink-publisher/bug-reports/` are smoke-test artifacts from
building the 2026-07-09-002 bug-report-system feature, not real bugs (user
confirmed the test-suite run as the source of truth for this plan).

## Problem Frame

CI presumably runs on Linux (per `AGENTS.md`'s `PYTHONPATH=src pytest tests/`
convention and the mypy-against-Linux-platform note in this repo's history),
so these 122+11 failures are invisible there. But the user develops and runs
this suite locally on Windows, and roughly a third of the failures are not
platform-semantics noise — they trace to real bugs: a broken Windows file-lock
shim that throws `PermissionError` on real dedup/idempotency CLI operations,
a test-sandbox escape that risks touching the real user profile, and a
config-hash canonicalization bug that makes SHA-based config comparisons
unstable across platforms.

## Requirements Trace

- R1. Every genuine (non-platform-semantics) bug surfaced by the full local
  run is root-caused and fixed, in priority order (production-impact first).
- R2. The Windows POSIX-permission-semantics gap (`os.chmod` not restricting
  NTFS access) is explicitly documented and the affected assertions are
  skipped on `win32`, per the user's decision — not silently ignored, not
  engineered into a full ACL solution.
- R3. Test-only Unix-isms (`os.fork`, `bash` subprocess dependency, macOS
  `.plist` assumptions) either get a Windows-compatible implementation or an
  explicit, clearly-messaged skip — never a silent ERROR.
- R4. After all units land, a fresh full-suite run is used to confirm the
  fix set and re-triage whatever remains (Unit 10).

## Scope Boundaries

- This plan only addresses failures observed in the 2026-07-13 full local
  run. It does not attempt a general Windows-support audit beyond what that
  run surfaced.
- Real NTFS ACL-based credential-file protection on Windows is explicitly
  **not** in scope (see Key Technical Decisions) — tracked as a
  documented, accepted limitation instead.
- The large uncommitted WIP diff currently on `feat/operation-progress`
  (async operation store / worker / SPA task center) is not otherwise
  touched by this plan except where it already caused a test gap (Unit 5's
  `/error-reports` contract-test coverage, which predates that WIP and was
  exposed by it, not caused by it).

### Deferred to Separate Tasks

- Re-pushing/merging `feat/operation-progress` itself: separate, tracked
  by that branch's own feature work — this plan only fixes test-suite bugs
  it happens to run alongside.

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/_compat/fcntl.py` — Windows `flock()` shim used by
  `idempotency/audit_log.py`, `idempotency/store.py`, `image_gen` token
  rotation, `reliability/circuit.py`, and others wherever real `fcntl` is
  unavailable.
- `tests/conftest.py` — pre-import `HOME`/sandbox redirect (Plan
  2026-05-27-005 Unit 3), exercised by `tests/test_home_redirect_pre_import.py`.
- `src/backlink_publisher/config_echo.py::_canonicalise_for_sha` — the
  deterministic-representation function used to compute config/state SHAs.
- `tests/test_no_inner_import_shadowing.py` / `tests/test_protected_set_coverage.py`
  — both already scan `webui_app/`, `webui_store/`, and adapters correctly
  (`_SCAN_ROOTS` includes them, `read_text(encoding="utf-8")` is already
  correct there) — their failures are assertion-string bugs, not scan bugs.
- `src/backlink_publisher/events/persona.py::_ensure_salt` — binary-safe
  `os.open`/`os.write`/`os.link` salt-provisioning path.
- `webui_app/routes/llm.py` + `src/backlink_publisher/llm/http_guard.py` —
  the SSRF-guarded LLM POST call path and its `ALLOWLIST`-gated raw-`requests`
  scanner test.
- `docs/plans/2026-07-09-002-feat-error-bug-report-system-plan.md` — origin
  of the `/error-reports` routes that Unit 5 closes contract-test coverage
  for.

### Institutional Learnings

- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
  — already documents the exact `os.environ` direct-mutation anti-pattern
  Unit 8 fixes; this is a known, previously-diagnosed failure mode recurring
  in a new file.
- Memory: `project_comprehensive_opt_plan_status.md` records a prior,
  **already-fixed** cp950 crash in mypy config loading (D2', done
  2026-07-13, unrelated file). Unit 9's cp950 `UnicodeDecodeError` is a
  **new, distinct occurrence** of the same locale-dependent-encoding bug
  class in different files (`tests/test_bp_registry.py`,
  `tests/test_cli_typed_error_emission.py`) — not a regression of the fixed
  one.

## Key Technical Decisions

- **Windows permission-semantics gap → document + skip, not fix (Unit 6):**
  confirmed with the user. `os.chmod(0o600)` does not restrict NTFS access
  the way it does on POSIX (observed as `0o666`/`0o777` actual modes across
  ~45-50 assertions). Implementing real Windows ACL enforcement (`icacls`/
  `pywin32`) was considered and explicitly rejected as out of scope for a
  bug-fix pass — it is a security feature, not a bug fix, and belongs in its
  own plan if the user wants real Windows credential protection later.
- **Fix the Windows `flock` shim rather than remove locking (Unit 1):**
  the alternative — dropping the lock/unlock calls under `_compat/fcntl.py`
  on Windows — would silently reintroduce the concurrent-write races the
  locking exists to prevent. Anchoring the `msvcrt.locking()` region at a
  fixed offset preserves the intended whole-file exclusive-lock semantics.
- **`_canonicalise_for_sha` must use `Path.as_posix()`, not `str(Path)`
  (Unit 3):** the function's own docstring commits to "deterministic
  representation" for SHA computation; `str(Path)` is platform-dependent and
  breaks that contract. This is treated as a correctness bug, not a
  Windows-only test artifact, because it affects any config/state hash
  computed on Windows being compared against one computed elsewhere.
- **Persona-salt byte-count bug (Unit 4) is scoped as investigate-then-fix,
  not pre-diagnosed:** the write path (`os.open`/`os.write`/`os.link`) is
  already binary-safe and already has a Windows-specific `chmod` skip, so
  the 33-vs-32-byte discrepancy doesn't match any of this plan's other root
  causes. Rather than guess, Unit 4 starts with a minimal repro script to
  pin the exact root cause before changing production code.

## Open Questions

### Resolved During Planning

- "Which bug source should this plan target?" → user selected "run the test
  suite and treat real failures as the bug list" over the captured
  bug-report smoke-test files or the WIP branch.
- "How to handle the Windows chmod/NTFS-permission gap?" → user selected
  "document as a known limitation, skip the assertions on Windows" over
  implementing real ACL enforcement or leaving the ~45-50 tests failing.

### Deferred to Implementation

- Exact byte(s) responsible for the persona-salt 33-vs-32 discrepancy (Unit
  4) — requires a live repro on this machine, not resolvable from static
  reading of `persona.py`.
- Whether `test_bind_channel_chrome_backend.py`'s availability check should
  be fixed or `skipif`'d — depends on whether a real Chrome binary +
  reachable websocket is expected to be present in this dev environment
  (Unit 7).
- Whether any additional `Path.read_text()`/`open()` call sites elsewhere in
  the codebase share Unit 9's missing-`encoding="utf-8"` pattern — Unit 9
  includes an explicit grep-audit step to find out, since this pattern has
  now recurred twice (mypy config, and now these two test helpers).

## Implementation Units

- [ ] **Unit 1: Fix Windows `flock` shim lock/unlock region mismatch**

**Goal:** Stop `_compat/fcntl.py`'s Windows `flock()` shim from raising
`PermissionError` on unlock, which currently breaks real dedup/idempotency
CLI operations (not just tests) on Windows.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/_compat/fcntl.py`
- Test: `tests/test_dedup_adjudicate.py`, `tests/test_dedup_enforce_gate.py`,
  `tests/test_dedup_force_manifest.py`, `tests/test_dedup_operator_verbs.py`,
  `tests/test_idempotency_backfill.py`,
  `tests/test_image_gen_token_rotation.py` (the 3 concurrency-flock tests),
  `tests/test_io_atomic_crossproc.py`, `tests/test_reliability_circuit.py`
  (`test_concurrent_trip_barrier`), `tests/test_reliability_circuit_crossproc.py`,
  `tests/test_secrets.py` (`test_rotation_archives_old_key_and_writes_new`)

**Approach:**
- Root cause (confirmed via traceback): `msvcrt.locking(fd, op, nbytes)`
  locks/unlocks `nbytes` starting at the file descriptor's *current seek
  position*, and moving the position afterward. Callers following the
  standard lock → write → unlock pattern (e.g.
  `idempotency/audit_log.py::append_entry`, which opens with `O_APPEND`)
  have their write advance the fd position between the `LOCK_EX` and
  `LOCK_UN` calls, so the unlock call targets a different byte than the one
  that was locked, and Windows returns `PermissionError: [Errno 13]`.
- Fix direction: inside `flock()`, before issuing either the lock or unlock
  `msvcrt.locking()` call, save the fd's current position, seek to a fixed
  anchor offset (0), perform the locking operation, then restore the
  original position. This keeps every `flock()` call — regardless of what
  the caller did to the fd in between — operating on the same 1-byte region,
  matching the whole-file-exclusive semantics every call site actually
  wants.

**Execution note:** Add a focused regression test for the lock→write→unlock
sequence directly against the shim (not just via the higher-level dedup/
idempotency tests) before changing the implementation, since the existing
failures already characterize the bug — treat this as the starting
characterization test.

**Test scenarios:**
- Happy path: `flock(fd, LOCK_EX)` → `os.write(fd, ...)` (position advances)
  → `flock(fd, LOCK_UN)` succeeds without raising.
- Happy path: the full existing `tests/test_dedup_*`, `tests/test_idempotency_*`
  suites pass unmodified once the shim is fixed (no test-side changes
  needed — this is a pure production-code fix).
- Integration: `tests/test_reliability_circuit_crossproc.py`'s
  cross-process concurrent-trip test (two real subprocesses contending for
  the same lock) still serializes correctly after the fix.

**Verification:**
- All test files listed above pass on this Windows machine.
- No new `PermissionError` from `_compat/fcntl.py` anywhere in a full
  suite run.

- [ ] **Unit 2: Fix `Path.home()` sandbox redirect on Windows**

**Goal:** Ensure the test-suite's HOME sandbox redirect actually redirects
`Path.home()` on Windows, closing a real risk of tests writing into the
operator's actual `~/.config`/`~/.cache` during a Windows test run.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_home_redirect_pre_import.py`

**Approach:**
- Root cause (confirmed via traceback): the sandbox fixture sets
  `os.environ["HOME"]`, which `tests/test_home_redirect_pre_import.py`'s own
  `test_home_env_var_redirected_to_sandbox`-style check already confirms
  works. But Python's `pathlib.Path.home()` on Windows resolves via
  `USERPROFILE` (not `HOME`), so `Path.home()` still returns the real
  profile directory — `test_path_home_resolves_to_sandbox_during_tests` is
  the one check that actually exercises `Path.home()` and it fails.
- Fix direction: when redirecting HOME for the sandbox on `win32`, also set
  `USERPROFILE` (and `HOMEDRIVE`/`HOMEPATH` if any code path relies on
  those instead) to the sandbox directory, alongside the existing `HOME`
  redirect.

**Test scenarios:**
- Happy path: `Path.home()` returns the sandbox directory during a test run
  on Windows (`test_path_home_resolves_to_sandbox_during_tests` passes).
- Integration: git subprocess tests that rely on `HOME`/`USERPROFILE` being
  propagated (the blast-radius check already in
  `test_home_redirect_pre_import.py`) still pass — the redirect must not
  break subprocess `git` invocations.

**Verification:**
- `tests/test_home_redirect_pre_import.py` passes in full on Windows.

- [ ] **Unit 3: Fix platform-dependent path canonicalization**

**Goal:** Make config/state SHA canonicalization and related path-to-string
comparisons stable across platforms instead of leaking Windows'
backslash-separated `str(Path)` representation into hashes and assertions.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/config_echo.py`
- Modify: `src/backlink_publisher/_util/fail_closed_resolver.py` (verify
  exact path/module name during implementation — confirm via the failing
  test's import)
- Modify: `tests/test_no_inner_import_shadowing.py`
  (`test_scanner_recurses_into_webui_and_adapters`)
- Modify: `tests/test_protected_set_coverage.py`
  (`test_scanner_recurses_into_adapters_and_webui`)
- Test: `tests/test_config_echo.py`, `tests/test_fail_closed_resolver.py`,
  `tests/test_config_managed_root_subsection_roundtrip.py`

**Approach:**
- Root cause (confirmed): `config_echo.py::_canonicalise_for_sha` does
  `if isinstance(value, Path): return str(value)`. On Windows this yields
  `\tmp\x`-style strings instead of the POSIX-style `/tmp/x` the function's
  own "deterministic representation" docstring promises. Fix: use
  `value.as_posix()` instead of `str(value)`.
- `fail_closed_resolver`'s `test_config_dir_returns_override_when_set` /
  `test_cache_dir_returns_override_when_set` show the identical symptom
  (`'\tmp\bp-test-config' == '/tmp/bp-test-config'`) — verify during
  implementation whether the resolver itself needs the same `as_posix()`
  fix, or whether (given the name "fail_closed_resolver") the correct
  direction is instead a POSIX-normalizing helper shared with
  `config_echo.py` to avoid duplicating the fix.
- The two scanner-test failures are a *different* instance of the same
  separator assumption, but in test code, not production code: both
  `_SCAN_ROOTS` already correctly include `webui_app`/`webui_store`, and
  both already read files with `encoding="utf-8"` — the assertions
  themselves (`p.startswith("webui_app/")`, checking for `"publishing/adapters"`
  substring) use a hardcoded forward slash against a Windows-native
  backslash-separated string, so they fail even when the scan succeeded.
  Fix by normalizing (`Path(p).as_posix()` or `p.replace(os.sep, "/")`)
  before the string check, or by checking `Path(p).parts` membership
  instead of a substring/prefix match.

**Test scenarios:**
- Happy path: `_canonicalise_for_sha(Path("/tmp/x"))` returns `"/tmp/x"` on
  Windows (currently returns `"\\tmp\\x"`).
- Happy path: a config/state SHA computed for the same logical config is
  identical whether computed via a POSIX-style or Windows-style `Path`
  input.
- Happy path: `test_scanner_recurses_into_webui_and_adapters` and
  `test_scanner_recurses_into_adapters_and_webui` pass on Windows without
  weakening what they actually verify (scan reaches `webui_app`/`webui_store`/
  adapters).
- Edge case: `fail_closed_resolver`'s override-path tests pass with a
  Windows-style override path input and reference a POSIX-style expected
  output for the resolved dir.

**Verification:**
- `tests/test_config_echo.py`, `tests/test_fail_closed_resolver.py`,
  `tests/test_config_managed_root_subsection_roundtrip.py`,
  `tests/test_no_inner_import_shadowing.py`,
  `tests/test_protected_set_coverage.py` all pass on Windows.

- [ ] **Unit 4: Investigate and fix persona-salt byte-count corruption on Windows**

**Goal:** Determine why a 32-byte `os.urandom` persona salt round-trips as
33 bytes on Windows, and fix it.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/events/persona.py` (pending root-cause
  confirmation)
- Test: `tests/test_events_persona.py`

**Execution note:** Investigate-then-fix. Write a minimal standalone repro
(`_ensure_salt`/`_read_validated_salt` round-trip in isolation, outside
pytest, on this Windows machine) before touching production code — the
write path (`os.open`/`os.write` loop/`os.fsync`/`os.link`) is already
binary-safe and doesn't match any of this plan's other diagnosed root
causes (not the `flock` bug, not a text-mode/CRLF issue per the raw-fd
write), so guessing the fix without a repro risks masking rather than
fixing the bug.

**Approach:**
- Starting hypotheses to rule in/out during the repro: (a) `os.link()`
  hardlink semantics differing on NTFS such that the linked file observes a
  different byte count than the source tmpfile; (b) a race between the two
  `persona.persona_id()` calls in the failing test (`_load_salt.cache_clear()`
  between them) causing a second provisioning attempt to layer onto the
  first; (c) an off-by-one in how the tmpfile name/pid-suffix path itself
  is being written to, if the tmp/final path resolution differs on Windows.
- Once root-caused, fix at the specific step identified rather than
  broadening the change beyond what the repro demonstrates.

**Test scenarios:**
- Happy path: `persona.persona_id()` called twice in succession (with an
  intervening `_load_salt.cache_clear()`) returns the same persona ID both
  times, and the on-disk salt file is exactly 32 bytes
  (`test_persona_id_stable_across_calls_with_fresh_cache`).
- Happy path: a pre-seeded 32-byte salt file is read back unchanged
  (`test_existing_salt_file_is_read_back`).
- Regression: whatever the confirmed root cause is, add a scenario that
  fails before the fix and passes after — the existing two failing tests
  may already suffice if they precisely capture it.

**Verification:**
- `tests/test_events_persona.py` passes in full on Windows.

- [ ] **Unit 5: Close `/error-reports` contract-test gap and fix stale SSRF-guard test**

**Goal:** Add missing route-contract-test coverage for the shipped
`/error-reports` WebUI routes, and fix the now-stale SSRF-redirect-guard
test + `ALLOWLIST` entry left over from an `http_guard`/`http_client`
migration.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/test_webui_core_routes.py`
- Modify: `tests/test_no_raw_requests_outside_http_client.py`
- Modify: `tests/test_webui_unit3_security.py`
  (`TestLlmSsrfRedirectGuard::test_safe_post_json_rejects_redirect`)

**Approach:**
- `test_every_route_has_at_least_one_contract_test` reports
  `['/error-reports', '/error-reports/<report_id>']` as uncovered — these
  are the routes shipped by
  `docs/plans/2026-07-09-002-feat-error-bug-report-system-plan.md`'s
  `webui_app/api/v1/error_report_bundle.py`. Add at least one
  `client.get(...)`/`client.post(...)` call per route to
  `tests/test_webui_core_routes.py` (or wherever this suite's convention
  puts route-contract tests), matching the existing pattern for other
  routes in that file.
- `test_no_new_raw_requests_call_sites` reports the `ALLOWLIST` entry for
  `src/backlink_publisher/llm/http_guard.py:103` as stale — the call at
  that location now goes through `_SESSION.post(...)` (already migrated to
  a guarded session), so the raw-call allowlist entry (and its accompanying
  explanatory comment referencing `http_guard.py:103`) should be removed.
- `test_safe_post_json_rejects_redirect` monkeypatches
  `webui_app.routes.llm.requests.post` directly, but `_safe_post_json` in
  that module appears to have been migrated to call through the guarded
  session/`http_guard` path instead of raw `requests.post` — the same
  migration that made the `ALLOWLIST` entry stale. Update the test to patch
  the actual current call site (verify exact target during implementation
  by reading `webui_app/routes/llm.py::_safe_post_json`), preserving the
  test's intent: a 307 redirect response must raise
  `ValueError("redirect_not_allowed")`.

**Test scenarios:**
- Happy path: `client.get("/error-reports")` and
  `client.get("/error-reports/<id>")` (or `post`, matching the route's
  actual verb) are exercised in `tests/test_webui_core_routes.py`.
- Happy path: `test_no_new_raw_requests_call_sites` passes with no stale
  allowlist entries.
- Error path: `test_safe_post_json_rejects_redirect` still asserts a 307
  response raises `ValueError` matching `"redirect_not_allowed"`, now
  patching the correct call site.

**Verification:**
- `tests/test_webui_core_routes.py`,
  `tests/test_no_raw_requests_outside_http_client.py`,
  `tests/test_webui_unit3_security.py` all pass.

- [ ] **Unit 6: Document Windows permission-semantics gap and skip affected assertions**

**Goal:** Per the confirmed decision, stop the ~45-50 permission-strictness
assertions from failing on Windows by skipping them there, with an explicit
documented rationale — not a silent pass.

**Requirements:** R2

**Dependencies:** None (independent of Units 1-5, but sequenced after them
so real bugs aren't accidentally skipped alongside genuine platform noise)

**Files:**
- Modify: `tests/test_io_utils.py`, `tests/test_jsonl_atomic_stream.py`,
  `tests/test_idempotency_store.py` (`test_store_files_are_0600`),
  `tests/test_image_gen_token_rotation.py` (the 0600/0700 mode assertions,
  not the flock ones already covered by Unit 1),
  `tests/test_secrets.py` (the mode-assertion tests, not
  `test_rotation_archives_old_key_and_writes_new` which is Unit 1's),
  `tests/test_registry_credential_saver.py`, `tests/test_reliability_circuit.py`
  (`test_state_file_created_with_0600_perms`),
  `tests/test_webui_store_channel_status_sqlite.py`,
  `tests/test_webui_store_drafts_sqlite.py`,
  `tests/test_webui_store_profiles_sqlite.py`,
  `tests/test_webui_store_queue_sqlite.py`,
  `tests/test_webui_store_schedule_sqlite.py`,
  `tests/test_webui_store_sqlite_base.py`,
  `tests/test_save_config_section_taxonomy_canary.py`,
  `tests/test_frw_login.py`, `tests/test_credential_service.py`,
  `tests/test_comment_outreach_status_store.py`,
  `tests/test_gitlabpages_adapter.py`, `tests/test_hackmd_adapter.py`,
  `tests/test_mataroa_adapter.py`, `tests/test_provider.py`,
  `tests/test_session_package.py`, `tests/test_settings_service.py`,
  `tests/test_webui_llm_test_persist.py`,
  `tests/test_webui_core_routes.py` (`TestSecretLeakRegression`),
  `tests/test_purge_removed_credentials.py`
  (`test_symlink_is_refused_not_followed` — symlink creation itself
  requires elevated privilege on unprivileged Windows accounts, same
  category of platform gap)
- Create or modify: a shared pytest marker/fixture (e.g. in
  `tests/conftest.py`) for "POSIX-permission-strictness" so each test file
  applies one consistent skip mechanism rather than 20+ ad-hoc
  `sys.platform` checks
- Create: a short docs note (e.g. `AGENTS.md` "Known limitations" section,
  or a new `docs/solutions/` entry) stating that Windows builds of
  backlink-publisher do not restrict credential/config file access at the
  OS level, and why.

**Approach:**
- Prefer a single shared `skipif`/marker (e.g.
  `@pytest.mark.skipif(sys.platform == "win32", reason="...")` applied via
  a helper, or a `posix_permissions_only` fixture that skips at setup) over
  editing 40+ individual assertions inline, to keep the intent
  discoverable and avoid drift.
- Do not weaken what these tests verify on POSIX — the skip only applies on
  `win32`.

**Test scenarios:**
- Test expectation: none — this unit changes test *skip conditions* and
  documentation, not application behavior. Verification is that the
  affected tests report `skipped` (not `passed` via a weakened assertion,
  and not `failed`) on Windows, and still run and pass unmodified on
  POSIX/CI.

**Verification:**
- A full Windows run shows the ~45-50 previously-failing permission tests
  as `skipped`, with a clear skip reason string.
- The new docs note exists and accurately describes the limitation.

- [ ] **Unit 7: Fix or skip remaining Windows-only test-portability failures**

**Goal:** Resolve the smaller, independent Windows-portability issues that
don't fit Units 1-6's clusters, each with a Windows-compatible
implementation or an explicit skip — never a silent ERROR.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Modify: `tests/test_events_store_lease.py`
  (`test_pid_alive_false_for_dead_process`)
- Modify: `tests/test_idempotency_store.py`
  (`test_attempting_with_dead_pid_is_stale`)
- Modify: `tests/test_phase0_seal_hook.py` (9 ERRORs) and/or
  `scripts/install-pre-push-hook.sh` invocation site
- Modify: `tests/test_keepalive_plist.py`
- Modify: `tests/test_bind_channel_chrome_backend.py`
  (`test_available_when_binary_and_websocket_present`)
- Possibly modify: `src/backlink_publisher/idempotency/store.py` or
  wherever `is_stale_attempting`'s liveness check lives (pending
  investigation)

**Approach:**
- `test_pid_alive_false_for_dead_process` calls `os.fork()`, which doesn't
  exist on Windows. Replace with a cross-platform way to obtain a
  guaranteed-dead PID (e.g. `subprocess.Popen` a short-lived child, `wait()`
  it, reuse its now-recycled-or-dead pid) or `skipif(sys.platform == "win32")`
  if the codebase already has a Windows-specific liveness-check test
  elsewhere.
- `test_attempting_with_dead_pid_is_stale` shows `is_stale_attempting`
  returning `False` for pid `2_147_483_000` on Windows — investigate whether
  the liveness probe (likely `os.kill(pid, 0)`-based, which behaves
  differently or raises differently on Windows) needs a Windows branch, or
  whether the fabricated PID needs to be Windows-realistic (Windows PIDs
  are typically much smaller than `2**31`, so the "clearly dead" fixture
  value may need adjusting per-platform instead of the production code
  changing).
- `test_phase0_seal_hook.py`'s 9 ERRORs are `subprocess.run(["bash",
  "scripts/install-pre-push-hook.sh"], ...)` exiting 127 (command not
  found) when invoked from the native-Windows `.venv` Python, even though
  this session runs inside Git Bash. Resolve `bash` explicitly (e.g.
  `shutil.which("bash")`, falling back to the Git-for-Windows install path)
  rather than relying on bare `"bash"` resolving via the child process's
  inherited `PATH`; if no `bash` can be found, `skip()` the fixture with a
  clear message instead of erroring.
- `test_keepalive_plist.py` tests a macOS `launchd` `.plist` — add
  `skipif(sys.platform != "darwin")` if not already conditional.
- `test_available_when_binary_and_websocket_present` — determine during
  implementation whether this dev environment is expected to have a real
  Chrome binary + reachable websocket; if not, `skipif`, if so, fix the
  probe.

**Test scenarios:**
- Happy path: each fixed test passes on Windows using a real (not
  Unix-only) mechanism.
- Test expectation for `test_keepalive_plist.py`: none beyond confirming it
  now reports `skipped` (not `failed`) on non-macOS.
- Edge case: the `is_stale_attempting` fix (whichever side it lands on)
  still correctly reports `True` for a genuinely-dead PID and `False` for a
  live one, on both platforms.

**Verification:**
- All test files listed above pass or explicitly skip (never error) on
  Windows.

- [ ] **Unit 8: Fix `os.environ` test-isolation leak in `test_locked_health_store.py`**

**Goal:** Stop `test_concurrent_writes_no_lost_update` from leaving
`BACKLINK_PUBLISHER_CONFIG_DIR` mutated in `os.environ` after teardown,
which trips the `_env_isolation_guard` autouse fixture and cascades into 9
downstream `test_phase0_seal_hook.py` errors in the same session (per
Unit 7, those also have their own independent root cause — re-verify
after this fix whether any of the 9 were solely caused by this leak).

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/test_locked_health_store.py`

**Approach:**
- This is a previously-documented anti-pattern:
  `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`.
  Replace whatever direct `os.environ["BACKLINK_PUBLISHER_CONFIG_DIR"] = ...`
  / `del os.environ[...]` call `test_concurrent_writes_no_lost_update` makes
  with `monkeypatch.setenv(...)`/`monkeypatch.delenv(...)`, which
  auto-reverts on teardown before the isolation guard checks.

**Test scenarios:**
- Happy path: `test_concurrent_writes_no_lost_update` passes and leaves
  `os.environ` unmutated after teardown.
- Integration: re-run the full suite after this fix and Unit 7's
  `test_phase0_seal_hook.py` fix independently, to confirm whether the 9
  `test_phase0_seal_hook.py` errors were partly a leak cascade or purely
  the `bash`-not-found issue (update Unit 7/10 notes accordingly if the
  cause turns out to be mixed).

**Verification:**
- `tests/test_locked_health_store.py` passes with no isolation-guard
  failure.

- [ ] **Unit 9: Fix cp950-locale `UnicodeDecodeError` in test helpers, audit for recurrence**

**Goal:** Fix the two test helpers that crash reading repo source files
under this machine's cp950 default locale, and check whether the same
missing-`encoding="utf-8"` pattern recurs elsewhere (it has now appeared
twice: previously in mypy config loading, per memory's already-fixed D2',
and now here).

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/test_bp_registry.py` (`_pyproject_commands()`)
- Modify: `tests/test_cli_typed_error_emission.py`
  (`_bare_nonzero_systemexits` / wherever it calls `path.read_text()`)

**Approach:**
- Root cause (confirmed): both call `Path.read_text()` without an explicit
  `encoding=`, so Python falls back to the OS locale encoding — cp950
  (Traditional Chinese) on this machine — which cannot decode UTF-8
  em-dashes/other non-ASCII bytes present in `pyproject.toml` and the CLI
  source files. Fix: add `encoding="utf-8"` to both calls.
- Audit step: grep the repo (`src/`, `webui_app/`, `webui_store/`, `tests/`)
  for other bare `.read_text()`/`open(...)` calls without an explicit
  encoding, to catch any other latent occurrences of this recurring bug
  class before they surface on another cp950/non-UTF8-locale machine. Fix
  any genuine hits found; note-only (no fix) for call sites that
  demonstrably always read ASCII-only content.

**Test scenarios:**
- Happy path: `tests/test_bp_registry.py::test_bp_groups_cover_all_pyproject_commands`
  and `test_bp_groups_contain_no_unknown_commands` pass under a cp950
  locale.
- Happy path: all 8 parametrized
  `test_cli_typed_error_emission.py::test_no_fatal_exit_bypasses_chokepoint`
  cases pass under a cp950 locale.
- Regression: the audit step's grep output is captured in the PR/commit
  description (or a short note in this plan's checkbox) so the search isn't
  silently lost if nothing else needs fixing.

**Verification:**
- `tests/test_bp_registry.py` and `tests/test_cli_typed_error_emission.py`
  pass on this machine.

- [ ] **Unit 10: Full-suite re-run and residual triage**

**Goal:** Confirm Units 1-9 collectively fix what they claim to, and
produce a short, current list of whatever remains (there is a known
residual list below that hasn't been individually root-caused).

**Requirements:** R4

**Dependencies:** Units 1-9

**Files:**
- None (verification-only unit; may produce follow-up notes/tickets, not
  code changes, unless residual triage reveals a quick fix)

**Approach:**
- Re-run `PYTHONHASHSEED=0 .venv/Scripts/python.exe -m pytest tests/ -q`
  in full.
- Confirm the previously-failing tests named in Units 1-9 now pass or skip
  as designed.
- Triage the residual list below (not yet root-caused in this plan; keep
  investigation minimal per Phase-3.6 guidance, defer deep dives to a
  follow-up unit/plan if any turn out non-trivial):
  `test_phase0_seal_init.py::test_init_manual_happy`,
  `test_pipeline_inprocess_characterization.py::test_report_anchors_stdin_aggregate_markdown`,
  `test_cli_recheck_backlinks.py::test_batch_budget_exhaustion_defers_remaining`,
  `test_webui_store_sqlite_base.py::TestBaseSqliteStoreTemplate::test_migrate_happy_path`,
  `test_config_managed_root_subsection_roundtrip.py` (re-check after Unit
  3 — may already be resolved).

**Test scenarios:**
- Test expectation: none — this is a verification/triage unit, not new
  behavior.

**Verification:**
- Full-suite pass/fail/skip counts recorded before/after; only the
  residual list (or an empty list) remains failing, with each residual item
  either scoped into a follow-up or explicitly accepted.

## System-Wide Impact

- **Interaction graph:** Unit 1's `flock` fix touches every call site that
  imports `_compat.fcntl` as a fallback for real `fcntl` — dedup ops,
  idempotency store, image-gen token rotation, reliability circuit. Unit 3's
  `_canonicalise_for_sha` fix touches anything that hashes a config/state
  object containing a `Path` field.
- **Error propagation:** Unit 1's fix must not change the exception type
  raised on a genuine lock contention (`OSError`/`errno.EAGAIN` for
  non-blocking attempts) — only the spurious unlock-position mismatch is
  being fixed.
- **State lifecycle risks:** Unit 4's investigation must confirm the salt
  file is never observed in a torn/partial state during the fix — the
  existing `_ensure_salt` docstring's durability guarantees (fully
  populated or absent, never partial) must hold after the change.
- **Unchanged invariants:** POSIX (Linux/macOS) behavior is unchanged by
  every unit in this plan except Unit 3 (which fixes a real cross-platform
  hash-stability bug that also affects POSIX-computed hashes being compared
  against Windows-computed ones) — Units 1, 2, 6, 7, 8, 9 are Windows-only
  or test-only in effect.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 1's `flock` fix changes locking semantics subtly enough to reintroduce a race under real concurrent load (not just the test's simulated concurrency) | Keep the fix minimal (anchor offset only, no change to lock/unlock call structure); rely on `test_reliability_circuit_crossproc.py`'s real multi-subprocess test as the strongest signal, not just single-process unit tests |
| Unit 4 ships a fix without a confirmed root cause (guessing) | Explicit execution note requires a standalone repro before any production-code change |
| Unit 6's shared skip marker accidentally also skips a test that verifies something beyond permission bits (over-broad skip) | Review each skipped assertion individually when adding the marker, not a blanket file-level skip |
| Unit 9's audit step finds a large number of additional bare-encoding call sites, expanding scope | Cap the audit to a fix-what's-clearly-broken pass; anything ambiguous gets noted, not force-fixed, in this plan |

## Sources & References

- Full local test run: `pytest tests/ -q --no-header`, `PYTHONHASHSEED=0`,
  Windows 10, cp950 locale, 2026-07-13 — 122 failed, 11 errored, 12960
  passed, 68 skipped, 405.29s.
- `docs/plans/2026-07-09-002-feat-error-bug-report-system-plan.md` (origin
  of Unit 5's `/error-reports` routes)
- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
  (Unit 8)
- Related code: `src/backlink_publisher/_compat/fcntl.py`,
  `src/backlink_publisher/config_echo.py`,
  `src/backlink_publisher/events/persona.py`, `tests/conftest.py`
