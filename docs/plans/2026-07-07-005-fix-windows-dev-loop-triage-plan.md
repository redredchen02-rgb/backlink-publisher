---
title: Sequential Bug Triage & Fix — Windows Local Dev Loop (mypy + pytest)
type: fix
status: shipped
date: 2026-07-07
deepened: 2026-07-07
---

## Final Status (2026-07-07, end of execution)

All 7 units complete. `python -m mypy src/backlink_publisher --config-file mypy.ini` runs to completion (72 platform-mismatch findings on win32, 0 with `--platform linux`, neither a fix target). Full-suite sweep (`pytest tests/ -q -n auto --timeout=120`, `PYTHONHASHSEED=0`): **1 failed, 12959 passed, 72 skipped** — down from the original 147 failed/10 errors. The 1 remaining failure (`test_cli_timing_regression.py::test_import_times_within_regression_threshold`) is a load-sensitive performance-threshold test that passes cleanly in isolation (confirmed) — it fails only when the system is busy running the other ~13,000 tests in parallel, unrelated to any Windows-compatibility bug this plan targets.

Beyond this plan's originally-scoped 5 categories, execution surfaced and fixed several additional real, previously-undiscovered bugs (some by this session, some by the concurrent uncommitted work described below, reconciled together): a salt/HMAC-token corruption bug (missing `os.O_BINARY` on Windows silently mangling random bytes containing a `0x0A` byte), a non-deterministic cross-platform config SHA (`str(Path)` vs `.as_posix()`), a Windows CRT text-mode subprocess-output crash in the pre-push-hook installer, a `_credential_audit` false-positive-on-Windows gap, a transient `PermissionError` on concurrent `atomic_write_json` replaces, a stale `core.hooksPath` in this checkout's local git config, a resource leak in `_db_stats`, and a path-serialization bug in the phase0-seal manual-verdict flow.

---

# Sequential Bug Triage & Fix — Windows Local Dev Loop (mypy + pytest)

## Overview

The request was "依序排查BUG 依序修復提出完整計畫" (sequentially find bugs, fix them in order, give a complete plan) with no bug list supplied. Per user selection, the ground-truth bug source is: **run the full lint/typecheck/test sweep locally and treat real failures as the bug list.**

That sweep was executed on this machine (Windows 10, `backlink-publisher/.venv`, non-UTF‑8 system locale `cp950`) and produced an initial reading of:

- `python -m mypy src/backlink_publisher --config-file mypy.ini`: **crashes immediately**, zero output (`UnicodeDecodeError` reading `mypy.ini`).
- `pytest tests/ -q -n auto --timeout=120` (`PYTHONHASHSEED=0`): **147 failed, 10 errored, 12812 passed, 57 skipped** out of 12969 collected tests.
- Frontend (`npm run typecheck`, `npm run lint`, `npm run build`, `npm run test -- --run`): **all clean** (57/57 test files, 494/494 tests). Frontend is out of scope for this plan.

**This number is not stable and should not be treated as precise.** Two things were discovered during this plan's own review pass, both confirmed by direct re-execution, not just re-reading:

1. **Repeated identical sweeps on unchanged code disagree with each other by dozens of tests** (`-n auto` xdist nondeterminism plus at least one genuinely flaky cross-process lock test — see Unit 3). Runs taken minutes apart on this exact plan's own code produced 147, then later 111, then 104, then 99 failed, with the error count steady at 10. Treat every failure count in this document as an order-of-magnitude signal, not an exact figure — re-measure before trusting any of them at implementation time.
2. **This workspace's `backlink-publisher/.venv` and working tree are shared with at least one other, concurrent, uncommitted line of work** that is independently fixing an overlapping — in some cases identical — set of Windows-compatibility bugs right now. See "Concurrent Uncommitted Work Discovered" immediately below; it materially changes what several of this plan's units still need to do.

