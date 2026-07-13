---
title: "feat: error/bug-report system — capture any failure into a coding-agent-ready bundle"
type: feat
status: active
date: 2026-07-09
origin: user request — 當使用者遇到問題時，能一鍵把錯誤現場抓出來，打包成可直接交給 coding agent 修復的報表
deepened: 2026-07-09
claims:
  # Restored 2026-07-13 after feat/error-bug-report merged to origin/main
  # (schema note: only paths/shas keys are allowed — the original summary key
  # was rejected by plan-check). Not claimed because still open: the
  # bp-report-bug pyproject entrypoint and the WebUI 匯出診斷包 button
  # (webui_app/static/js/ui/error-report-entry.js was never created).
  paths:
    - src/backlink_publisher/cli/report_bug/__init__.py
    - src/backlink_publisher/cli/report_bug/_build.py
    - src/backlink_publisher/cli/report_bug/main.py
    - webui_app/api/v1/error_report_bundle.py
    - webui_app/api/v1/__init__.py
    - tests/test_report_bug_build.py
    - tests/test_report_bug_cli.py
    - tests/test_webui_api_v1_error_report_bundle.py
---

# Plan: Error / Bug-Report System (2026-07-09-002)

## Goal

When the operator hits any problem (a failing CLI command, or a failed WebUI
pipeline run), produce a **self-contained, secret-redacted** diagnostic bundle
(Markdown + JSON) that can be pasted straight into a chat with a coding agent.
The bundle collects, in one place: the typed error, an environment snapshot, a
sanitized config snapshot, storage health, recent runs, and remediation hints.

## Design decisions (confirmed with user)

- **CLI capture:** `bp-report-bug --wrap "CMD"` wraps the failing command as a
  subprocess (stdout passes through untouched; stderr is buffered + echoed; a
  non-zero exit triggers the report). Zero edits to the 45 existing entrypoints.
- **Surface:** CLI + WebUI button. The WebUI already holds the failed run's
  stderr + typed-error envelope in memory (via `cli_runner`), so a button POSTs
  that context to the new endpoint.

## Reused (not re-invented)

- `PipelineError` family + `emit_error` / `handle_error` (`_util/errors`).
- `__BLP_ERR__` typed-error envelope + `ErrorEnvelope.parse` (`_util/error_envelope`).
- Structured-key redaction `_redact_in_place` / `_SENSITIVE_KEYS` (`_util/logger`).
- Storage-health `_check_all` (`cli/ops/health_check`).
- Recent runs via `checkpoint.list_all_runs()`.
- WebUI `sanitize_error_report` (Unit-1: free-text + structured + exact
  known-credential-value matching) — strictly stronger than the core's own
  regex scrubber; the WebUI endpoint routes free text through it.

## Components

1. `src/backlink_publisher/cli/report_bug/_build.py` — the shared builder
   (environment/config/health/recent-runs snapshots, typed-error section,
   free-text + structured redaction, error-class self-diagnosis, Markdown/JSON
   rendering, and 0600 file persistence). Lives under `cli` (domain) so it may
   import `health_check` / `checkpoint`; imports from `_util` only (allowed
   direction), never the reverse.
2. `src/backlink_publisher/cli/report_bug/main.py` — the `bp-report-bug` CLI
   (`--wrap`, `--stderr-file`, `-`, `--describe`, `--run-id`, `--output`,
   `--json`, `--no-redact`). stdout emits one JSONL line with the report paths;
   human summary goes to stderr.
3. `webui_app/api/v1/error_report_bundle.py` — `POST /api/v1/error-reports/
   export-bundle`, reusing `sanitize_error_report` + the core builder.
4. `webui_app/static/js/ui/error-report-entry.js` — a "匯出診斷包" button in the
   existing report panel (pure fetch + Blob download; no inline handlers, no
   innerHTML).
5. `pyproject.toml` — `report-bug` script entrypoint.
6. `monolith_budget.toml` — SLOC ceilings for the three new source files.

## Output contract

- stdout = pure JSONL (one line: `{report_path, json_path}`, plus `report` when
  `--json`). The bundle itself is written to disk (0600).
- Exit codes: 0 success; 2 insufficient input; 5 report build failure.
- All secrets masked by default; `--no-redact` is an explicit opt-out that
  warns loudly.

## Tests

- `tests/test_report_bug_build.py` (unit): section assembly, secret redaction
  (free-text + structured), JSON parseability, self-diagnosis mapping, 0600
  persistence, no-error-source general path.
- `tests/test_report_bug_cli.py` (unit): `--wrap` failure builds a report and
  masks the secret; `--wrap` success exits 0 without a report; `--stderr-file`
  parses the envelope; `--json` includes the report; `--no-redact` leaks; no
  source exits 2.
- `tests/test_webui_api_v1_error_report_bundle.py` (integration): returns
  Markdown + paths, redacts secrets, general path, CSRF required, invalid body
  400.

## Risks / mitigations

- **Secret leakage:** every structured section runs `_redact_in_place`; free
  text runs the regex scrubber (Bearer / authorization: Basic / key=value); the
  WebUI path *additionally* runs the Unit-1 known-credential matcher. Unit tests
  assert specific token/cookie values never appear in the bundle.
- **Original command affected:** `--wrap` passes stdout through and echoes
  stderr live; a report-build failure is caught and never masks the wrapped
  command's own result.
- **Import boundaries:** the builder is under `cli` (not `_util`), so core never
  imports `webui_app`; webui importing core is the existing, allowed direction.

## Rollout

Ships as a new, additive command + endpoint; no existing entrypoint or
error-reporting subsystem is modified beyond the additive WebUI button and the
new route registration.
