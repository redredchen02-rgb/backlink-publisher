---
title: "feat: Core upgrade — complete R4–R10 (verify, archive, demote)"
type: feat
status: completed
date: 2026-06-10
origin: docs/brainstorms/2026-06-05-core-upgrade-prove-and-prune-requirements.md
claims: {}
---

# Core upgrade: complete R4–R10

## Overview

This plan completes the remaining scope (R4–R10) from the [core-upgrade-prove-and-prune plan](https://github.com/backlink-publisher/docs/plans-archive/2026-06-05-008-feat-core-upgrade-prove-and-prune-plan.md) (R1–R3 already shipped).

**Critical discovery during planning:** R4–R8 are **substantially or fully implemented already** — the codebase already contains the recheck CLI + launchd schedule, the survival dashboard route + template + cohort query, the per-target dofollow badge template + CSS, and the real-credential e2e test fixtures + 3 test files. The remaining work is:

1. **Integration verification** — confirm R4–R6 actually work end-to-end (exercised tests + manual WebUI walkthrough)
2. **Remove `--probe` dry‑run gate** — make the weekly recheck switchable from dry‑run to real probing
3. **R9** — archive off‑narrative brainstorms (the only genuine greenfield work)
4. **R10** — move Perplexity to optional extra in `pyproject.toml`

## Requirements Trace

| Unit | Status | Remaining work |
|---|---|---|
| R4 (weekly recheck) | Scaffolded — CLI, plist, 11 test files | Verify integration; make `--probe` gate toggleable |
| R5 (survival dashboard) | Built — route, service, template, cohort query | Verify integration (render test + manual walkthrough) |
| R6 (per‑target dofollow badge) | Built — template lines 258–269, CSS lines 652–668 | Verify data flow from `link.rechecked` → badge render |
| R7+R8 (real‑credential e2e) | Scaffolded — 3 test files + fixtures | Run live half (operator‑local); harden fixture‑scrub guard |
| R9 (archive brainstorms) | **Not done** — 30 brainstorms, no archive dir | Determine keep‑set; `git mv` complement to `docs/_archive/brainstorms/` |
| R10 (demote peripherals) | Partially done — AGENTS.md section exists | Move Perplexity to optional extra in `pyproject.toml` |

## Context & Research

### R4 — Weekly recheck (existing architecture)

- `src/backlink_publisher/cli/recheck_backlinks.py` (331 lines): CLI entrypoint with `--probe` gate. Without `--probe` it runs a zero‑network dry preview.
- `src/backlink_publisher/recheck/probe.py`: `probe_liveness()` — shared primitive used by both CLI and WebUI (`services/recheck.py`)
- `src/backlink_publisher/recheck/selection.py`: age‑cursor selection (`DEFAULT_CAP=50`, `DEFAULT_DAYS=14`, `MIN_RETRY=1`)
- `src/backlink_publisher/recheck/events_io.py`: `emit_recheck()` + `write_verified_at()` + `derive_decay_counts()`
- `scripts/com.dex.bp-recheck.plist`: weekly Monday 04:30 schedule (already uses `StartCalendarInterval`)
- `scripts/run-recheck-periodic.sh`: shell wrapper (supports `--probe` + `PROBE=1` env)
- 11 test files under `tests/test_recheck_*.py`

**What remains:**
- Replace `--probe` default (`False` → `True`) or add an env‑var toggle for production switching
- Verify `--limit` covers "all due links within budget" (cap vs selection logic)
- Integration test: plist → shell → CLI → `link.rechecked` events

### R5 — Survival dashboard (existing architecture)

- `webui_app/routes/survival_dashboard.py` (38 lines): Blueprint, registered in `routes/__init__.py` line 43/57
- `webui_app/services/survival.py` (59 lines): `build_survival_view()` injectable presenter
- `webui_app/templates/survival_dashboard.html` (60 lines): extends `base.html`, survival‑rate headline + sample size
- `src/backlink_publisher/events/survival_query.py` (206 lines): `compute_survival()` cohort query — 30‑day maturity, `MIN_COHORT_N=2`, `_EXCLUDED_HOSTS={"example.com"}`
- Route test at `tests/test_webui_service_routes.py::test_get_survival_dashboard_page`

**What remains:**
- Verify the data path: `publish.confirmed` → `link.rechecked` → `compute_survival()` → template render
- Manual walkthrough: navigate `/survival-dashboard` in WebUI, confirm states (empty / insufficient / with data)
- Edge case: verify `MATURITY_DAYS=30` and `MIN_COHORT_N=2` guard work correctly with real event data

### R6 — Per‑target dofollow badge (existing architecture)

- `webui_app/templates/_tab_history.html` lines 258–269: renders badge with 4 states (`dofollow` green, `dofollow_lost` amber, `stripped` red, `unverified` amber)
- `webui_app/static/css/index.css` lines 652–668: `.target-dofollow-badge` + `.target-badge.nofollow`
- Data source: `item.target_dofollow` derived from latest `link.rechecked` verdict in `history_query.py`
- Integration test: `tests/test_history_recheck.py`

**What remains:**
- Verify the data flow: `history_query.py` joins latest `LINK_RECHECKED` per `article_id` → `item['target_dofollow']` → template renders correct badge
- Manual walkthrough: open history tab on a row with `link.rechecked` data, confirm badge matches verdict

### R7+R8 — Real‑credential e2e (existing architecture)

- `tests/test_e2e_live_publish_ratio.py` (235 lines): scrubbed‑replay half (CI) + live half (operator‑local, env‑gated)
- `tests/test_live_publish_fixtures_scrubbed.py` (101 lines): fixture‑scrub security guard
- `tests/test_live_publish_real.py` (68 lines): operator‑local live half, gated behind `BACKLINK_PUBLISHER_REAL_LIVE_PUBLISH=1`
- `tests/fixtures/live_publish/`: `medium_recorded.json`, `blogger_recorded.json`, `*_dofollow.html`, `*_nofollow.html`, `*_rewritten.html`
- `real_live_publish` marker registered in `pyproject.toml`

**What remains:**
- Run live half once against operator's non‑author account(s)
- Harden fixture‑scrub guard: verify `_MAX_SCRUB_LEN` check, `Set-Cookie`/`Authorization` pattern rejection
- Verify scrubbed‑replay half passes in CI

### R9 — Archive brainstorms (remaining work)

- 30 `.md` files in `docs/brainstorms/` (plus `_drafts/` with 3 files)
- No archive directory exists
- Per the origin plan: keep‑set = active plans' origin/topic brainstorms + adapter‑related topics + core narrative
- Plan 003 (`ai-engine-empowerment`) has no `source_brainstorm`/`origin` frontmatter — manual decision needed

**What remains:**
- Determine keep‑set: derive from `grep -rl '^status: active' docs/plans/` and trace each plan's `origin:`/`source_brainstorm:` frontmatter
- Create `docs/_archive/brainstorms/` matching the existing `docs/_archive/plans/` precedent
- `git mv` complement — never delete, only move

### R10 — Demote peripherals (remaining work)

- AGENTS.md already has "Peripheral / meta modules" section (correct)
- Perplexity not yet moved to optional extra in `pyproject.toml`
- 4 entrypoints (`probe-citations`, `pr-opportunities`, `click-track`, `debt-report`) — all kept per zero‑breakage baseline

**What remains:**
- Add `[project.optional-dependencies] perplexity = ["perplexity-cli>=…"]` in `pyproject.toml`
- Keep entrypoints (verified: `test_no_orphan_code.py` stays green without allowlist churn)

## Key Technical Decisions

1. **No code changes to existing R4–R6 implementations** — integration verification confirms they work; only the `--probe` gate toggle needs a one‑line change.
2. **R4 `--probe` gate → env‑variable toggle**: add `RECHECK_PROBE=1` env var to the plist's `EnvironmentVariables` (leave the CLI default `action='store_true'` so `--probe` still works for manual runs; the plist provides the env var to switch from dry‑preview to live).
3. **R9 archive dir = `docs/_archive/brainstorms/`** — matches `docs/_archive/plans/` precedent (deliberate deviation from "`docs/brainstorms/_archive/`" so globs like `docs/brainstorms/*.md` naturally exclude archived ones).
4. **R10 zero‑breakage**: keep all 4 entrypoints in `[project.scripts]`; only add Perplexity optional extra; AGENTS.md already correct.

## Implementation Units

### Unit V1: Integration verification (R4–R6)

**Goal:** Confirm the existing R4–R6 implementations actually work end‑to‑end.

**Files:**
- `src/backlink_publisher/cli/recheck_backlinks.py` (read, no change)
- `webui_app/routes/survival_dashboard.py` (read, no change)
- `webui_app/templates/_tab_history.html` (read, no change)
- `src/backlink_publisher/events/survival_query.py` (read, no change)

**Verification script (run once, not committed):**
```bash
# 1. Seed a publish.confirmed event via test fixture
python -c "
from backlink_publisher.events.store import EventStore
from backlink_publisher.events.kinds import PUBLISH_CONFIRMED
s = EventStore('/tmp/test-events.db')
s.append(PUBLISH_CONFIRMED, {'article_id':'t1','platform':'blogger','target_url':'https://example.com/p1'})
"
# 2. Run recheck dry preview (no network)
recheck-backlinks
# 3. Check events were written
python -c "
from backlink_publisher.events.store import EventStore
s = EventStore('/tmp/test-events.db')
for e in s.stream('link.rechecked'): print(e)
"
# 4. Start WebUI and manually navigate /survival-dashboard
# 5. Check history tab for badge rendering on seeded row
```

**Note:** Steps 3–5 require a running WebUI with the test event store; formal integration test to be determined.

**Success criteria:** R4 dry preview emits `link.rechecked` events; R5 dashboard renders without 500; R6 badge shows correct verdict for seeded data.

---

### Unit V2: Enable R4 live probing

**Goal:** Make the weekly recheck actually probe (not dry‑run) by adding an env‑var toggle in the plist.

**Files:**
- Modify: `scripts/com.dex.bp-recheck.plist` — add `RECHECK_PROBE=1` to `EnvironmentVariables`
- Optionally modify: `scripts/run-recheck-periodic.sh` — pass `--probe` when `PROBE=1` (already supported per code inspection)

**Approach:** The plist currently starts `run-recheck-periodic.sh` which invokes `recheck-backlinks`. Adding `RECHECK_PROBE=1` to the plist's environment and making the shell wrapper translate it to `--probe` is the minimal change. Alternatively, the CLI itself could read the env var — but changing the plist env is the safer path (revert by removing the env line).

**Test:** Add `--probe` to the existing plist content test so the expected command line includes it.
- Test file: `tests/test_recheck_periodic_schedule.py`

**Success criteria:** After reinstall, the weekly job probes live; operator can revert by editing the plist.

---

### Unit V3: R9 — Archive brainstorms

**Goal:** Reduce active brainstorms to the core few that feed the main narrative.

**Files:**
- Create: `docs/_archive/brainstorms/` (new directory)
- Move: `git mv docs/brainstorms/{non‑keep} docs/_archive/brainstorms/`

**Keep‑set derivation (operator decision):**
1. Run `grep -rl '^status: active' docs/plans/` to find active plans
2. For each active plan, read its `origin:` and `source_brainstorm:` frontmatter → those brainstorms stay
3. Brainstorms whose topic is a `registered_platforms()` adapter name → stay
4. The origin brainstorm (`2026-06-05-core-upgrade-prove-and-prune-requirements.md`) → stay
5. Plan 003 (`ai-engine-empowerment`) has no `source_brainstorm`/`origin` — **operator decides manually**
6. Everything else → `git mv` to `docs/_archive/brainstorms/`

**Verification:**
- No active plan's `origin:`/`source_brainstorm:` points to a moved file
- `ls docs/brainstorms/*.md | wc -l` drops from ~30 to the keep‑set count
- `git status` shows only renames (no content changes)

---

### Unit V4: R10 — Perplexity optional extra

**Goal:** Move Perplexity dependency out of core install.

**Files:**
- Modify: `pyproject.toml` — add `[project.optional-dependencies] perplexity = ["perplexity-cli>=..."]`
- No changes to `AGENTS.md` (already documents peripherals correctly)
- No changes to entrypoints (keep all 4 in `[project.scripts]`)

**Approach:** If Perplexity is currently a hard dependency, move it to optional. If it's already lazy‑imported (which the AGENTS.md peripheral section suggests), the `pyproject.toml` change alone suffices. Confirm with `pip install -e .` that the package installs without Perplexity.

**Verification:**
- `pip install -e .` succeeds without Perplexity
- `pip install -e ".[perplexity]"` installs it
- `test_no_orphan_code.py` still passes (entrypoints unchanged)
- `test_r9_extension_readiness.py` still passes (registry contract untouched)

---

## Scope Boundaries

- **No** new WebUI pages/routes — the dashboard already exists
- **No** new adapters — R7/R8 uses existing medium + blogger
- **No** GA4/GSC attribution — outside scope
- **No** deleting code — archive/demote only
- **No** changes to `dispatch_weight`/`routing.py` — confirmed working from R1–R3

## Integration Points

| Flow | Components | Risk |
|---|---|---|
| R4: plist → shell → CLI → events.db | `com.dex.bp-recheck.plist` → `run-recheck-periodic.sh` → `recheck-backlinks` → `emit_recheck()` | Low — 11 test files cover unit paths |
| R5: events.db → query → template | `events.db` → `compute_survival()` → `build_survival_view()` → `survival_dashboard.html` | Low — route test exists |
| R6: events.db → history query → badge | `events.db` → `_build_history_item()` → `_tab_history.html` badge | Low — template + CSS verified present |

## Open Questions

- **R4 toggle:** env var in plist vs modifying CLI default? (Recommend: env var in plist for reversibility)
- **R9 keep‑set:** which specific brainstorms should stay? (Need operator input for plan 003's brainstorm)
- **R9 archive target:** `docs/_archive/brainstorms/` vs `docs/brainstorms/_archive/`? (Recommend: `docs/_archive/brainstorms/` to match `docs/_archive/plans/`)
- **R7/R8 live half:** which platform + account? (Confirmed operator has ≥1 non‑author account; defer account choice to R7 execution time)
- **R10 Perplexity version pin:** what's the minimum version? (Needs discovery before writing pyproject.toml)
