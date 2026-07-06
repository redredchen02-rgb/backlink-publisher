---
title: Fix Windows Console/Subprocess UTF-8 Encoding Crashes in WebUI Publish + Launchers
type: fix
status: completed
date: 2026-07-03
claims:
  paths:
    - src/backlink_publisher/_util/
    - src/backlink_publisher/sdk/_cli_runner.py
    - src/backlink_publisher/cli/pipeline_orchestrator.py
    - src/backlink_publisher/optimization/collector.py
    - webui_app/services/bind_job.py
    - webui_app/services/keepalive_job.py
    - webui_app/services/browser_login.py
    - scripts/
    - tests/
  shas: []
---

# Fix Windows Console/Subprocess UTF-8 Encoding Crashes in WebUI Publish + Launchers

**Target repo:** `backlink-publisher` (paths below are relative to this repo's root unless marked `workspace-root/...`)

## Overview

On a Windows machine running under a non-UTF-8 system locale (Traditional Chinese, ANSI codepage `cp950`/Big5), two related but distinct symptoms were reported from a single pasted WebUI session log:

1. **Functional**: publishing to Medium fails every time — `webui_publish_result` logs `state="all_failed"`, `error_class="unrecognized"`, with `stderr_preview: "'cp950' codec can't encode character '关' in position 277: illegal multibyte sequence"`.
2. **Cosmetic**: the WebUI startup banner (printed by the double-clicked `.bat` launcher) renders as mojibake (`[??] WebUI ??銝?..` instead of `[啟動] WebUI 啟動中...`).

Both trace to the same root cause *class* — Windows text encoding falling back to the legacy ANSI codepage instead of UTF-8 — but at two different layers (Python subprocess I/O vs. `cmd.exe` console rendering), so they need two different fixes. This plan fixes both, plus the same latent defect in four other subprocess call sites that share the exact same gap and would otherwise crash the same way under different WebUI actions (channel binding, keep-alive full-pipeline runs, browser-login, and the standalone pipeline-orchestrator/optimization CLIs).

Two additional log lines from the same session were investigated and found **not** to be bugs — see [Resolved During Planning](#resolved-during-planning) — so this plan does not touch them.

## Problem Frame

The user pasted a raw WebUI terminal session (Windows, waitress server, `启动WebUI.bat` launcher) showing a garbled startup banner followed by a failed Medium publish attempt, and asked for it to be fixed because "現在連啟動都是問題" (now even starting up is a problem).

Direct code inspection (not guesswork) confirmed the mechanism:

- Medium is a **browser-tier** platform (`_is_browser_tier`), so `PipelineAPI.publish()`/`publish_seed()` (`src/backlink_publisher/sdk/api.py`) spawns a real `publish-backlinks` CLI **subprocess** (all other, non-browser-tier platforms run in-process and are unaffected).
- That subprocess is launched via `run_pipe_capture()`/`run_pipe()` in `src/backlink_publisher/sdk/_cli_runner.py`, using `subprocess.run(..., capture_output=True, text=True, env=env, ...)` with **no explicit `encoding=`** and an `env` built by copying `os.environ` with **no `PYTHONIOENCODING`/`PYTHONUTF8` override**.
- When a Python subprocess's stdout/stderr is a **pipe** (not a real console — true whenever the parent uses `capture_output=True`), Python has no console to write through and falls back to `locale.getpreferredencoding(False)` — the Windows **ANSI codepage** (`cp950` on this machine) — for its own internal text I/O. `cp950` (Big5) cannot represent all Unicode CJK, notably many Simplified Chinese characters (like `关`, U+5173) scraped from the target content site and folded into the article/anchor text. When the child process tries to write that text to its own stdout, it raises an unhandled `UnicodeEncodeError`.
- That crash happens *before* the child reaches its typed-error-envelope chokepoint (`_util/error_envelope.py` / `emit_error`), so the parent never sees a parseable envelope — it falls into the QUARANTINE path, which is exactly why the WebUI logs `error_class="unrecognized"` (see `docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md`).
- Separately, the **parent** WebUI process's own printed log lines (including ones containing CJK/Japanese titles) rendered *correctly* in the pasted log — because that process is attached to a real console, where Python uses the Win32 `WriteConsoleW` API directly and bypasses the codepage entirely. This is a real console vs. pipe distinction, not evidence that "encoding works fine here" — it explains why only the *subprocess* path breaks.
- The garbled startup banner is unrelated to Python at all: `启动WebUI.bat` and two packaged `.bat` scripts under `scripts/` (`start-webui.bat`, `start-cli.bat`) `echo` literal Chinese text with no `chcp 65001` guard, so `cmd.exe` renders the files' UTF-8 bytes using the active (non-UTF-8) console codepage. The workspace-root `start-webui.bat` ("ASCII-safe name" launcher) also contains one non-ASCII character (an en dash) with no guard, sharing the defect on a smaller scale. `scripts/launcher.ps1` shares the same root issue via a different mechanism — PowerShell's `Write-Host` follows `[Console]::OutputEncoding`, not `chcp` — so all five launcher files need a fix (see Unit 4).

This is not a novel problem for this codebase — a structurally identical bug (`'ascii' codec can't encode characters...` on CJK/Korean URLs during fetch) was already found and fixed once, narrowly, at the transport boundary in `docs/_archive/plans/2026-05-21-005-fix-verify-non-ascii-url-ascii-codec-plan.md`. This plan follows the same shape: a small, stdlib-only, canonical `_util/` helper applied at every subprocess text-I/O boundary, not a broad rewrite.

## Requirements Trace

- R1. Medium (and any other browser-tier platform) publish must not crash with `UnicodeEncodeError` when article/anchor content contains characters outside the operator's Windows ANSI codepage.
- R2. When a browser-tier publish genuinely fails for a real reason (auth expired, dependency missing, etc.), the typed-error envelope must still surface correctly — this fix must not weaken `error_class` fidelity or the `run_pipe` silent-failure guard.
- R3. Every other production subprocess call site with the same gap (no explicit UTF-8 text handling) gets the same fix, so the bug doesn't resurface via a different WebUI action.
- R4. The double-clicked Windows launcher's startup banner must render correctly (no mojibake) under a non-UTF-8 system locale.
- R5. Investigate the two other anomalous log lines from the reported session (missing-config warning, BeautifulSoup replacement-character warning) and either fix them or explicitly document why they're benign.

## Scope Boundaries

- No change to the adapter registry, CLI flags, or `schema.py`.
- No change to the Windows config-directory convention (`%APPDATA%\backlink-publisher`) — confirmed working as designed (see Resolved During Planning).
- No change to how scraped source-site HTML is decoded (the BeautifulSoup warning is about the *target* site's malformed encoding, not this codebase).
- Not editing generated/packaged files under `dist/backlink-publisher-v0.5.0-win64/**` — these are build artifacts regenerated from `scripts/` source at package time.
- Not adding a stdio-encoding safeguard to `serve.py`'s own startup path — the reported bug is a console-attached, interactively-launched session; headless/service deployment is a distinct, separate concern (see Deferred / Open Questions).

### Deferred to Separate Tasks

- Aligning the workspace-root `.bat` launchers with the AGENTS.md "One launcher (R9)" convention (they should delegate to `scripts/launcher.ps1` rather than duplicating its logic) — this is a pre-existing architectural drift, unrelated to the encoding bug, and out of scope for a bug-fix PR.
- Writing up this fix (and the never-documented 2026-05-21-005 URL-codec fix) as a `docs/solutions/` institutional-learning entry — recommended, but a documentation task, not implementation; noted under Documentation Notes below.
- `scripts/start-webui.bat` and `scripts/start-cli.bat` share the same mojibake defect as the other launchers, but turned out to be **uncommitted, not-yet-landed files** on `main` at implementation time (part of unrelated in-progress work in the shared canonical checkout) — they don't exist in this branch's history and weren't fabricated here. Apply the same `chcp 65001 >nul` guard to them whenever that other work lands.
- Adding the same stdio-encoding safeguard to `serve.py`'s startup path for headless/service deployment (Windows service, Task Scheduler, redirected-output invocation) — a real gap identified during review, but a different topology than the reported bug; left as a follow-up.

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/sdk/_cli_runner.py` — `_rewrite_cli_cmd()` (builds the child `env`, currently only sets `PYTHONPATH`), `_base_subprocess_kwargs()` (builds the shared `subprocess.run` kwargs, currently `text=True` with no `encoding=`). This is the confirmed root-cause call site (invoked via `PipelineAPI._invoke_capture()` → `run_pipe_capture()`, `src/backlink_publisher/sdk/api.py:441,461`).
- Five other production call sites share the identical gap (`text=True`/text-mode `Popen`, no `encoding=`, no `PYTHONIOENCODING`/`PYTHONUTF8` in `env`):
  - `webui_app/services/bind_job.py` (~line 100) — `BindJobRegistry.start()` spawns `bind-channel` via `Popen(..., stdout=PIPE, stderr=PIPE, text=True, bufsize=1)`.
  - `webui_app/services/keepalive_job.py` (~line 242) — gap-closure job runs `bash scripts/run-full-pipeline.sh` via `subprocess.run(..., capture_output=True, text=True, env=env)`.
  - `webui_app/services/browser_login.py` (~line 77) — `spawn_browser_login()` runs `python -m <login-module>` via `Popen(..., env={**os.environ, "PYTHONPATH": pythonpath})`; output goes to a log file, but the *child's own* stdout encoding still defaults to the ANSI codepage.
  - `src/backlink_publisher/cli/pipeline_orchestrator.py` (lines ~138, ~178, ~388) — three `subprocess.run(cmd, capture_output=True, text=True, timeout=...)` calls that don't even pass `env=` today (pure addition, not a modification).
  - `src/backlink_publisher/optimization/collector.py` (~line 150) — `_try_cli_collect()` shells out to `backlink_publisher.cli.<command>` the same way.
- `src/backlink_publisher/publishing/adapters/medium_brave.py` uses `subprocess` too, but is macOS-gated (`_require_macos()`); on Windows, Medium falls back to `MediumBrowserAdapter` (Playwright, in-process, no subprocess) — **not** part of this bug and not touched.
- `src/backlink_publisher/cli/_bind/chrome_backend.py` launches Chrome via `Popen(..., stdout=DEVNULL)` — output discarded, no decode/encode risk, not touched.
- No existing `_util/` helper or documented convention for UTF-8-safe subprocess I/O exists anywhere in the repo (confirmed via repo-wide grep for `PYTHONIOENCODING`, `PYTHONUTF8`, `reconfigure(encoding`, `chcp` — zero hits) — this plan establishes the first one, following the existing `_util/paths.py` / `_util/errors.py` pattern of canonical cross-cutting helpers.
- `src/backlink_publisher/config/_config_io.py:_snapshot_config()` and `src/backlink_publisher/_util/paths.py:_config_dir()` — read during investigation; confirmed benign (see Resolved During Planning).

### Institutional Learnings

- `docs/_archive/plans/2026-05-21-005-fix-verify-non-ascii-url-ascii-codec-plan.md` (completed) — the closest prior precedent: CJK/Korean URLs crashed `urllib` with an ASCII-codec error; fixed narrowly via a stdlib-only normalization helper at the transport boundary, with CJK-fixture regression tests. This plan mirrors that shape. **Gap**: that fix was never captured into `docs/solutions/` — worth doing for both fixes together (see Documentation Notes).
- `docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md` — documents the `__BLP_ERR__` sentinel envelope contract and the `error_class="unrecognized"` QUARANTINE fallback that fires when a child dies before reaching its own error-emission chokepoint. Confirms the exact mechanism behind the `error_class="unrecognized"` the user observed, and constrains the fix: the goal is to stop the child from crashing on encode at all, not just to reformat how the parent surfaces the crash after the fact.
- `docs/_archive/plans/2026-05-21-004-fix-webui-publish-false-success-plan.md` (completed) — establishes that `run_pipe`'s silent-failure guard (exit 0 + empty stdout + empty stderr → diagnostic exception) and the generic `except Exception` → `_push_history_single_failure` path in the publish route are load-bearing conventions this fix must not disturb.
- `docs/solutions/ui-bugs/webui-blocking-subprocess-and-missing-progress-feedback-2026-05-12.md` — establishes the team's practice of grep-auditing all `subprocess.run`/`Popen` call sites before assuming a fix is localized to one file; this plan's Unit 3 scope is the result of doing exactly that audit.
- No prior documented rationale for `text=True` without explicit `encoding=` was found anywhere — it is an unexamined stdlib default, not a deliberate choice being overridden.

### External References

None consulted. The failure mode (Windows subprocess pipes falling back to the ANSI codepage; console-attached processes bypassing it via `WriteConsoleW`; `cmd.exe`'s codepage-dependent `echo` rendering) is well-established core CPython/Win32 behavior, not framework- or version-specific, so no external documentation lookup was needed.

## Key Technical Decisions

- **New canonical helper in `_util/`, not per-call-site fixes**: introduce `src/backlink_publisher/_util/subprocess_env.py` once and apply it at all six call sites, rather than duplicating the same two-line change six times. Matches the existing `_util/paths.py`/`_util/errors.py` convention and the 2026-05-21-005 precedent (fix once at the canonical boundary).
- **`PYTHONIOENCODING=utf-8` in the child env, not `PYTHONUTF8=1`**: `PYTHONIOENCODING` only affects the child's stdio text layer (the confirmed failure surface). `PYTHONUTF8` (PEP 540) additionally changes the child's default filesystem/`open()` encoding process-wide, a much broader blast radius this fix doesn't need and can't fully regression-test across every downstream adapter.
- **`encoding="utf-8", errors="replace"` on the parent side's `subprocess.run`/`Popen` calls**: `errors="replace"` matches the dominant existing convention already used throughout this codebase for decode boundaries (`content/scraper.py`, `linkcheck/verify.py`, `publishing/adapters/link_attr_verifier.py` all use `errors="replace"`). Passing `encoding=` alongside the existing `text=True` is safe — per the `subprocess` docs, `encoding=` implies text mode, so no conflict.
- **Force UTF-8 unconditionally (not `setdefault`)**: the helper always sets `PYTHONIOENCODING=utf-8` in the merged env, overriding any inherited value, since correctness here doesn't depend on operator configuration.
- **`.bat`/`.ps1` fix is a `chcp`/`OutputEncoding` guard only, not an R9 delegation refactor**: keeps this a minimal, reviewable bug-fix; the larger "one launcher" convention alignment is tracked separately (see Scope Boundaries).
- **`utf8_child_env()`'s parameter type is `Mapping[str, str] | None`, not `dict[str, str] | None`** (added during code review): `os.environ` is an `os._Environ[str]`, not a `dict`, and mypy (CI-blocking per AGENTS.md) correctly rejected the narrower signature at the `_cli_runner.py` call site. `dict(base_env)` already accepts any `Mapping` at runtime, so this was a pure typing fix.

## Open Questions

### Resolved During Planning

- **"Failed to read config for snapshot: [Errno 2] No such file or directory: '...\AppData\Roaming\backlink-publisher\config.toml'"** — investigated `src/backlink_publisher/_util/paths.py:_config_dir()`: on Windows (`os.name == "nt"`), the config dir is intentionally `%APPDATA%\backlink-publisher` (the Windows Roaming-profile convention), distinct from the Unix `~/.config/backlink-publisher/` documented in `CLAUDE.md`/`AGENTS.md`'s cross-platform path table — that table's `~/.config/...` row is the macOS/Linux side only. `_config_io.py:_snapshot_config()` catches the missing-file case, logs a `WARNING`, and returns — by design, for a first-ever config save with no prior snapshot to redact-and-rotate. Confirmed non-fatal: the very next log line (`homepage_form_persisted`) succeeds. **No fix needed.**
- **"Some characters could not be decoded, and were replaced with REPLACEMENT CHARACTER."** — traced to `bs4/dammit.py`'s `UnicodeDammit`, logged when BeautifulSoup has to force-decode a fetched page whose declared/detected encodings all failed. This is a warning about the **target content site's** own malformed HTML encoding, surfaced during `content_fetch_prefetch`, not a bug in this codebase's console/subprocess handling. **No fix needed**; unrelated to R1–R4.
- **Where the UTF-8 helper should live** — `src/backlink_publisher/_util/subprocess_env.py` (new module), matching the existing `_util/` convention.
- **`PYTHONIOENCODING` vs `PYTHONUTF8`** — see Key Technical Decisions.

### Resolved During Implementation / Review

- **Unit 2's CJK regression test can't fail pre-fix on this repo's CI (ubuntu-only)** (deferred during doc review, resolved during implementation) — resolved via option (a) from the deferred note: the test forces the child's `PYTHONIOENCODING=cp950` directly (rather than relying on the host OS's default locale), which reproduces the exact crash deterministically on any OS including `ubuntu-latest`, since `cp950` is a pure-Python stdlib codec, not an OS setting. Verified the test fails pre-fix (reproducing the exact `UnicodeEncodeError: 'cp950' codec can't encode character '关'` from the bug report) and passes post-fix. See `tests/test_webui_error_fidelity.py::test_child_subprocess_survives_non_big5_cjk_with_utf8_child_env` and the analogous real-subprocess test in `tests/test_browser_login_helper.py`.
- **Plan assumes the WebUI parent process is always console-attached; no fix for headless/service deployment** (deferred during doc review) — decided to explicitly document as an accepted out-of-scope gap rather than extend scope: the reported bug is a console-attached, interactively-launched session; headless/service deployment is a distinct topology and a reasonable follow-up, not a blocker for this fix (see Scope Boundaries).
- **`utf8_child_env(os.environ)` mypy type error** (found by code review, `ce-kieran-python-reviewer`, confirmed via a real `mypy src/backlink_publisher` run) — fixed by widening the parameter type to `Mapping[str, str] | None`.
- **`_count_gaps`' own `subprocess.run` call in `pipeline_orchestrator.py` had no dedicated test** (found independently by three reviewers: maintainability, testing, kieran-python) — added `test_count_gaps_plan_gap_call_passes_utf8_encoding_and_pythonioencoding_env`.
- **`_rewrite_cli_cmd`'s `env=None` fallback for unrecognized CLI names silently bypassed the fix** (found by the adversarial reviewer, corroborated by correctness reviewer's residual risk) — the early-return branch for an unrecognized command now also builds `env` via `utf8_child_env(os.environ)` instead of returning `None`.
- **`launcher.ps1`'s unguarded `[Console]::OutputEncoding` assignment could throw when stdout is redirected** (found by both the correctness and adversarial reviewers) — wrapped in `try { } catch { }` so a redirected/non-interactive invocation degrades gracefully instead of aborting before the script's own error handling runs. Added a static-content regression test (`tests/test_launcher_ps1_encoding.py`) asserting the UTF-8 BOM and the `OutputEncoding` line both survive future edits.

### Deferred to Implementation

- Exact wording of the optional `docs/solutions/` write-up (Documentation Notes) — left to whoever picks that up.
- Whether to consolidate the repeated `encoding="utf-8", errors="replace"` literal kwargs (duplicated 7 times across 5 files) into a second shared constant alongside `utf8_child_env()` — flagged as advisory by three reviewers (maintainability, kieran-python) as a real but non-blocking maintainability tradeoff; not applied here to keep this fix minimal and mechanical, but worth revisiting if an 7th call site is ever added.

## High-Level Technical Design

> *This illustrates the intended shape of the shared helper and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
# src/backlink_publisher/_util/subprocess_env.py  (illustrative shape only)

def utf8_child_env(base_env: dict | None = None) -> dict:
    env = dict(base_env) if base_env is not None else os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"   # force, don't setdefault
    return env

# Applied at each call site, e.g.:
#   env = utf8_child_env(env)                      # was: env = os.environ.copy()
#   subprocess.run(cmd, ..., text=True,
#                  encoding="utf-8", errors="replace",   # new
#                  env=env)
```

Every call site keeps its existing `text=True`/`Popen` shape; only the `env=` construction and the addition of `encoding`/`errors` kwargs change. (The shipped helper's parameter type is `Mapping[str, str] | None`, not `dict | None` -- see Key Technical Decisions.)

## Implementation Units

- [x] **Unit 1: Add the shared UTF-8-safe subprocess helper**

**Goal:** One canonical place to build a UTF-8-forcing child environment, so the fix isn't duplicated ad hoc across six call sites.

**Requirements:** R1, R3

**Dependencies:** None

**Files:**
- Create: `src/backlink_publisher/_util/subprocess_env.py`
- Test: `tests/test_subprocess_env_util.py`

**Approach:**
- One function, `utf8_child_env(base_env: dict | None = None) -> dict`, returning a copy of `base_env` (or `os.environ` if `None`) with `PYTHONIOENCODING` forced to `"utf-8"`.
- Pure stdlib (`os` only), no new dependency, no I/O.

**Patterns to follow:**
- `src/backlink_publisher/_util/paths.py` — existing `_util/` module shape (small, focused, no side effects at import time).
- `docs/_archive/plans/2026-05-21-005-fix-verify-non-ascii-url-ascii-codec-plan.md`'s `normalize_url_for_fetch` — narrow, canonical, stdlib-only helper at a transport boundary.

**Test scenarios:**
- Happy path: `utf8_child_env({"FOO": "bar"})` → returns `{"FOO": "bar", "PYTHONIOENCODING": "utf-8"}`.
- Edge case: `utf8_child_env(None)` → returns a copy of `os.environ` plus the override; does not mutate the real `os.environ`.
- Edge case: caller's base env already sets `PYTHONIOENCODING` to a different value → helper's return overrides it to `"utf-8"` (force, not setdefault).

**Verification:**
- New test file passes in isolation; no existing test imports or behavior touched.

---

- [x] **Unit 2: Fix the confirmed root cause — `_cli_runner.py`**

**Goal:** Stop Medium (and any other browser-tier platform) publish from crashing with `UnicodeEncodeError` under a non-UTF-8 Windows locale.

**Requirements:** R1, R2

**Dependencies:** Unit 1

**Files:**
- Modify: `src/backlink_publisher/sdk/_cli_runner.py` (`_rewrite_cli_cmd`, `_base_subprocess_kwargs`)
- Test: `tests/test_webui_error_fidelity.py`
- Test: `tests/test_webui_typed_error_surfacing.py`

**Approach:**
- `_rewrite_cli_cmd()`: build `env` via `utf8_child_env(os.environ)` instead of a bare `os.environ.copy()`, keeping the existing `PYTHONPATH` merge on top.
- `_base_subprocess_kwargs()`: add `encoding="utf-8", errors="replace"` to the shared kwargs dict, alongside the existing `text=True`.

**Patterns to follow:**
- `tests/test_webui_error_fidelity.py`'s existing `_FakeCompleted` + `patch("backlink_publisher.sdk._cli_runner.subprocess.run", return_value=fake)` pattern — the exact seam already used to test `run_pipe`/`run_pipe_capture`.

**Test scenarios:**
- Happy path: call `run_pipe_capture(["publish-backlinks"], "...")` with `subprocess.run` mocked; assert the captured call's kwargs include `encoding="utf-8"` and its `env["PYTHONIOENCODING"] == "utf-8"`.
- Integration: a real (non-mocked) `subprocess.run` invocation of a throwaway inline Python child (`python -c "print('关')"`) using `utf8_child_env()` + the new kwargs completes without `UnicodeEncodeError` — this is the regression test that would have failed before the fix, mirroring the CJK-fixture approach from the 2026-05-21-005 precedent. Prefer Traditional *and* Simplified characters in the fixture (e.g. `義` and `关`) since the bug is specifically about characters outside Big5.
- Regression (error path): `run_pipe`'s silent-failure guard (exit 0 + empty stdout + empty stderr + non-empty stdin → raises a diagnostic) still fires — unchanged by the encoding kwargs.
- Regression (integration): `test_webui_typed_error_surfacing.py`'s QUARANTINE/`error_class="unrecognized"` assertions for a genuine (non-encoding) failure still pass — confirms the fix doesn't mask real typed-envelope failures.

**Verification:**
- Existing `test_webui_error_fidelity.py` and `test_webui_typed_error_surfacing.py` suites pass unchanged in behavior (only new assertions added).
- The new integration-style CJK subprocess test fails on the pre-fix code and passes after. (Confirmed: the test forces `PYTHONIOENCODING=cp950` in the child directly, so this is verifiable on any OS, not just Windows — see Resolved During Implementation / Review.)

---

- [x] **Unit 3: Apply the same fix to the remaining production subprocess call sites**

**Goal:** Close the identical latent defect everywhere else it exists, so the bug doesn't resurface via a different WebUI action (channel binding, keep-alive full-pipeline run, browser-login) or the standalone CLIs (pipeline-orchestrator, optimization collector).

**Requirements:** R3

**Dependencies:** Unit 1

**Files:**
- Modify: `webui_app/services/bind_job.py` | Test: `tests/test_webui_bind_job_service.py`
- Modify: `webui_app/services/keepalive_job.py` | Test: `tests/test_keepalive_gap_closure_job.py` (new — no prior test exercised `start_gap_closure`'s subprocess call directly)
- Modify: `webui_app/services/browser_login.py` | Test: `tests/test_browser_login_helper.py`
- Modify: `src/backlink_publisher/cli/pipeline_orchestrator.py` | Test: `tests/test_pipeline_orchestrator.py`
- Modify: `src/backlink_publisher/optimization/collector.py` | Test: `tests/test_collect_signals.py`

**Approach:**
- `bind_job.py`, `keepalive_job.py`: same pattern as Unit 2 — wrap the existing `env` construction with `utf8_child_env(...)`, add `encoding="utf-8", errors="replace"` to the `Popen`/`run` call.
- `browser_login.py`: env is built inline (`{**os.environ, "PYTHONPATH": pythonpath}`) — replace with `utf8_child_env({**os.environ, "PYTHONPATH": pythonpath})`. Output still goes to a binary log file (`fh`, opened `"ab"`), so no `encoding=`/`errors=` kwargs apply here (the fix is entirely the child-env var, so the child's own `print()`/logging calls don't crash before writing bytes to the fd).
- `pipeline_orchestrator.py`, `optimization/collector.py`: these three call sites currently pass **no** `env=` at all — this is a pure addition (`env=utf8_child_env()`), plus `encoding="utf-8", errors="replace"` alongside their existing `text=True`. (`pipeline_orchestrator.py` has *three* such call sites: `_run_step`, `_run_pipe_step`, and `_count_gaps` — all three needed the fix and, after code review, all three ended up with dedicated test coverage.)

**Test scenarios:**
- Happy path (per file): assert the mocked/patched subprocess call now receives `env` containing `PYTHONIOENCODING="utf-8"` (and, where output is captured as text, `encoding="utf-8"` in the call kwargs).
- Regression (per file): existing pass/fail-path assertions in each test file continue to pass unchanged — this fix only adds kwargs, it doesn't change control flow.
- `browser_login.py` additionally got a real (non-mocked) end-to-end regression test forcing `PYTHONIOENCODING=cp950` and spawning a real stub subprocess that prints CJK content, confirming it survives via the actual production `spawn_browser_login()` function, not just a mocked-kwargs assertion.

**Verification:**
- All five modified files' existing test suites pass with the new env/kwargs assertions added.

---

- [x] **Unit 4: Fix the Windows launcher startup-banner mojibake**

**Goal:** The double-clicked Windows launcher displays its Chinese-language startup banner correctly under a non-UTF-8 system locale, instead of mojibake.

**Requirements:** R4

**Dependencies:** None (independent of Units 1–3 — different layer, console rendering vs. subprocess I/O)

**Files:**
- Modify: `workspace-root/启动WebUI.bat` (the launcher actually run in the reported session — confirmed by matching its literal echoed strings against the garbled output)
- Modify: `workspace-root/start-webui.bat` (the "ASCII-safe name" launcher — despite its name, it contains a literal U+2013 en dash in its port-exhaustion error line with no `chcp` guard, sharing the same defect class on a smaller scale)
- Modify: `scripts/launcher.ps1`
- Test: `tests/test_launcher_ps1_encoding.py` (new)

**Approach:**
- Add `chcp 65001 >nul` as the first line after `@echo off` in each workspace-root `.bat` file, so `cmd.exe`'s active console codepage matches the files' UTF-8-encoded Chinese text. While touching `workspace-root/start-webui.bat`, also replaced its literal U+2013 en dash with a plain ASCII hyphen so that line is unaffected by codepage even if the guard is ever skipped.
- Added `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` near the top of `launcher.ps1` (PowerShell 5.1's `Write-Host` follows `[Console]::OutputEncoding`, a separate mechanism from `cmd.exe`'s codepage), wrapped in `try { } catch { }` after code review flagged that the assignment throws when stdout has no real console handle (e.g. output redirected to a log file). Also saved `launcher.ps1` with a UTF-8 byte-order mark (BOM): Windows PowerShell 5.1 (Desktop edition) decodes a BOM-less `.ps1` file's literal characters using the system's active ANSI code page at *parse* time — before `[Console]::OutputEncoding` has any effect. `scripts/launcher.ps1` had no BOM and contains literal Simplified Chinese `Write-Host` strings, so on the exact cp950 machine this plan targets, those string literals would already have been mis-decoded in memory at parse time; setting `OutputEncoding` alone would not have fixed the mojibake for this file.
- This fix is purely about how the launcher's own literal text renders in the console — it is unrelated to, and does not affect, the child Python process's subprocess I/O encoding fixed in Units 1–3.
- **Scope note (finalized during implementation):** `scripts/start-webui.bat` and `scripts/start-cli.bat` were originally in this unit's file list, but turned out to be uncommitted, not-yet-landed files on `main` (part of unrelated in-progress work) — they don't exist in this branch's git history. Rather than fabricate them, this unit's scope was narrowed to the three files that actually exist in history; the other two are noted under Scope Boundaries → Deferred to Separate Tasks for whoever lands that other work.

**Test expectation:** `scripts/launcher.ps1` got a static-content regression test (`tests/test_launcher_ps1_encoding.py`) asserting the UTF-8 BOM and `[Console]::OutputEncoding` line both survive future edits — a real behavioral test needs an actual non-UTF-8-locale Windows PowerShell host, infeasible on this repo's ubuntu-only CI. The two `.bat` files remain untested (console-codepage change, no Python test surface); verify manually per below.

**Verification:**
- Double-click `启动WebUI.bat` on a non-UTF-8-locale Windows machine (or run with `chcp 950` active beforehand) and confirm the banner text (`[啟動] WebUI 啟動中...`, `網址: ...`, `關閉此視窗或按 Ctrl-C 即可停止服務`) renders correctly instead of as mojibake.
- Confirm `workspace-root/start-webui.bat`'s port-exhaustion message renders correctly and no longer contains the U+2013 en dash.
- Run `scripts/launcher.ps1` the same way (confirming it was saved with a UTF-8 BOM) and confirm its `Write-Host` banner renders correctly; also confirm it doesn't crash when invoked with redirected stdout (`powershell -File scripts\launcher.ps1 > out.log 2>&1`).

## System-Wide Impact

- **Interaction graph:** every text-capturing `subprocess.run`/`Popen` call in WebUI services (`bind_job`, `keepalive_job`, `browser_login`, the `_cli_runner` seam used by `PipelineAPI`) plus the standalone `pipeline-orchestrator` and `optimization/collector` CLIs.
- **Error propagation:** unaffected in shape — `run_pipe`'s silent-failure guard and the typed-error-envelope / QUARANTINE(`unrecognized`) fallback both continue to operate exactly as before; this fix only prevents one specific pre-envelope crash mode from occurring in the first place.
- **State lifecycle risks:** none — no persistent state, config, or history-store schema changes.
- **API surface parity:** none — internal subprocess plumbing only; no CLI flag, HTTP route, or adapter-registry changes. Confirmed by the agent-native code reviewer: the shared `_cli_runner.py` choke point means WebUI-driven and SDK/CLI-driven (agent) callers get identical encoding behavior — no new human/agent asymmetry introduced.
- **Integration coverage:** Unit 2's real (non-mocked) subprocess round-trip with CJK content, and `browser_login.py`'s equivalent end-to-end test, are the scenarios that unit/mocked tests alone can't prove — they exercise the actual Windows locale fallback behavior, not just that the right kwargs were passed.
- **Unchanged invariants:** the `stdout = clean JSONL / stderr = diagnostics` CLI contract; the typed-error envelope format; the Windows `%APPDATA%\backlink-publisher` config-dir convention; the macOS-gated `MediumBraveAdapter` path (untouched, irrelevant on Windows).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `errors="replace"` on the parent's decode could mask genuine mid-stream corruption in child output | Scoped identically to the existing repo-wide convention (`scraper.py`, `verify.py`, `link_attr_verifier.py` all already use `errors="replace"` at decode boundaries); only applies at the subprocess text-capture boundary, never to stored artifacts. Reliability review flagged one narrow residual case (`optimization/collector.py`'s `json.loads` could accept a corrupted-but-syntactically-valid payload) — low-likelihood, left as an advisory residual risk rather than adding an unvalidated sanity check. |
| A subprocess call site was missed despite the repo-wide grep audit | Audit covered every `subprocess\.(Popen\|run)` match in `src/` and `webui_app/` (excluding tests/archived scripts); macOS-only and output-discarded (`DEVNULL`) call sites were explicitly reviewed and excluded with rationale (see Context & Research). Independently re-confirmed by the adversarial and agent-native code reviewers, who found no additional unfixed call site. |
| `PYTHONIOENCODING=utf-8` in child env unexpectedly interacts with a downstream tool the child itself shells out to (e.g. Chrome/Playwright) | `PYTHONIOENCODING` only affects Python's own stdio text layer for the process it's set on; it has no effect on non-Python child processes further down the tree, and Python subprocesses further down would only benefit from the same fix if they inherit the env, which is the intended behavior. |
| `.bat`/`.ps1` edits get silently overwritten by the packaging step that produces `dist/backlink-publisher-v0.5.0-win64/**` | Edits target only the git-tracked `scripts/` and workspace-root originals; `dist/` artifacts are explicitly out of scope (see Scope Boundaries) and are regenerated from source at build time. |
| `_rewrite_cli_cmd`'s early-return branches silently bypassed the fix for unrecognized CLI names (found by adversarial review) | Fixed: both early-return branches now build `env` via `utf8_child_env(os.environ)` too. |
| `launcher.ps1`'s `[Console]::OutputEncoding` assignment throws when stdout is redirected (found by correctness + adversarial review) | Fixed: wrapped in `try { } catch { }`. |

## Documentation / Operational Notes

- Recommended (not required for this fix to land): capture this bug — and the previously-undocumented 2026-05-21-005 URL-ASCII-codec fix — as a single `docs/solutions/` entry (e.g. under `logic-errors/` or a new `windows-encoding/` category) describing the "Windows pipe-subprocess falls back to ANSI codepage; console-attached processes don't" pattern, so it isn't independently re-derived a third time. The learnings researcher (both during doc review and code review) independently confirmed this gap exists and no such entry currently exists anywhere in `docs/solutions/`.
- Unrelated, pre-existing bug discovered during full-suite verification (**out of scope, not touched**): several `cli/*.py` re-export shims created during an old CLI reorganization (e.g. `cli/equity_ledger.py`, `cli/report_anchors.py`, `cli/audit_state.py`, and others) do `from ... import *` but never re-declare `if __name__ == "__main__": main()`, so `python -m backlink_publisher.cli.<shim-name> --help` silently produces no output and exits 0 instead of running the CLI. Confirmed via git history to predate this branch by multiple commits and confirmed unrelated to this diff (the shim files import unrelated modules, and the affected module set doesn't overlap with anything this plan touches). Worth a separate follow-up sweep across all `cli/*.py` shims.

## Deferred / Open Questions

_All items from the 2026-07-03 review round were resolved during implementation — see "Resolved During Implementation / Review" above._

## Sources & References

- Related code: `src/backlink_publisher/sdk/_cli_runner.py`, `src/backlink_publisher/sdk/api.py`, `webui_app/routes/pipeline_publish.py`, `src/backlink_publisher/_util/paths.py`, `src/backlink_publisher/config/_config_io.py`
- Prior precedent (completed): `docs/_archive/plans/2026-05-21-005-fix-verify-non-ascii-url-ascii-codec-plan.md`
- Related (completed): `docs/_archive/plans/2026-05-21-004-fix-webui-publish-false-success-plan.md`
- Institutional learning: `docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md`
- Institutional learning: `docs/solutions/ui-bugs/webui-blocking-subprocess-and-missing-progress-feedback-2026-05-12.md`
- Convention reference: `AGENTS.md` — "One launcher (R9)" note and the macOS/Windows path-orientation table
