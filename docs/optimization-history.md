# Optimization History

> Consolidated summary of all optimization phases (P1–P10).
> Supersedes: `OPTIMIZATION_REPORT.md`, `OPTIMIZATION_PHASE3_REPORT.md`,
> `FINAL_OPTIMIZATION_REPORT.md`, `OPTIMIZATION_COMPLETE_REPORT.md`.

## Phase 1 — Security & Reliability (completed)
- SSL cert validation hardened
- Exception handling improved (structured + typed)
- Opt-in state fix applied

## Phase 2 — Thread Safety (completed)
- `HttpClient` made thread-safe with lock-free reads

## Phase 3 — Test Coverage (completed)
- 79 new tests for 5 previously untested modules

## Phase 4 — Code Quality (completed)
- Config `token_path` deduplication
- Mypy config prep for type checking

## Phase 5 — Cross-Platform (P1 in this report)
- **11 files** fixed: `import fcntl` → `from backlink_publisher._compat import fcntl`
- **4 lazy imports** fixed inside function bodies
- Windows `_compat/fcntl.py` now the single fcntl source

## Phase 6 — Exception Hygiene (P2)
- **6 rollback `except Exception: pass` blocks** upgraded with structured logging
- `webui_app/api/drafts_api.py`: all 4 rollback blocks now log errors
- `spray_backlinks/core.py` + `_gates.py`: corrupt-checkpoint skipping now debug-logs

## Phase 7 — CLI Boilerplate (P3)
- `src/backlink_publisher/cli/_shared.py` created with:
  - `LOG_LEVELS` constant (single source of truth)
  - `add_log_level_arg()` helper
  - `validate_log_level()` for UsageError exit-1 convention
  - `setup_logging()` for unified log + config-echo init
- **5 CLI files** migrated: `canary_seed`, `canary_targets`, `cull_channels`, `preflight_targets`, `spray_backlinks/core`

## Phase 8 — Type Safety (P4)
- **86 mypy errors → 0 errors in 395 source files**
- 18 fcntl `[attr-defined]` cleared by compat layer
- 4 `[no-untyped-def]` in `cli_format.py`: `IO[str]` annotations added
- 6 `[call-arg]` in browser adapters: PipelineLogger calls fixed
- 3 `[no-any-return]`: `cast()` added for TTL cache returns
- 2 `[unused-ignore]`: stale `# type: ignore` comments removed
- 1 `[unreachable]`: `_store_sqlite.py` restructured for cross-platform
- 1 `[attr-defined]`: `os.geteuid` on Windows annotated with `# type: ignore`

## Phase 9 — Test Hygiene (P7)
- **17 test files** missing `__tier__` markers now have them
- Proper tiering: CLI tests → `"unit"`, SQLite/network tests → `"integration"`

## Phase 10 — Documentation (P6, P10)
- Vue 3 SPA migration roadmap: `docs/spa-migration-roadmap.md`
- This consolidated history: `docs/optimization-history.md`

## Key Metrics After All Phases

| Metric | Before | After |
|---|---|---|
| Source files | 393 | 395 (+2) |
| Mypy errors | 86 | **0** |
| `# noqa: C901` | 2 | 1 (accepted: argparse dispatcher) |
| Bare `import fcntl` | 15 | **0** |
| `except Exception: pass` | 6 rollback blocks | **0** (all logged) |
| CLI `_LOG_LEVELS` definitions | 5 | **0** (centralized) |
| Test files without `__tier__` | 17 | **0** |