Root-causing the red results (after separating what's already fixed by the concurrent work from what remains) still shows the same **5 real, fixable issue categories** plus one already-large, already-known, already-partially-documented class of platform noise. This plan fixes what's left in dependency/impact order.

## Concurrent Uncommitted Work Discovered

While writing and reviewing this plan, `git status`/`git diff` on the shared working tree showed uncommitted, in-progress changes — not authored by this planning session — to several of the exact files this plan targets. `git stash list` in this repo already carries an explicit note from a prior session flagging this exact hazard as recurring ("SAFETY: unintended checkout artifact on main worktree ... may contain another session's WIP"). Confirmed via direct test re-runs, the working tree **already contains, uncommitted:**

- **Unit 1's symptom (stale editable install) is already resolved.** `pip show backlink-publisher` now reports the correct `backlink-publisher/` location (it reported the deleted `bp-main-reconcile` worktree when this plan's Overview sweep was first run); the ~28 subprocess-based CLI tests this plan attributed to that bug now pass.
- **Most of Unit 2's test-side fix is already applied.** `tests/test_bp_registry.py`, `tests/test_cli_typed_error_emission.py`, and `tests/test_keepalive_run.py` already have `encoding="utf-8"` added to their `Path.read_text()` calls and now pass. `mypy.ini` and `pyproject.toml` themselves are **not** touched yet — the `mypy` command still crashes exactly as originally diagnosed. `src/backlink_publisher/cli/publish/report_anchors.py` also already gained a `sys.stdout/stderr.reconfigure(errors="replace")` guard for the same class of non-UTF-8-console problem, one level up the stack from this plan's scope.
- **Unit 4 is already resolved.** `tests/conftest.py` already sets `os.environ["USERPROFILE"]` alongside `HOME` (guarded by `sys.platform == "win32"`), and `test_home_redirect_pre_import.py::test_path_home_resolves_to_sandbox_during_tests` now passes. `HOMEDRIVE`/`HOMEPATH` were not needed — `USERPROFILE` alone was sufficient, contradicting this plan's original Approach for that unit.
- **The two AST-scanner failures this plan had filed under "needs investigation" in Unit 7 are already fixed, and their real root cause is different from what this plan guessed.** It was never an encoding-swallow issue — `tests/test_no_inner_import_shadowing.py` and `tests/test_protected_set_coverage.py` both compared `str(path.relative_to(root))` (which yields backslash-separated strings on Windows, e.g. `webui_app\foo.py`) against `.startswith("webui_app/")`-style forward-slash checks. The fix is `.as_posix()` instead of `str(...)`, already applied to both files plus a third sibling (`tests/test_cli_exit_code_literals.py::test_scanner_recurses_into_cli_subpackages`) that this plan never even identified as failing.
- **A bug this plan never found at all is already fixed**: `src/backlink_publisher/cli/ops/recheck_backlinks.py` and `src/backlink_publisher/keepalive/chain.py` switched a batch-budget deadline check from `time.monotonic()` to `time.perf_counter()` (Windows' `GetTickCount64`-backed `monotonic()` has ~15.6ms resolution, coarse enough to let extra work through a near-zero budget). This fixed `test_cli_recheck_backlinks.py::test_batch_budget_exhaustion_defers_remaining`, which *was* in this plan's original 147-failure list but was never individually triaged here.
- **`src/backlink_publisher/_compat/fcntl.py` already has one fix, but not this plan's fix.** The uncommitted change there widens non-blocking lock-contention detection (`e.errno == errno.EACCES` in addition to `winerror == 33`) — a real, different bug from the `LOCK_UN` position-mismatch this plan diagnoses in Unit 3, which is confirmed still present.
- **Update (2026-07-07, later same day — direct re-run against the current uncommitted tree):** the `LOCK_UN` fix actually landed is the simpler `try/except PermissionError: pass` wrap described under Unit 3's "Resolution actually landed" below, not the seek/restore design this plan originally sketched — see Unit 3 for the reconciliation. Two more real bugs were found and fixed in this same uncommitted pass that this plan never identified:
  - `src/backlink_publisher/events/_store_sqlite.py`'s `_pid_alive()` treated every nonexistent Windows PID as alive (`os.kill(pid, 0)` raises a bare `OSError` with `winerror == 87` on Windows, not `ProcessLookupError` as on POSIX, so it fell into the fail-safe "assume alive" branch). Fixed by treating `winerror == 87` as equivalent to `ProcessLookupError`. This was silently breaking every dead-owner-PID stale-reclaim path (`test_dedup_enforce_gate.py` × 6, `test_idempotency_store.py::test_attempting_with_dead_pid_is_stale`) — not a mode-bit or lock issue, a real Windows PID-liveness gap.
  - `src/backlink_publisher/persistence/safe_write.py`'s `atomic_write_stream` opened its temp file with `os.fdopen(fd, "w", encoding="utf-8")` — no `newline="\n"` — so Windows' universal-newline translation silently turned every `\n` written through it into `\r\n` on disk. Fixed by adding `newline="\n"`. This is a byte-identity contract violation for any JSONL/text file this helper writes (`test_jsonl_atomic_stream.py::test_jsonl_byte_identical_to_legacy_stringio` caught it), independent of Unit 5's mode-bit noise.
  - A full-suite measurement taken directly after all of the above (`pytest tests/ -q --timeout=300`, single-worker, no `-n auto`) read **74 failed, 12884 passed, 58 skipped, 10 errors** — this is the freshest available baseline and supersedes the 147/111/104/99 swing figures above for planning Units 5-7's remaining scope.
- **Final update (2026-07-07, end of this session's pass) — Units 6 and 7 fully closed, real root causes found for both (neither matched this plan's original guesses; see their sections below for the actual fixes: a stale local `core.hooksPath` git config plus a Windows `CreateProcess`/WSL-bash-shadowing bug for Unit 6, five distinct test-fixture/product bugs for Unit 7). The concurrent session continued landing Unit 5 work throughout this pass (3+ incremental commits observed, e.g. `29df6884`/`cd662232`/`3232730d` "fix(windows): route more mode-bit assertions through assert_file_mode") and is not yet finished — do not assume Unit 5 is done just because the failure count keeps dropping. A full-suite re-run taken after all of the above reads **24 failed, 12948 passed, 60 skipped, 0 errors** — every remaining failure is a `0600`/`chmod`/`world_readable`/`loose_perms`-named test, i.e. squarely Unit 5's remaining scope. This is the current authoritative baseline; re-measure before trusting it, per the volatility note in point 1 above.

**This means:** Units 1 and 4 as originally scoped are done; only their regression-guard/verification value remains. Unit 2 is mostly done; only the `mypy.ini`/`pyproject.toml` byte-level fix remains. Unit 7's scanner-test entries were misdiagnosed and are resolved; they're removed below. Units 3, 5, and 6 remain genuinely open. **Before implementing anything in this plan, confirm with whoever/whatever produced this uncommitted work — committing it (or at least not clobbering it) should happen before or alongside this plan's remaining units, to avoid two lines of work re-solving or reverting each other's fixes.**

## Problem Frame

There is no requirements doc or product bug report to plan from — the "bug list" had to be manufactured by actually running the documented commands from `CLAUDE.md`/`AGENTS.md` and reading the failures. Two things make this non-trivial to just "go fix":

1. This repo's CI runs exclusively on `ubuntu-latest` (`.github/workflows/ci.yml`). Everything found here was found on a Windows workstation with a non-UTF-8 default locale, which is a materially different environment than CI. A large share of raw failures are **environment-mismatch noise, not code bugs** — confirmed against an existing institutional-learnings doc (`docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md`) from yesterday, which already classified ~90+ of a previous run's failures as the same noise class and explicitly left the noise-vs-signal split as an open follow-up ("not done in this pass").
2. Underneath the noise sit real, previously-undocumented, fixable bugs — one of which (a broken editable install) is very likely a brand-new regression from today's branch/worktree consolidation activity, not a pre-existing condition.

This plan's job is to separate the two and sequence fixes so each fix's effect on the remaining count is verifiable before moving to the next.

## Requirements Trace

- R1. `python -m mypy src/backlink_publisher --config-file mypy.ini` (the CI-blocking, AGENTS.md-documented command) must run to completion on a Windows workstation with a non-UTF-8 locale, without crashing before analysis starts.
- R2. Any test failure that reflects a genuine, platform-independent code defect must be fixed.
- R3. Any test failure that is pure Windows-vs-Linux-CI environment noise must be clearly labeled as such (via skip/xfail with a reason, not deleted or silently ignored) so the local suite's signal-to-noise ratio improves — this directly executes the open follow-up from `post-fleet-merge-full-suite-measurement-2026-07-06.md`.
- R4. The local dev loop (`pip install -e .`, `pytest tests/`) must work as documented in `CLAUDE.md`/`AGENTS.md` without undocumented environment variables being required to avoid a crash.
- R5. No fix in this plan may touch CI-relevant Linux behavior in a way that could regress the currently-green Linux CI run.

## Scope Boundaries

- Only `backlink-publisher/` is in scope (the canonical repo). The frontend (`frontend/`, `webui_app/spa_dist/`) is explicitly out of scope — it is already clean.
- Fixing the *class* of ~90+ Windows chmod/flock-mode-bit assertion failures does not mean rewriting each test's business logic — it means making the assertions platform-aware, consistent with the product's own documented "permission enforcement is a no-op on Windows" design (`src/backlink_publisher/_util/permissions.py`).
- This plan does not attempt to make the full suite 100% green on Windows if a failure is a genuine platform capability gap unrelated to a code defect (e.g., Windows requiring Developer Mode/admin to create symlinks). Those get an honest `skipif` with a reason, not a fudge.
- mypy's 73 `attr-defined`/`unreachable` findings when run **without** `--platform linux` are diagnosed in this plan (Context & Research) but are not a fix target — they are proven false positives from checking a cross-platform codebase against the wrong target platform locally, and CI already runs mypy correctly (Ubuntu). A one-line local-workflow note is the only deliverable for that finding.

### Deferred to Separate Tasks

- `test_phase0_seal_hook.py`'s exact "which command exits 127" root cause inside `install-pre-push-hook.sh` under Windows Git Bash is scoped as Unit 6 here, but if it turns out to require rewriting the hook script's shell-portability assumptions wholesale, that rewrite is deferred to a follow-up plan — Unit 6 here is bounded to diagnosis + either a minimal portability fix or a documented Windows `skip`.
- The stray empty directory `bp-fix-main-mypy/` at the workspace root (not a real git worktree, no `.git` pointer) is unrelated leftover state, not touched by this plan.

## Context & Research

### Relevant code and patterns

- `src/backlink_publisher/_compat/fcntl.py` — the Windows `fcntl.flock()` shim (`msvcrt.locking()`-based), installed process-wide via `sys.modules["fcntl"] = ...` in `src/backlink_publisher/__init__.py:39-40` when `sys.platform == "win32"`. This is why plain `import fcntl` fails standalone but works everywhere inside the package (parent `__init__.py` always runs first on any submodule import).
- `src/backlink_publisher/_util/permissions.py` — `check_0600()` intentionally no-ops on `win32` (documented in its own module docstring). This is the documented, correct behavior that the noisy tests need to respect, not fight.
- `mypy.ini` (repo root) — `warn_unreachable = True`, `warn_unused_ignores = True`, no `platform =` override. Combined with `--platform` defaulting to the host OS, this is why local Windows mypy runs disagree with CI's Ubuntu runs on every `sys.platform == "win32"` branch in the codebase.
- `tests/conftest.py:257-292` — the test-sandbox home-directory redirect. Sets `os.environ["HOME"]` but never `USERPROFILE`/`HOMEDRIVE`/`HOMEPATH`. `pathlib.Path.home()` on Windows resolves via `os.path.expanduser("~")`, which prefers `USERPROFILE`, not `HOME` — hence the redirect is incomplete on this platform.
- `tests/test_no_raw_home_path_primitives.py` — an existing meta-test banning direct `Path.home()`/`os.environ["HOME"]` use in product code, in favor of a resolver. This is why the blast radius of the conftest gap is a broken *safety net*, not (as far as could be observed) active leakage — `~/.config/backlink-publisher/config.toml` on this machine shows no modification timestamp from this session's test run.
- `pyproject.toml` `[tool.pytest.ini_options]` sets `pythonpath = [".", "src"]`, which is how the 12,812 passing in-process tests resolve `backlink_publisher` even though the venv's own editable install is broken (see Unit 1) — pytest's own sys.path shim masks the broken install for everything except tests that shell out to a **fresh** subprocess.

### Institutional Learnings

- `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md` (yesterday): already identified the ~90+ chmod/mode-bit Windows noise class and the `test_phase0_seal_hook.py` 10-error cluster, explicitly as **not yet fixed**, with an open recommendation to add "a dedicated Windows-chmod-noise learnings doc / xfail-marking pass." Unit 5 and Unit 6 here directly close that follow-up. Their run used `PYTHONUTF8=1` as an ambient workaround for the encoding crash (see Unit 2) — a workaround, not a fix, and not part of any documented command in `CLAUDE.md`/`AGENTS.md`.
- `docs/solutions/logic-errors/git-hookspath-config-redirects-hook-installation-2026-05-18.md`: a different hook installer (`install-post-merge-hook.sh`) in this same repo has a documented history of "fixture tests pass, real environment breaks" failures around git hook installation. Not the same script or failure mode as Unit 6's `install-pre-push-hook.sh` (exit 127 vs. wrong-directory), but establishes this is a recurring fragility area worth checking with the same "run it for real, don't just read the code" discipline.
- `docs/solutions/ui-bugs/notifications-js-orphaned-brace-syntax-error-2026-07-07.md` (today, already fixed at `85a9e1a7`): unrelated to this plan's findings, but confirms this repo currently has no CI step that dry-parses shipped JS — noted only because it's the most recent prior bug-fix in this repo and shares this plan's general "the documented check doesn't actually catch what it should" theme.

### External References

None used — every finding here reproduces from this repo's own commands and config; no external framework/library research was needed.

## Key Technical Decisions

- **Fix the root cause of the `cp950` crash by removing non-ASCII bytes from tool-read config files, not by mandating `PYTHONUTF8=1`.** Rationale: `mypy.ini`/`pyproject.toml` are read by third-party parsers (`mypy`'s `configparser`, `tomllib` in test helpers) whose call sites we don't own; an env var is an easy-to-forget tribal-knowledge workaround (yesterday's session already needed it and it's still not documented anywhere), whereas stripping the em dash is a one-time, zero-risk, permanent fix. For the test/meta files we DO own the call site for, add `encoding="utf-8"` explicitly — the correct fix per-call-site.
- **Fix `_compat/fcntl.py`'s lock/unlock semantics rather than patching call sites.** Rationale: 14+ files call `fcntl.flock()` assuming POSIX whole-file-lock semantics (lock/unlock don't need to agree on file offset). The shim's `msvcrt.locking()`-based implementation is offset-sensitive; the mismatch belongs in the one shim file, not in 14 call sites.
- **Adapt permission-assertion tests via a shared helper, not per-test rewrites.** Rationale: ~40+ tests hardcode `0o600`/`0o700` comparisons against a platform where `os.chmod` cannot represent those bits by design (already documented in `_util/permissions.py`). A single `assert_mode(path, expected_posix_mode)` test helper that is a no-op/soft-check on `win32` and a hard assertion on POSIX keeps the intent (real enforcement is still checked in CI on Linux) while removing local Windows noise, and is one place to fix instead of 40.
- **Do not chase the mypy `attr-defined`/`unreachable` findings as code changes.** Rationale: confirmed false positives — running `mypy --config-file mypy.ini --platform linux` (matching what CI's Ubuntu runner naturally does) is expected to produce a clean run once Unit 2 removes the config-parse crash; the local Windows-without-`--platform linux` invocation is simply the wrong command for this cross-platform codebase, not a code defect.

## Open Questions

### Resolved During Planning

- "Which bugs?" → resolved via user selection: run test/lint/typecheck, treat failures as the list (see Overview).
- "Is the fcntl Windows shim actually broken, or is this just another 0600-style mode-bit mismatch?" → resolved: distinct bug. Traced one failure (`test_dedup_adjudicate.py::test_adjudicate_single_to_succeeded`) to an in-process (non-subprocess) call chain ending in `fcntl.flock(fd, fcntl.LOCK_UN)` raising `PermissionError` from inside `_compat/fcntl.py`, which is a real exception propagating through product code, not a `stat().st_mode` comparison.
- "Is the stale editable install pre-existing or new?" → resolved: new, and already fixed by the time this plan finished review (see "Concurrent Uncommitted Work Discovered"). Yesterday's authoritative measurement doc reports 105 failed/10 errors; this plan's initial raw run (without yesterday's `PYTHONUTF8=1` workaround) showed 147/10, and repeat runs since have shown 111, 104, and 99 failed with 10 errors holding steady — a run-to-run swing of dozens of tests on unchanged code, from `-n auto` xdist nondeterminism plus at least one genuinely flaky cross-process lock test (Unit 3). Given that volatility, treat the original "~28 install + ~12 encoding ≈ the whole 147→105 delta" arithmetic as a directionally-correct hypothesis at the time it was written, not a proven accounting — both clusters were real (confirmed by direct re-run before and after), but the precise number they explain cannot be pinned down from noisy sweep counts alone.

### Deferred to Implementation

- Exact command inside `scripts/install-pre-push-hook.sh` that exits 127 under Windows Git Bash (Unit 6) — needs a manual `bash -x scripts/install-pre-push-hook.sh` run to see which line fails; not diagnosed further here.
- Whether `test_config_managed_root_subsection_roundtrip.py::test_medium_browser_user_data_dir_survives_roundtrip`, `test_phase0_seal_init.py::test_init_manual_happy`, `test_bind_channel_chrome_backend.py::...test_available_when_binary_and_websocket_present`, `test_keepalive_plist.py`, `test_purge_removed_credentials.py`, and `test_config_echo.py::TestWarnIfLooseConfigPermissions::*` are permission-noise, environment-dependent (missing local Chrome binary), or standalone logic bugs — each needs an individual traceback read at implementation time (Unit 7). (`test_credential_service.py::test_save_userpass_livejournal_writes_hpassword` was in this list in an earlier draft; confirmed during review to be a plain mode-bit assertion and moved to Unit 5 — see below.)
- ~~Whether the two AST-scanner meta-test failures... share the `cp950` read crash root cause... or are a genuine scan-root configuration bug~~ — resolved during review (not deferred after all): neither guess was right. Root cause is `str(path.relative_to(root))` producing backslash-separated strings on Windows compared against forward-slash `.startswith(...)` checks; fix is `.as_posix()`. Already applied uncommitted to both files plus a third sibling — see "Concurrent Uncommitted Work Discovered." Removed from Unit 7 below.

## Implementation Units

- [x] **Unit 1: Verify the editable-install fix already in place, and add a guard against silent recurrence** — *done. Underlying fix confirmed holding (`pip show backlink-publisher` reports the correct `backlink-publisher/` location). Regression guard added: `pytest_configure` hook in `tests/conftest.py` + `tests/test_editable_install_sanity.py` (2 tests, both passing), committed at `47d0ed79`.*

**Goal:** The originally-diagnosed defect (editable install pointing at a deleted worktree, `bp-main-reconcile`) is **already fixed** — confirmed by direct re-run, see "Concurrent Uncommitted Work Discovered." This unit is now scoped to (a) verifying that fix holds, and (b) adding the regression guard the plan always intended, so this class of bug fails fast and legibly instead of as 20+ unrelated-looking `ModuleNotFoundError`s next time a worktree gets deleted out from under the shared venv.

**Requirements:** R2, R4

**Dependencies:** None

**Files:**
- Modify: `tests/conftest.py` (add a session-start sanity check)
- Test: `tests/test_editable_install_sanity.py` (new)

**Approach:**
- Confirm current state first: `pip show backlink-publisher` should already report `Editable project location:` under `backlink-publisher/`, not a deleted worktree — if it doesn't, the fix regressed and needs re-applying (`pip install -e ".[dev]"` from `backlink-publisher/`) before anything else in this unit.
- Add a cheap, session-scoped check that resolves `backlink_publisher.__file__` and asserts it lives under a **fixed** reference point, not `cwd` or a shared workspace ancestor: derive the expected root from this specific `conftest.py`'s own location (`Path(__file__).resolve().parent.parent`, i.e. `backlink-publisher/`), not from the process's working directory. This matters because the workspace root's `make test` target runs a worktree sweep (`PYTHONPATH=<other-worktree>/src pytest <other-worktree>/tests/` from the workspace root) — a check anchored to `cwd` or a shared ancestor would either miss the exact regression that happened here (the dead worktree was itself a sibling under the same shared ancestor) or false-fail during the documented sweep flow.
- On mismatch, fail with an actionable message ("editable install points outside this repo (<found path>) — run `pip install -e .` from backlink-publisher/") instead of letting downstream subprocess tests fail with a bare `ModuleNotFoundError`.

**Test scenarios:**
- Happy path: current state — `backlink_publisher.__file__` resolves under `backlink-publisher/src/`, matching the path derived from `conftest.py`'s own location.
- Regression guard: the new sanity check fails with a clear, actionable message (not a bare `ModuleNotFoundError`) if `.venv`'s editable-install record is deliberately pointed at a nonexistent path in a test fixture.
- Edge case: the check does not false-fail when exercised via the workspace-root `make test` worktree-sweep flow (simulate or reason through this explicitly, since that flow's `cwd`/`PYTHONPATH` differ from a plain `pytest tests/` invocation inside `backlink-publisher/`).
- Regression (already resolved, confirm doesn't regress): `test_optimization_rules.py::TestOptimizeWeightsCLI::test_help`, `test_cli_weights.py::TestWeightsCLIDispatcher::test_help_exit0`, `test_collect_signals.py::TestCollectSignalsCLI::test_help`, `test_cli_show_optimization_state.py::*`, `test_cli_timing_regression.py`, `test_footprint_engine.py::test_top_helper_stable_across_pythonhashseed_values`, `test_cli_recheck_backlinks.py::test_batch_budget_exhaustion_defers_remaining`, `test_cli_exit_code_literals.py::test_scanner_recurses_into_cli_subpackages` all currently pass — confirm they stay passing.

**Verification:**
- `pip show backlink-publisher` reports `Editable project location:` under the current `backlink-publisher/` path, not a deleted worktree.
- The new sanity check exists and demonstrably fails loudly (in its own test) when the install is deliberately broken, rather than only when observed to pass.

---

- [x] **Unit 2: Fix the `cp950` locale crash in `mypy.ini`/`pyproject.toml` (restores the documented `mypy` command)** — *done. Em dashes/box-drawing/section-sign bytes stripped from both files (pure ASCII now); `mypy --config-file mypy.ini` runs to completion (72 platform-mismatch findings, expected, not a fix target); `mypy --config-file mypy.ini --platform linux` reports zero issues. One additional latent-risk call site fixed (`tests/test_webui_api_v1.py`'s read of `openapi/backlink-api.yaml`). Committed at `47d0ed79`.*

**Goal:** Make `python -m mypy src/backlink_publisher --config-file mypy.ini` run to completion on a Windows workstation whose default locale is not UTF-8, without requiring an undocumented `PYTHONUTF8=1`. **The pytest-side half of this unit is already done** — see below.

**Requirements:** R1, R4

**Dependencies:** None

**Files:**
- Modify: `mypy.ini` (remove/replace the em dash in the `webui_store` override comment)
- Modify: `pyproject.toml` (remove/replace the non-ASCII byte at position 2272 that breaks `tomllib.loads(_PYPROJECT.read_text())`)
- Already done, uncommitted (verify only, do not re-do): `tests/test_bp_registry.py`, `tests/test_cli_typed_error_emission.py`, `tests/test_keepalive_run.py` already have explicit `encoding="utf-8"` added to their `Path.read_text()` calls and pass. `src/backlink_publisher/cli/publish/report_anchors.py` already has a `sys.stdout/stderr.reconfigure(errors="replace")` guard for the same underlying non-UTF-8-console class of problem (console *output*, not file *input* — a different call site than this unit's remaining scope, mentioned here only so it isn't mistaken for unfinished work).

**Approach:**
- Locate and ASCII-ify the two remaining offending bytes: confirmed at `pyproject.toml` byte offset 2272 and `mypy.ini`'s `webui_store` override comment (`\xe2\x80\x94`, U+2014 em dash). Replace with `--` or plain `-`. This is the only code change actually left in this unit.
- Do a repo-wide grep sweep (`rg "\.read_text\(\)" tests/ src/`) for the same `Path.read_text()`-without-`encoding=` anti-pattern in files that happen not to contain non-ASCII bytes yet — those are latent, not yet triggered by any current failure; add `encoding="utf-8"` proactively rather than waiting for the next em dash to land in a comment. Skip files already fixed (listed above).

**Execution note:** Verify by actually re-running `mypy` on this machine (not just reading the diff) — this exact class of bug (works on the author's machine, breaks on a different locale) is why `git-hookspath-config-redirects-hook-installation-2026-05-18.md` and this plan both stress "dogfood, don't just read the code."

**Test scenarios:**
- Happy path: `mypy src/backlink_publisher --config-file mypy.ini` produces analysis output (not a traceback) on this machine.
- Happy path: `mypy src/backlink_publisher --config-file mypy.ini --platform linux` reports zero errors (confirms the remaining `attr-defined`/`unreachable` findings were purely a platform-target mismatch, per Key Technical Decisions).
- Edge case: a `pyproject.toml`/`mypy.ini` round-trip (`tomllib.loads` / mypy's own config parse) still succeeds after the byte replacement — i.e., the ASCII substitution didn't change parsed semantics, only the literal bytes.
- Regression (already resolved, confirm doesn't regress): `pytest tests/test_bp_registry.py tests/test_cli_typed_error_emission.py tests/test_keepalive_run.py -q` stays green.

**Verification:**
- The `mypy` command from `AGENTS.md`'s CI job description runs to completion locally.

---

- [x] **Unit 3: Fix `_compat/fcntl.py`'s Windows lock/unlock semantics** — *already resolved during execution, by the same concurrent uncommitted work described above.*

**Resolution actually landed:** rather than this plan's proposed position-tracking-and-seek approach, the concurrent work wraps the `LOCK_UN` call in `try: msvcrt.locking(fd, LK_UNLCK, 1) except PermissionError: pass` — simpler, with no fd-keyed state to leak or go stale on fd reuse, and no thread-safety caveat to reason about. Verified directly: `pytest tests/test_dedup_adjudicate.py tests/test_dedup_operator_verbs.py tests/test_idempotency_store.py tests/test_dedup_enforce_gate.py tests/test_reliability_circuit.py tests/test_reliability_circuit_crossproc.py -q -n auto` (repeated, including under parallel load where the flaky manifestation was previously observed) shows zero `PermissionError` failures — the only 2 remaining failures in that run are `test_idempotency_store.py::test_store_files_are_0600` and `test_reliability_circuit.py::test_state_file_created_with_0600_perms`, both plain 0o600 mode-bit assertions that belong to Unit 5, not this unit. This plan's own technical-design sketch below is retained only as a record of the alternative approach considered, not as work still to do.

**Goal (historical — already satisfied):** Make the Windows `flock()` shim's `LOCK_UN` path stop raising `PermissionError`, which is the highest-value real product-code bug found in this sweep — it cascades into the largest cluster of dedup/idempotency/secrets/reliability-circuit test failures.

**Requirements:** R2, R5

**Dependencies:** None (independent of Units 1-2, but re-running the suite to measure its effect is most useful after Unit 1 removes the unrelated subprocess noise)

**Files:**
- Modify: `src/backlink_publisher/_compat/fcntl.py` (note: this file already has one *different*, unrelated, uncommitted fix in place — a non-blocking lock-contention `EACCES` check — see "Concurrent Uncommitted Work Discovered." Do not revert it; add this unit's fix alongside it.)
- Test: `tests/test_dedup_adjudicate.py`, `tests/test_dedup_operator_verbs.py`, `tests/test_idempotency_store.py`, `tests/test_reliability_circuit_crossproc.py` (existing — serve as regression checks)

**Approach:**
- Root cause (confirmed via traceback on `test_dedup_adjudicate.py::test_adjudicate_single_to_succeeded`): `src/backlink_publisher/idempotency/audit_log.py:86` calls `fcntl.flock(fd, fcntl.LOCK_UN)` and the shim raises `PermissionError`. `msvcrt.locking()` locks/unlocks a byte range starting at the file's *current position*; POSIX `flock()` is a whole-file advisory lock with no such position-sensitivity. A caller that writes to the file (moving its position) between the `LOCK_EX` and `LOCK_UN` calls causes the unlock's implicit byte range to no longer match the lock's, and `msvcrt.locking(..., LK_UNLCK, ...)` fails.
- **Scope correction (this plan originally overclaimed this):** this does *not* affect all 14 files that call `fcntl.flock()` — most lock a *sibling* lock file that the caller never itself writes to (`circuit.py`, `locked_store.py`, `safe_write.py`, `comment_outreach/store.py`, `pr_outreach/store.py`), or are pure non-blocking "don't run twice" guards that never write to the locked handle at all (`probe_index.py`, `probe_citations.py`, `probe_ranking.py`, `recheck_backlinks.py`, `keepalive/chain.py`) — so the position never moves and the current shim already works for them. Only `audit_log.py` (confirmed) and `medium_auth.py` (writes directly to the same fd via `os.write(self._fd, ...)`) structurally match the failure mode. Size the expected impact accordingly — this is a real, worth-fixing bug, just a narrower one than first described.
- Fix inside the shim only: track the locked `(fd, position, length)` internally (e.g., a module-level dict keyed by `fd`) at `LOCK_EX`/`LOCK_EX|LOCK_NB` time, and on `LOCK_UN` seek back to the recorded position before calling `msvcrt.locking(fd, LK_UNLCK, length)`, then restore the caller's current position afterward. This makes the shim's lock/unlock symmetric regardless of what the caller does with the file handle in between, matching POSIX `flock()`'s actual contract, without touching either of the two call sites.
- The dict has no cleanup path for a caller that closes the fd without calling `LOCK_UN` (e.g. `safe_write.py`'s `atomic_write_stream`, which only does `os.close(lock_fd)` in its `finally` block — never `LOCK_UN`). Left as-is, `_locked_regions` grows unboundedly over a long-lived process (the WebUI Flask server) and a later fd-number reuse could inherit a stale recorded position. Decide explicitly whether to key on something more durable than the raw OS fd, or accept and document this as a known, bounded-severity gap — do not leave it silently unaddressed.
- The seek-lock-seek sequence briefly mutates the file's current read/write position, which is only safe if a given `fd` is not accessed concurrently from multiple threads within the same process (only cross-*process* contention is protected by the lock itself). Confirm none of the two affected call sites' callers share an `fd` across threads before relying on this; if any do, the dict-and-seek sequence needs its own lock around it, not just the OS-level file lock.

**Technical design:** *(directional, not implementation-ready)*
```
flock(fd, LOCK_EX|LOCK_NB):
    pos = tell(fd)
    msvcrt.locking(fd, LK_NBLCK, 1)
    _locked_regions[fd] = pos      # remember where the lock byte lives

flock(fd, LOCK_UN):
    saved = tell(fd)
    seek(fd, _locked_regions.pop(fd, 0))
    msvcrt.locking(fd, LK_UNLCK, 1)
    seek(fd, saved)                 # don't disturb caller's position
```

**Test scenarios:**
- Happy path: acquire `LOCK_EX|LOCK_NB`, write to the file (moving the position), then `LOCK_UN` — no exception.
- Happy path (blocking): acquire `LOCK_EX` (blocking variant) with no writes in between, then `LOCK_UN` — no exception (regression guard for the already-working path).
- Edge case: `LOCK_UN` called on an `fd` that was never locked by this shim — must silently return, matching real POSIX `flock(fd, LOCK_UN)`'s documented no-op-on-unlock-of-unlocked-fd behavior. (This plan originally said this case should raise "to match POSIX behavior" — that is backwards; POSIX does not raise here. Do not implement a raise.)
- Concurrency/integration: `test_reliability_circuit_crossproc.py::test_crossproc_flock_serializes_rmw` — two real OS processes contending for the same lock file must still serialize correctly after the fix (this is the scenario a single-process mock cannot prove).
- Regression, run under the full parallel suite (not only in isolation — `test_dedup_operator_verbs.py::test_forget_absent_key_still_records_audit_entry` was observed failing with this exact `PermissionError` under a full `-n auto` run but passes when run alone, consistent with a genuinely intermittent, concurrency-timing-dependent manifestation): `test_dedup_adjudicate.py`, `test_dedup_operator_verbs.py`, `test_idempotency_store.py`. Some tests in these files may still fail separately on the unrelated 0o600-mode-bit issue (Unit 5's job, not this unit's) — don't conflate the two failure shapes.

**Verification (confirmed):**
- `test_dedup_adjudicate.py::test_adjudicate_single_to_succeeded` and `test_dedup_operator_verbs.py::test_forget_absent_key_still_records_audit_entry` both pass under a full-suite `-n auto` run, not just in isolation. ✅
- No new failures introduced in `test_reliability_circuit_crossproc.py`. ✅
- The already-uncommitted `EACCES` lock-contention fix in the same file is still present and its own tests still pass. ✅
- Re-confirmed 2026-07-07 (later, single-worker full run): zero `PermissionError`-from-`flock` failures anywhere in the 74-failure baseline below — every remaining `test_dedup_*`/`test_idempotency_*`/`test_reliability_circuit*` failure is a plain mode-bit assertion (Unit 5's scope), not a lock exception. ✅

---

- [x] **Unit 4: Verify the Windows test-sandbox gap for `Path.home()` is closed, and cite the real leakage-detection mechanism** — *`pytest tests/test_home_redirect_pre_import.py -q` confirmed fully green (8 passed) on 2026-07-07. `_credential_tripwire` history review (this unit's other deliverable) still outstanding.*

**Goal:** This unit's original defect — the test-sandbox home-directory redirect (`tests/conftest.py`) setting `$HOME` but not `USERPROFILE`, so `Path.home()` on Windows escaped the sandbox — is **already fixed, uncommitted** (see "Concurrent Uncommitted Work Discovered"): `tests/conftest.py` now sets `os.environ["USERPROFILE"]` alongside `HOME`, guarded by `sys.platform == "win32"`, and `test_home_redirect_pre_import.py::test_path_home_resolves_to_sandbox_during_tests` passes. `HOMEDRIVE`/`HOMEPATH` were not needed — `USERPROFILE` alone was sufficient (this plan's original Approach proposed setting all three; that was broader than necessary). This unit is now verification-only, plus correctly citing the repo's real leakage-detection mechanism instead of inventing a weaker one.

**Requirements:** R2, R5

**Dependencies:** None

**Files:**
- Verify only: `tests/conftest.py` (already modified, uncommitted)
- Test: `tests/test_home_redirect_pre_import.py` (existing, already passing)

**Approach:**
- Confirm `pytest tests/test_home_redirect_pre_import.py -q` is fully green (all of `test_home_is_redirected_to_sandbox`, `test_config_dir_resolves_to_sandbox`, `test_cache_dir_resolves_to_sandbox`, `test_real_roots_differ_from_sandbox_roots`, `test_path_home_resolves_to_sandbox_during_tests`).
- **Correction to this plan's original verification method:** do not rely on a single file's mtime as evidence that no real credential/config leakage occurred during any Windows test run before this fix landed — that check is write-only (misses read-based exposure), doesn't cover the actual named secrets file (`~/.config/backlink-publisher/llm-settings.json`, CLAUDE.md's designated 0600 API-key store), and only proves "nothing changed this one time I checked." This repo already has a stronger, purpose-built mechanism for exactly this: `tests/conftest.py`'s `_credential_tripwire` (autouse, session-scoped) content-hashes every file matching `PROTECTED_GLOBS` (`llm-settings.json`, `*-token.json`, `*-credentials.json`, `events.db`, etc.) at session start and end, and fails loudly if any changed while no operator process was live. Use its pass/fail history across recent sessions as the real evidence, not a new ad hoc check.
- No production code changes — this repo already enforces (via `test_no_raw_home_path_primitives.py`) that product code never calls `Path.home()` directly, so this unit was always about the safety net's trustworthiness, not an active leak.

**Test scenarios:**
- Regression (already resolved, confirm doesn't regress): `pytest tests/test_home_redirect_pre_import.py -q` stays fully green.
- Verification-only (no new test needed): review `_credential_tripwire`'s recent pass/fail history (not a one-off mtime spot-check) as the leakage-forensics evidence for this unit.

**Verification:**
- `pytest tests/test_home_redirect_pre_import.py -q` is fully green.
- `_credential_tripwire` has not fired (no unexplained credential-file content change) across the sessions spanning this plan's own investigation.

---

- [ ] **Unit 5: Adapt Windows-vs-POSIX permission-mode assertions (closes the open follow-up from `post-fleet-merge-full-suite-measurement-2026-07-06.md`)** — *IN PROGRESS by a concurrent session as of 2026-07-07: `tests/_mode_assertions.py` (the shared `assert_file_mode()` helper) and `tests/test_mode_assertions.py` (its own unit tests) already exist, uncommitted, and match this unit's Approach almost exactly — location is `tests/_mode_assertions.py` (flat import, matching this repo's "tests/ is not a package" convention), not the `tests/_util/mode_assertions.py` path this plan originally guessed. Whoever picks this unit up next should read those two files first and extend/apply the existing helper across the file list below, not re-author a second helper.*

**Goal:** Stop the ~40+ tests that hardcode `stat.S_IMODE(...) == 0o600` (or `0o700`/`0o644`) from failing on Windows, where `os.chmod` cannot represent POSIX permission bits — consistent with `_util/permissions.py`'s own documented no-op-on-`win32` design — while keeping full enforcement checked on POSIX/CI.

**Requirements:** R2, R3

**Dependencies:** Unit 3 (some files, e.g. `test_reliability_circuit.py`, `test_idempotency_store.py`, mix a lock-related failure and a mode-bit failure across their two-plus test functions; fixing Unit 3 first means re-running the suite here gives a clean read of exactly which failures are pure mode-bit noise).

**Files:**
- Create: `tests/_util/mode_assertions.py` (shared helper — repo-relative test-support module; adjust to match this repo's existing test-helper location convention, e.g. `tests/conftest.py`-adjacent, at implementation time)
- Modify — confirmed exhaustive list from the 2026-07-07 74-failure single-worker baseline (Unit 3 already landed, so every one of these is now purely a mode-bit assertion, not a residual lock exception): `tests/test_canary_store.py` (2), `tests/test_cli_health_check.py` (3 — `TestDbStats::test_corrupt_db` is a `PermissionError` on an already-open file, not a mode-bit assert; verify at implementation time whether it belongs here or in Unit 7), `tests/test_comment_outreach_status_store.py` (2), `tests/test_config_echo.py::TestCanonicalise::test_path_to_string` + `TestWarnIfLooseConfigPermissions` (3) (4 total — note `test_path_to_string` looks like a naming outlier; confirm it's mode-bit-shaped before routing through the helper), `tests/test_config_geo_provider.py` (1), `tests/test_config_llm_sidecar.py` (2), `tests/test_credential_service.py` (3, including `test_save_userpass_livejournal_writes_hpassword`), `tests/test_dedup_connection.py` (1), `tests/test_dedup_digest.py::TestLoadOrCreateSecret::test_load_or_create_secret_file_permissions` (1), `tests/test_fail_closed_resolver.py` (2), `tests/test_frw_login.py` (2), `tests/test_gitlabpages_adapter.py`, `tests/test_hackmd_adapter.py`, `tests/test_mataroa_adapter.py` (1 each, same `TestLoadToken::test_rejects_world_readable_token_file` pattern), `tests/test_idempotency_store.py::test_store_files_are_0600` (1), `tests/test_image_gen_token_rotation.py` (4), `tests/test_io_utils.py` (3), `tests/test_jsonl_atomic_stream.py` (2), `tests/test_provider.py` (2, `TestVelogCookies`/`TestSubstackCookies::test_wrong_chmod`), `tests/test_registry_credential_saver.py` (2), `tests/test_reliability_circuit.py::test_state_file_created_with_0600_perms` (1), `tests/test_save_config_section_taxonomy_canary.py` (5), `tests/test_secrets.py` (4), `tests/test_session_package.py::TestProviderLoadVelog::test_load_bad_permissions` (1), `tests/test_settings_service.py` (1), `tests/test_webui_core_routes.py::TestSecretLeakRegression::test_llm_settings_loose_perms_fixed_on_load` (1), `tests/test_webui_llm_test_persist.py` (2), `tests/test_webui_store_channel_status_sqlite.py`, `tests/test_webui_store_drafts_sqlite.py`, `tests/test_webui_store_profiles_sqlite.py`, `tests/test_webui_store_queue_sqlite.py`, `tests/test_webui_store_schedule_sqlite.py` (1 each, `TestStartupMigration::test_migrated_file_chmod_600`), `tests/test_webui_store_sqlite_base.py` (2). Total: ~58 test functions across 27 files — this supersedes the "representative, ~40+" estimate the plan originally carried.
- Test: the files above are themselves the tests being adapted; no separate new test file beyond the shared helper's own small unit test.

**Approach:**
- Add one small helper, e.g. `assert_file_mode(path, expected_octal)`, that on POSIX platforms asserts the exact mode (today's behavior, preserving real CI coverage) and on `win32` asserts the platform-appropriate contract instead. Prefer "the file exists and the code path that would `chmod` it did not raise" over a bare `pytest.skip(...)` wherever the surrounding test also exercises real file-write logic (e.g. `test_credential_service.py`, `test_secrets.py`) — a bare skip throws away the only signal a local Windows run could still usefully provide about credential-writing code paths. Reserve `pytest.skip("POSIX permission bits are a no-op on Windows by design — see _util/permissions.py")` for tests whose *entire* content is the mode-bit comparison with nothing else to check.
- Sweep the confirmed-representative file list above for their mode-bit assertions and route them through the helper. Do not touch assertions in the same files that are unrelated to file mode (e.g., a file's *content* correctness) — only the `st_mode`/`chmod`-equality checks. Include `tests/test_credential_service.py::test_save_userpass_livejournal_writes_hpassword` explicitly — its name doesn't look like the pattern, but its actual assertion (`os.stat(path).st_mode & 0o777 == 0o600`) confirms it's the same mode-bit class as its two siblings in the same file; it does not need special-case investigation (an earlier draft of this plan incorrectly flagged it for that in Unit 7).
- This executes, rather than re-discovers, the explicit open recommendation already on file in `post-fleet-merge-full-suite-measurement-2026-07-06.md` ("a dedicated Windows-chmod-noise learnings doc / xfail-marking pass").

**Test scenarios:**
- Happy path (POSIX, via CI): `assert_file_mode` still fails loudly if a file is genuinely `0o644` instead of the required `0o600` — i.e., confirm the helper does not weaken real enforcement on Linux.
- Happy path (Windows, local): the same call is a clean skip/soft-pass with a clear reason string, not a false green and not a crash.
- Regression: full re-run of the representative file list on this Windows machine is green (modulo any files that turn out, at implementation time, to have a second unrelated failure — those are out of this unit's scope).

**Verification:**
- Re-running the full suite locally shows the mode-bit-assertion class of failures gone from the failure list, and the total failure count has dropped from its Unit-1/2/3/4-adjusted baseline by roughly the size of this cluster (confirmed exact count at implementation time, not pre-committed here).
- A short addendum to `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md` (or a new dated doc cross-linking it) records that the open follow-up is now done.

---

- [x] **Unit 6: Diagnose and fix (or correctly skip) the `test_phase0_seal_hook.py` cluster** — *done, 2026-07-07. Root cause was neither of this unit's two guesses (a missing GNU toolchain command, or a script-portability gap). Two distinct, unrelated bugs were found and fixed:*
  1. *This checkout's local (uncommitted, not version-controlled) `.git/config` had a stale `core.hooksPath` absolute path baked in from a different machine (`/Users/dex/YDEX/...`), left over from however this working tree was provisioned. `git rev-parse --git-path hooks` was resolving to that dead path, so **hook installation was broken on this checkout for any script, not just under test** — fixed via `git config --unset core.hooksPath` (a local environment fix, not a repo file change; nothing to commit).*
  2. *`tests/test_phase0_seal_hook.py`'s own `_install_hook()`/`test_installer_idempotent_when_rerun` invoked `subprocess.run(["bash", str(target)], ...)` with a bare `"bash"` argv[0]. On this Windows machine, `CreateProcess`'s implicit executable search checks `C:\Windows\System32\` **before** `PATH`, and that directory contains a WSL launcher stub also named `bash.exe` — so the bare string resolved to WSL's bash, not Git for Windows' real bash, and WSL's bash cannot see Windows-style paths at all (reports "No such file or directory", i.e. exit 127, for a path that genuinely exists). Fixed by resolving `shutil.which("bash")` once at module scope and using the full path plus `.as_posix()` for the script argument at both call sites.*
  3. *One further failure after both of the above: `TestInstaller::test_installer_creates_executable_hook` asserted the POSIX execute bit (`mode & 0o100`), which Windows cannot set or represent (same class as Unit 5) — added a `sys.platform == "win32"` early-return, since existence is already checked above it.*
- *Verification: `pytest tests/test_phase0_seal_hook.py -q` → 10 passed, 0 errors.*

**Goal (historical):** Resolve the 10 collection/execution errors in `test_phase0_seal_hook.py`, all currently failing with `subprocess.CalledProcessError: ... returned non-zero exit status 127` when invoking `bash .../scripts/install-pre-push-hook.sh` from a pytest-created temp repo on this Windows machine.

**Requirements:** R2, R3

**Dependencies:** None

**Files:**
- Investigate: `scripts/install-pre-push-hook.sh`
- Modify (one of, depending on diagnosis): `scripts/install-pre-push-hook.sh` (if a genuinely portable fix exists) — or — `tests/test_phase0_seal_hook.py` (add a `skipif` with a clear reason if the script legitimately requires a POSIX toolchain component absent from Windows Git Bash's minimal `usr/bin`)

**Approach:**
- Exit code 127 is "command not found" — run `bash -x scripts/install-pre-push-hook.sh` manually in this repo's Git Bash to see exactly which invoked command is missing (candidates to check first, since they're common gaps in Git for Windows' minimal toolset: GNU-only `stat`/`realpath`/`sha256sum` flags, `flock`, or a `python3` vs `python`/`py` invocation).
- This repo has prior history of hook-installer scripts breaking only in real environments, not fixture tests (`docs/solutions/logic-errors/git-hookspath-config-redirects-hook-installation-2026-05-18.md`, a different script but the same class of gap) — treat that doc's closing advice ("run it for real, don't just read the code") as the working method here too.
- If the missing command is Windows-Git-Bash-unavailable by nature (not fixable without adding a dependency), the correct fix per this plan's Key Technical Decisions is an honest `skipif(sys.platform == "win32", reason=...)`, not a workaround that masks it on Linux too.

**Test scenarios:**
- Happy path: whichever of the 10 `test_phase0_seal_hook.py` tests are fixable (not skipped) pass after the script fix.
- Regression: any test that gets a `skipif` instead reports `skipped`, not `error`, in the local run — and the same test is unaffected on Linux CI (verify by reading, since CI itself isn't run from this plan).

**Verification:**
- `pytest tests/test_phase0_seal_hook.py -q` on this machine reports 0 errors (each of the 10 is either passing or an explicit, reasoned skip).

---

- [x] **Unit 7: Triage the remaining standalone failures** — *done, 2026-07-07. `test_config_echo.py::TestWarnIfLooseConfigPermissions` (3 tests) turned out to be genuinely Unit 5's mode-bit-noise scope, not a standalone bug, and was fixed there (`skipif` on win32) rather than here. All 6 other investigate-list items were read, classified, and fixed this pass:*
- *`test_purge_removed_credentials.py::test_symlink_is_refused_not_followed` → wrapped `link.symlink_to(outside)` in `try/except OSError: pytest.skip(...)` (classification b, privilege gap).*
- *`test_config_managed_root_subsection_roundtrip.py::test_medium_browser_user_data_dir_survives_roundtrip` → rebuilt the fixture path via `tempfile.gettempdir()` instead of a hardcoded `/tmp/...` literal, and fixed the raw-TOML-text assertion to compare against the TOML-escaped backslash form (classification a, test-fixture bug).*
- *`test_bind_channel_chrome_backend.py::TestRealChromeBrowserRunnerAvailable::test_available_when_binary_and_websocket_present` → replaced the hardcoded `/bin/ls` sentinel with `sys.executable` (classification a/b, test-fixture bug).*
- *`test_keepalive_plist.py` (2 tests) → `test_..._is_absolute` now compares via `PurePosixPath` (the plist's `WorkingDirectory` is always macOS/POSIX content regardless of host OS); `test_..._exists` gained a `sys.platform != "darwin"` skip alongside its existing CI skip (classification b).*
- *`test_phase0_seal_init.py::test_init_manual_happy` → real product bug, not investigated by this plan before: `_build_manual_verdict_ref()` in `src/backlink_publisher/cli/_seal_init.py` serialized the evidence path via `str(rel)` (native separators) instead of `rel.as_posix()`, so the git-notes payload carried backslashes on Windows and failed a portability comparison against git's own (always-forward-slash) `ls-files` output. Fixed at the one call site (classification a, product bug).*
- *`test_cli_health_check.py::TestDbStats::test_corrupt_db` → real product bug: `_db_stats()` in `src/backlink_publisher/cli/ops/health_check.py` opened a `sqlite3.connect()` handle and only called `.close()` on the success path — when the "database" was actually corrupt/unreadable, the exception handler returned without closing the connection, leaking an open file handle. Harmless on POSIX (open fds don't block `unlink`); on Windows it made the test's own `tempfile.TemporaryDirectory` cleanup fail with `PermissionError` (the file was still held open). Fixed with `try/finally: conn.close()` (classification a, product bug — a real resource leak, not test noise).*
- *Verification: all 6 files pass individually; full-suite re-run confirms no regressions (see updated Overview baseline).*

**Goal (historical):** Individually resolve or correctly classify the small tail of failures that don't fit Units 1-6's clusters.

**Requirements:** R2, R3

**Dependencies:** Units 1-6 (re-run the suite after those land; some of these may turn out to already be fixed as a side effect, e.g. if they were actually mis-clustered).

**Files:**
- Investigate (traceback not yet read in this planning pass): `tests/test_phase0_seal_init.py::test_init_manual_happy`, `tests/test_config_managed_root_subsection_roundtrip.py::test_medium_browser_user_data_dir_survives_roundtrip`, `tests/test_bind_channel_chrome_backend.py::TestRealChromeBrowserRunnerAvailable::test_available_when_binary_and_websocket_present`, `tests/test_keepalive_plist.py` (2 tests), `tests/test_purge_removed_credentials.py::test_symlink_is_refused_not_followed`, `tests/test_config_echo.py::TestWarnIfLooseConfigPermissions` (3 tests)

**Removed from this list during review** (each independently re-run and confirmed resolved — see "Concurrent Uncommitted Work Discovered" and Unit 5): `test_no_inner_import_shadowing.py::test_scanner_recurses_into_webui_and_adapters` and `test_protected_set_coverage.py::test_scanner_recurses_into_adapters_and_webui` (real root cause was a Windows path-separator bug, `.as_posix()` fix already applied — not an encoding issue as this plan first guessed); `test_cli_timing_regression.py` (resolved by Unit 1's already-fixed editable install); `test_credential_service.py::test_save_userpass_livejournal_writes_hpassword` (confirmed by direct re-run to be a plain 0o600 mode-bit assertion — moved into Unit 5's list, not a standalone logic bug as this plan first guessed).

**Traceback read during this review pass (2026-07-07, later same day) — classifications below, ready to execute without further investigation:**
- `test_purge_removed_credentials.py::test_symlink_is_refused_not_followed` — classification (b): `link.symlink_to(outside)` itself raises `OSError: [WinError 1314]` (a required privilege is not held by the client) before the code under test ever runs. Creating a symlink on Windows requires admin or Developer Mode; this is not a product bug. Fix: `skipif`, or catch the `OSError` in the fixture and `pytest.skip(...)` with a reason, whichever this repo's convention prefers at implementation time.
- `test_config_managed_root_subsection_roundtrip.py::test_medium_browser_user_data_dir_survives_roundtrip` — classification (a), but a test-fixture bug, not a product bug: the fixture hardcodes a POSIX absolute path literal (`/tmp/bp-medium-profile-<uuid>`) as the config value; on Windows, once the loader round-trips it through `pathlib.Path`, `str(Path("/tmp/..."))` renders with backslashes (`\tmp\bp-medium-profile-...`), which then fails a literal string-equality assertion against the original forward-slash literal. This is not a real user-data-dir bug (no real Windows user would configure a POSIX-style `/tmp/...` path) — the fix is to make the fixture path platform-appropriate (e.g. build it via `tempfile.gettempdir()` or an OS-conditional literal) rather than touching the loader.
- `test_bind_channel_chrome_backend.py::TestRealChromeBrowserRunnerAvailable::test_available_when_binary_and_websocket_present` — classification (b)/(a) mixed: `monkeypatch.setenv("BACKLINK_PUBLISHER_REAL_CHROME_BIN", "/bin/ls")` as a stand-in "binary that exists" sentinel is itself a POSIX-only path baked into the test; `/bin/ls` does not exist on Windows so `RealChromeBrowserRunner.available()` correctly returns `False`, and the test's own premise fails, not the code under test. Fix: use a cross-platform "definitely exists" sentinel (e.g. `sys.executable`) instead of hardcoding `/bin/ls`.
- `test_keepalive_plist.py` (2 tests) — classification (b): the module under test builds a macOS `launchd` `.plist` (absolute-path, POSIX-style working-directory assumptions baked into the plist format itself). This is inherently macOS-only; `skipif(sys.platform != "darwin", ...)` is the correct and only fix.
- `test_phase0_seal_init.py::test_init_manual_happy` — not yet re-read this pass; still genuinely open, keep as originally scoped.
- `test_cli_health_check.py::TestDbStats::test_corrupt_db` — traceback shows `PermissionError` distinct from the Unit 5 mode-bit pattern (looks like a file still open/locked when the test tries to corrupt/reopen it on Windows, where an open file cannot be reopened exclusively the way POSIX allows) — needs its own read at implementation time; do not fold into Unit 5's mechanical sweep without checking first.

**Approach:**
- For each remaining test not already classified above, read the actual traceback and classify into one of: (a) genuine logic bug → fix, (b) Windows environment/privilege gap → honest `skipif` with reason, (c) already resolved by an earlier unit's fix.
- Given this plan's own track record in this review pass (several of its "needs investigation" guesses turned out to be either already-fixed or misdiagnosed once actually re-run), do not trust a name-pattern or file-clustering guess for any remaining unclassified test — read the real traceback before classifying.

**Test scenarios:**
- Per-test, matching whichever classification (a)/(b)/(c) above applies — enumerated at implementation time once the actual failure reason for each is known.

**Verification:**
- Every test in the investigate list above is either passing, or skipped with a specific, reviewable reason string — none remain in an unexplained failing state.

## System-Wide Impact

- **Interaction graph:** Unit 3's fix lives entirely in the shared shim (`_compat/fcntl.py`), so it is visible to all 14 files that call `fcntl.flock()` indirectly, but changes behavior only for the two confirmed same-fd-write call sites (`audit_log.py`, `medium_auth.py`) — the other 12 lock a sibling file or never write to the locked handle, so their behavior is unaffected either way. No call sites are modified. Units 2, 4, and 5 are test-only changes plus two config-file byte edits; no production code paths besides `_compat/fcntl.py` (Unit 3) are touched.
- **Error propagation:** Unit 3's fix changes a `PermissionError` that currently propagates out of `flock()` on unlock into no exception at all in the fixed path — verify no calling code (`audit_log.append_entry` and `medium_auth.py`'s `_FileLock.__exit__`, the two confirmed affected call sites) has a `try/except` specifically expecting and handling that `PermissionError` as a signal, so the fix doesn't silently change intended error-handling behavior.
- **API surface parity:** None of these fixes touch any CLI flag, HTTP route, or adapter registry surface — purely internal correctness/dev-loop fixes.
- **Integration coverage:** Unit 3's cross-process tests (`test_reliability_circuit_crossproc.py`) are the one place in this plan where a single-process/mocked test cannot prove correctness — real two-process contention is required and already exists as a test; no new integration test needs to be authored.
- **Unchanged invariants:** This plan does not change the adapter registry, the CLI argparse layer, `schema.py`, the error taxonomy (`_util.errors`), or any webui route/store. It does not change what CI actually enforces on Linux (Units 2, 4, 5 add platform-awareness that is a no-op on POSIX; Unit 3 fixes a bug that was latent on Linux too in principle, since real `fcntl.flock()` on Linux has no offset-sensitivity issue — the shim-only nature of the bug means Linux was never affected).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Units 3-5 touch credential/secrets-adjacent surfaces (the fcntl-guarded audit/idempotency/credential stores, the home-directory sandbox protecting real API keys/tokens, and the 0600-permission tests for `test_credential_service.py`/`test_secrets.py`/`test_image_gen_token_rotation.py`) without any change to production security-enforcement logic itself | No unit in this plan changes what CI enforces on POSIX; Unit 3 fixes a Windows-only shim bug, Unit 4 fixes a Windows-only test-sandbox gap, and Unit 5 makes local Windows test *assertions* platform-aware without touching `_util/permissions.py`'s actual enforcement code. Use `_credential_tripwire`'s pass/warn history (see Unit 4) as ongoing evidence this hasn't drifted into an actual weakening. |
| Repeated sweeps on unchanged code disagree by dozens of failures (`-n auto` nondeterminism plus at least one genuinely flaky lock test) | Don't trust a single before/after snapshot as proof a fix worked or didn't; re-run 2-3 times per checkpoint, and for Unit 3 specifically prefer a full-suite `-n auto` run over an isolated single-test run (the flaky case only reproduces under concurrent load). |
| This shared workspace has at least one other concurrent, uncommitted line of work fixing overlapping bugs right now | Confirm with whoever/whatever produced the uncommitted changes described in "Concurrent Uncommitted Work Discovered" before starting implementation, so this plan's remaining units build on top of that work instead of re-solving or reverting it. |
| Unit 3's shim fix could subtly change lock semantics in a way that only shows up under real concurrent load, not in tests | The two cross-process tests (`test_reliability_circuit_crossproc.py`) already exercise real multi-process contention; treat their pass/fail as the primary signal, not just the single-process dedup tests. |
| Unit 5's shared helper could be written loosely enough to silently weaken POSIX/CI enforcement too | Explicitly test the POSIX branch of the helper (first Unit 5 test scenario) before rolling it out to 20+ call sites. |
| Editable-install repair (Unit 1) is a local machine fix, not a tracked-file change — it will not show up in a diff/PR and could look like it "didn't happen" | The guard-rail sanity check (also part of Unit 1) is the durable, reviewable artifact; the reinstall itself is a one-time operational step to note in the PR description. |
| Removing em dashes from `mypy.ini`/`pyproject.toml` (Unit 2) is a cosmetic-looking diff that a reviewer might question | Reference this plan's diagnosis (exact byte offset, exact `UnicodeDecodeError`) in the commit/PR description so the "why" is legible without re-deriving it. |
| Fixing Unit 6 might reveal the hook script needs a dependency not present on Windows at all, making a real fix impossible | Falls back cleanly to the documented `skipif` path already scoped in Unit 6's Approach — not a blocker for the rest of the plan. |

## Documentation / Operational Notes

- Unit 5 should close the loop on `post-fleet-merge-full-suite-measurement-2026-07-06.md`'s explicit open follow-up — either append to that doc or add a new dated `docs/solutions/test-failures/` entry cross-linking it, per this repo's own `docs/solutions/` convention.
- Consider a one-line addition to `backlink-publisher/AGENTS.md`'s environment/CI section noting that local Windows mypy runs should use `--platform linux` to match CI's Ubuntu runner — not a code fix, just closing the "why did my laptop show 73 errors CI doesn't" confusion for the next person who runs this sweep.

## Sources & References

- `backlink-publisher/AGENTS.md` §CI (GitHub Actions) — authoritative CI job list, confirms `mypy src/backlink_publisher --config-file mypy.ini` is CI-blocking and runs on `ubuntu-latest`.
- `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md` — prior baseline (105 failed/10 errors) and the open follow-up this plan's Unit 5/6 close.
- `docs/solutions/logic-errors/git-hookspath-config-redirects-hook-installation-2026-05-18.md` — related hook-installer fragility pattern, referenced in Unit 6.
- `src/backlink_publisher/_compat/fcntl.py`, `src/backlink_publisher/__init__.py:36-40`, `src/backlink_publisher/_util/permissions.py`, `tests/conftest.py:257-292`, `tests/test_no_raw_home_path_primitives.py`, `mypy.ini`, `pyproject.toml` — all read directly during this planning pass; findings are reproducible via the exact commands in the Overview.
