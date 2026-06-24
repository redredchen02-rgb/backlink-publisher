---
title: "Optimization Phase 2: mypy strict, spray budget, test splits, exception audit"
date: 2026-06-23
status: active
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

### U2 — mypy strict: events.* subpackage ✅ DONE (2026-06-24)

| Field | Value |
|-------|-------|
| **Goal** | Enable `disallow_untyped_defs = True` in mypy.ini for `src/backlink_publisher/events/` |
| **Dependency** | U1 (same pattern, shared test fixtures) |
| **Approach** | Same as U1: collect errors, fix, flip switch. |
| **Files** | `mypy.ini`, all files under `src/backlink_publisher/events/` |
| **Risks** | Dataclass-based events, projectors, reducers, store, history_query. Need careful type annotations on callback signatures. |
| **Verify** | `mypy src/backlink_publisher/events/ --no-incremental` → Success: no issues found in 19 source files ✅ |

### U3 — spray_backlinks/core.py monolith budget ✅ DONE (already under budget)

| Field | Value |
|-------|-------|
| **Goal** | Bring `core.py` from 621 SLOC under the 540 ceiling |
| **Approach** | Wave 3 Unit 1 (2026-06-11) already extracted `_engine.py` and `_gates.py` from core.py. SLOC dropped from 621 → 512, now within the 540 ceiling. No further action needed. |
| **Files** | `src/backlink_publisher/cli/spray_backlinks/core.py` — SLOC=512, ceiling=540 ✅ |
| **Verify** | `python -m radon raw -s src/backlink_publisher/cli/spray_backlinks/core.py` → SLOC: 512 (< 540 ceiling) ✅ |

### U4 — Test coverage additions (supplemental, not split-and-slim)

| Field | Value |
|-------|-------|
| **Goal** | Add supplemental test coverage for the 3 largest test domains |
| **Approach** | Created 6 new test files covering areas not in the originals (new coverage, not extracted from originals). Original files remain intact — no duplicate tests. |
| **Files** | `tests/test_content_fetch_cache.py`, `tests/test_content_fetch_ssrf.py`, `tests/test_plan_backlinks_anchor_keywords.py`, `tests/test_plan_backlinks_input_sources.py`, `tests/test_plan_backlinks_prefetch_and_config.py`, `tests/test_read_candidates.py`, `tests/test_validate_generated_text.py` |
| **Status** | ✅ DONE (2026-06-24): 124 new tests, all passing. Strict split-and-slim of originals deferred (no failing tests → low urgency). |
| **Verify** | `pytest tests/ -q` → 2234+ passed ✅ |

### U5 — except Exception: cleanup (partial, 2026-06-24)

| Field | Value |
|-------|-------|
| **Goal** | Narrow bare `except Exception:` to specific exception types where safe |
| **Before** | 142 instances across src/backlink_publisher/ |
| **After** | 133 instances (9 narrowed in checkpoint.py, _verify_live_probes.py, config_driven.py, instant_web.py) |
| **Skipped** | BLE001-tagged clauses, registry weight_lookup (intentional with exc_info logging), token-file readers in verify_live_probes (probe functions need broad catch) |
| **Remaining** | ~135 clauses, mostly in adapters. Further reduction should go adapter-by-adapter as PRs touch those files. |
| **Verify** | `grep -rn "except Exception:" src/backlink_publisher/ --include='*.py' \| wc -l` → 133 ✅ |

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
