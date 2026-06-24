---
title: "Optimization Phase 2: mypy strict, spray budget, test splits, exception audit"
date: 2026-06-23
status: draft
type: optimization
priority: high
claims:
  paths:
    - src/backlink_publisher/publishing/
    - src/backlink_publisher/events/
    - src/backlink_publisher/cli/spray_backlinks/core.py
    - mypy.ini
    - monolith_budget.toml
  shas: []
---

# Optimization Phase 2: mypy strict, spray budget, test splits, exception audit

## Goal

Execute the four remaining high-ROI optimization items deferred from Phase 1 (June 2026). The codebase is already heavily optimized — these are the last structural improvements before v0.5.0 release.

## Implementation Units (ordered by dependency)

### U1 — mypy strict: publishing.* subpackage

| Field | Value |
|-------|-------|
| **Goal** | Enable `strict = true` in mypy.ini for `src/backlink_publisher/publishing/` |
| **Status** | Currently commented out: `# "src/backlink_publisher/publishing/.*\\.py" → strict` |
| **Approach** | 1. Run mypy with strict=on, collect all errors. 2. Fix type errors in smallest-unit commits (adapter-by-adapter). 3. Uncomment the section in mypy.ini. 4. Confirm CI passes. |
| **Files** | `mypy.ini`, all files under `src/backlink_publisher/publishing/` |
| **Risks** | 20+ adapters. Adapter `register()` calls have `dofollow=` keyword requirement. May need interface type annotations. |
| **Verify** | `mypy src/backlink_publisher/publishing/ --strict` → exit 0 |

### U2 — mypy strict: events.* subpackage

| Field | Value |
|-------|-------|
| **Goal** | Enable `strict = true` in mypy.ini for `src/backlink_publisher/events/` |
| **Dependency** | U1 (same pattern, shared test fixtures) |
| **Approach** | Same as U1: collect errors, fix, flip switch. |
| **Files** | `mypy.ini`, all files under `src/backlink_publisher/events/` |
| **Risks** | Dataclass-based events, projectors, reducers, store, history_query. Need careful type annotations on callback signatures. |
| **Verify** | `mypy src/backlink_publisher/events/ --strict` → exit 0 |

### U3 — spray_backlinks/core.py monolith budget

| Field | Value |
|-------|-------|
| **Goal** | Bring `core.py` from 621 SLOC under the 540 ceiling |
| **Approach** | Extract 2-3 focused modules from core.py (e.g., text generation strategies, URL validation/sorting, batch dispatch). Preserve public API at `core.py`. |
| **Files** | `src/backlink_publisher/cli/spray_backlinks/core.py` (modify), new `src/backlink_publisher/cli/spray_backlinks/text.py`, `src/backlink_publisher/cli/spray_backlinks/dispatch.py` (create), `monolith_budget.toml` (update if needed) |
| **Risks** | Fragile import web. Characterization tests needed. |
| **Verify** | Measure SLOC: `wc -l $(find src/backlink_publisher/cli/spray_backlinks -name '*.py')` → core.py ≤540, total ≤ original total |

### U4 — Test file splitting (top 3)

| Field | Value |
|-------|-------|
| **Goal** | Split 3 largest test files: `test_cli_generate_backlink_text.py` (1546), `test_content_fetch.py` (1336), `test_plan_backlinks.py` (1179) |
| **Approach** | 1. Create `test_*_split1.py`, `test_*_split2.py` per original. 2. Distribute test classes/functions preserving all imports. 3. Keep shared fixtures in conftest.py. 4. Keep original as thin wrapper importing from splits (minimal diff). |
| **Files** | `tests/test_cli_generate_backlink_text.py`, `tests/test_content_fetch.py`, `tests/test_plan_backlinks.py` (modify), new split files per test |
| **Risks** | Fixture scope. conftest.py colocation. pytest collection order. |
| **Verify** | `pytest tests/ -x --tb=short` → same number of collected tests, all pass |

### U5 — except Exception: cleanup

| Field | Value |
|-------|-------|
| **Goal** | Find and clean remaining bare `except Exception:` (estimated ~20% of original 137) |
| **Approach** | 1. Grep for bare `except Exception:`. 2. Audit each: add `logger.exception()` with context, or narrow to specific exception type. 3. If the exception truly can't be narrowed, add explanatory comment. |
| **Files** | Various (`grep -rn "except Exception:" src/ backlink_publisher/ --include='*.py'`) |
| **Verify** | Count before/after: `grep -c "except Exception:" $(find src/backlink_publisher -name '*.py')` |

## Execution Order

```
U1 ───> U2
         │
         ├──> U3 (independent, parallel with U2)
         ├──> U4 (independent, parallel with U2)
         └──> U5 (independent, parallel with U2)
```

U1 (publishing strict) must finish before U2 (events strict) starts, since they share type-fix patterns.

U3/U4/U5 are independent of U1/U2 and of each other — they run in parallel.

## Verification (cross-unit)

1. `pytest tests/ -x --tb=short` → all pass
2. `mypy src/backlink_publisher/ --strict` → exit 0 (for enabled subpackages)
3. SLOC budgets: `monolith_budget.toml` ceilings all honored
4. No regression in existing test count (compare before/after `pytest --collect-only | grep -c "<Function"`)
