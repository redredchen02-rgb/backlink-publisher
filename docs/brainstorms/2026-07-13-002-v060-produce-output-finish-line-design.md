---
title: "v0.6.0 Finish-Line + Produce-Output — Design Spec"
type: design
status: active
date: 2026-07-13
author: session 8e537c86 (isolated worktree bp-v060-finish, branch feat/v060-finish-line)
supersedes_context: docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md (this scopes the *collision-free* remainder + the produce-output thread)
---

# v0.6.0 Finish-Line + Produce-Output — Design Spec

## 1. Context

The operator asked (5th "全面優化" request) to: comprehensively optimize the project, upgrade it to **v0.6.0**, plan new features, delete unused features, and make it a more powerful tool. Two routing decisions were made:

- **This session's focus** = *plan + build the v0.6.0 finish-line* (seal + new features + deletion sequencing), executing only the **collision-free** parts, because **5 concurrent AI sessions** are live in this same physical workspace (worktrees `bp-webui-phase-a`, `bp-webui-stab`, `bp-audit-fix`, `bp-wave-a`, `bp-wave-b`) and own most in-flight optimization/WebUI work.
- **"More powerful"** = *make the tool actually produce output*. The machine has **zero real publish telemetry** — the tool has apparently never produced a real dofollow backlink.

Three read-only researchers established code-verified ground truth (2026-07-13, `main` @ `a69878ca`). Key findings that reshaped the plan:

1. **"Delete unused" is largely a mirage.** Retired adapters (hashnode/writeas) and the catalog YAML channel are **intentionally kept and tested** (catalog is exercised by 8 test files) — deleting them is a *regression*. Dead code is ~zero (CI runs orphan + vulture gates). The only real deletion is ~12.5k LOC of **legacy Jinja**, which *is* plan-unit **U9**, gated behind `U4→U6→U7` + a stability window, and prerequisite-built by two active SPA sessions. → "Delete unused" becomes **"sequence U9 correctly by landing its unblocker, U4."**
2. **Produce-output is the real lever and it's collision-free.** The tool can already produce a *real dofollow backlink* via `rentry`/`telegraph` (both `dofollow=True`, **zero credentials**). "Zero runs" is friction + not-knowing, not incapability. `publishing/adapters/` is touched by **no** active branch.
3. **U11 flip-or-kill is half-built.** Diagnosis works (`canary-seed` emits a `dofollow|nofollow|ambiguous` verdict). Promotion is ~6 manual steps of hand-editing `register()` in `publishing/adapters/__init__.py` — rule **A5** forbids the *canary-seed* tool from auto-editing that file.
4. **Registry is 7 dofollow / 9 nofollow / 8 uncertain (2 retired)** — the plan doc's "9/10/10" was stale.
5. **Version is still `0.5.0`** (`pyproject.toml:7`, canonical; runtime via `importlib.metadata`). No release-seal CLI exists; release is a manual, documented checklist.

## 2. Goals / Non-Goals

**Goals**
- Ship the **collision-free** v0.6.0 finish-line units and a set of **produce-output** features that measurably lower the friction between "installed" and "first real dofollow backlink."
- Turn U11 flip-or-kill into a **one-command** promotion (respecting A5) instead of manual surgery.
- **Stage** the v0.6.0 version seal ready-to-fire (hold the trigger until the fleet's SPA branches merge, so 0.6.0 is a coherent milestone).
- Produce an **authoritative roadmap** that sequences the fleet-owned + parked units and gives the operator a "run your first real campaign" runbook.

**Non-Goals (this session)**
- No broad `frontend/` SPA page work (U5 rollout, U8 Ctrl+K palette, U9 deletion) — owned by the fleet; sequenced in the roadmap only.
- No deletion of retired adapters or the catalog channel (regression).
- No edits to `webui_app/routes/settings_basic.py` (file-collision with `opt/reachable-harm-wave-a`).
- No autonomous real external publish (operator's action; requires their accounts). F1 makes it a one-liner for them.
- No flipping the `pyproject.toml` version line yet (staged, not fired).

## 3. Design — collision-free BUILD units

### F1 — `backlink-doctor` preflight (produce-output)

**What:** a new read-only CLI, `backlink-doctor`, that inspects the operator's environment and prints the *shortest path to a first real dofollow backlink*.

**Interface:** `backlink-doctor [--json]`. Human output on stderr (guidance), machine JSONL on stdout (per the repo's stdout=JSONL / stderr=diagnostics contract, exit 0).

**Checks (all local, no network):**
- `config.toml`: is there a `[target.*].main_url` and a non-empty `anchor_keywords`/`anchor_pools` for ≥1 target? (Required by plan + publish.)
- `llm-settings.json`: present and `0o600`? (Needed for content generation at plan time.)
- Per `dofollow=True` adapter: classify credential-readiness (anon = ready now; token/oauth/live_browser = what's missing).
- Telemetry state: is `events.db`/history empty? (If so, surface "you have never run a real publish.")

**Headline output:** explicitly surfaces *"`rentry` and `telegraph` need no account — you can publish a real dofollow backlink right now: `<exact command>`"* and, for each high-value channel, the one missing prerequisite.

**Module:** `src/backlink_publisher/cli/admin/doctor.py`; register console script `backlink-doctor` in `pyproject.toml [project.scripts]`. Reuses existing config resolution (`config/…`), `app_meta.pro_status_payload()`, and `publishing.registry.registered_platforms()` — no new state.

**Collision-safe:** new module + one pyproject line; touches no fleet-owned file. (A WebUI surface is roadmap'd, *not* built here, to avoid `frontend/`.)

### F2 — `canary-flip` promotion automation (produce-output, U11)

**What:** a new CLI that turns a confirmed canary verdict into a **ready-to-apply patch**, cutting promotion from ~6 manual steps to one command.

**Interface:** `canary-flip <platform> [--from-receipt <path>|--stdin] [--apply]`.
- **Default (A5-respecting):** reads a `canary-seed` verdict receipt (JSONL), and if verdict==`dofollow`, **emits a unified diff + writes a `.patch` file** covering: (a) flip `register("<p>", …, dofollow=True)` and delete its `rationale=_R[...]` / `referral_value=` kwargs in `publishing/adapters/__init__.py`; (b) delete the `_R[...]` entry in `_nofollow_rationales.py`; (c) update the platform's row in `docs/discovery/canary-pending.md` to `flipped`; (d) scaffold a regression-test stub asserting `dofollow is True`. Operator reviews and `git apply`s.
- **`--apply` (explicit opt-in):** performs (a)–(d) as working-tree edits after printing the diff — never commits. This keeps the operator in the loop while removing the manual typing.

**Mechanism:** a small, targeted line-transform (not a full AST rewrite) anchored on the exact `register("<platform>"` call — validated by re-parsing the file with `ast` after the edit and re-running the registry import to prove the flip took. Refuses to run if the platform isn't currently `"uncertain"`, or the receipt verdict isn't `dofollow`.

**Also fixes drift:** the tool's `canary-pending.md` updater lets us correct the already-stale `hackmd`/`mataroa` rows (resolved in the registry but never marked flipped).

**Module:** `src/backlink_publisher/cli/spray/canary_flip.py` (sibling of `canary_seed.py`); console script `canary-flip`. **Collision-safe:** `publishing/adapters/` and `cli/spray/` are touched by no active branch.

**A5 note (open question, §7):** default mode never auto-edits `__init__.py`; `--apply` does so only after showing the diff and only in the working tree. Confirm this reading of A5 with the operator before enabling `--apply` by default.

### F3 — Catalog channel activation (produce-output, U11 sub-goal)

**What:** make operator-authored catalog YAMLs actually load in production, giving the "low-code channel" a real use-path and making `verify-dofollow`'s existing write-back live.

**Root cause (verified):** `adapters/__init__.py:_lazy_init()` calls `register_catalog_entries(built_in_dir=_builtin_catalog)` with **no `user_config_dir`** → default `""` → `discover_catalog_dirs` only scans the built-in dir. `user_config_dir` is passed **only in tests**. So `~/.config/backlink-publisher/catalog/*.yaml` never registers at runtime.

**Fix:** resolve the user config dir (same resolver the rest of the app uses) and pass it into `register_catalog_entries(...)` in `_lazy_init`. Preserve "hand-written adapters always win" (slug-collision skip) so the built-in `txtfyi` fixture is unaffected. Add a test proving an operator catalog YAML in the user dir registers a net-new platform in production mode.

**Explicitly NOT in scope:** adding a real new built-in catalog platform (needs a real target + live verification) → roadmap. This unit only *wires the pipe*.

**Module:** `src/backlink_publisher/publishing/adapters/__init__.py` (the `_lazy_init` call site) + a new test. **Collision-safe.**

### B1 — U4 route redirects (finish-line; unblocks U9 deletion)

**What:** 302-redirect the three remaining dual-live legacy routes to their SPA siblings, mirroring the existing `/` pattern in `routes/main.py` (`_safe_flash_redirect` → `url_for("spa.spa", subpath="…")`, legacy render moved to a `…/jinja` fallback).

- `/sites` (`routes/sites.py`) → `/app/sites`
- `/batch-campaign` (`routes/batch_campaign.py`) → `/app/batch-campaign`
- `/ce:history` (`routes/history.py`) → `/app/history`

**Precondition (plan rule K5):** verify the SPA has bulk-ops parity (bulk-publish-now / cancel / recheck / purge-failed) before redirecting the pages that expose them; if a specific bulk op is still SPA-missing, redirect the page but preserve the legacy action endpoint until parity lands (documented per-route).

**Why it matters:** these three redirects are the last of U4, and **U4 is the ordering gate for U9** (legacy retirement). Landing them is the honest form of "delete unused features" this session can safely do.

**Modules:** `webui_app/routes/{sites,batch_campaign,history}.py` + redirect tests. **Collision-safe:** no active branch edits these route files (the SPA sessions touch only `frontend/`). Minor doc-coordination with `opt/reachable-harm-wave-a` on the CLAUDE.md SPA-routes note — handle by not editing that note here.

### B2 — U13 E2E expansion (finish-line quality)

**What:** add end-to-end journeys beyond the two that exist (`publish_journey.py`, `sdk_smoke_journey.py`): a **health-console** journey, a **publish-workbench** journey, and a **pagination** journey. Wire them into `.github/workflows/e2e.yml`.

**Modules:** `tests/e2e/*.py` + `e2e.yml`. **Collision-safe:** `tests/e2e/` untouched by any active branch.

## 4. Design — staged CAPSTONE + roadmap

### S1 — v0.6.0 seal, staged (held trigger)

Prepare everything except the version-line flip:
- Draft the `CHANGELOG.md` `[0.6.0]` section content (from `[Unreleased]` + this session's adds) but keep it under `[Unreleased]` until fire.
- Write a **`docs/runbooks/seal-v0.6.0.md`** checklist: (1) confirm fleet SPA branches merged, (2) `pyproject.toml:7` + `:276` → `0.6.0`, (3) `pip install -e ".[dev]"`, (4) regenerate `openapi/backlink-api.yaml` via `scripts/gen_openapi.py`, (5) promote CHANGELOG, (6) run all gates + `make reconcile-check`, (7) `git tag v0.6.0`. Note: `frontend/package.json` stays `0.0.0`; there is no automated seal CLI (`phase0-seal` is unrelated — it's the Telegraph money-page gate).
- **Do NOT flip `pyproject.toml` version** on this branch (would leak 0.6.0 into main prematurely if merged first).

### S2 — Authoritative roadmap doc

A `docs/plans/`-style roadmap capturing: what's IN 0.6.0, what's deferred to 0.6.1 (fleet-owned U5-rollout/U8/U9), the U9 deletion sequence, U10 park status, U11 remaining manual step, and an operator **"run your first real campaign"** guide (the shortest path F1 surfaces, plus binding one high-value channel). This is the "完整規畫新功能 + 用不到的刪除功能" deliverable.

## 5. Data flow & interfaces (summary)

- F1/F2/F3 all read through existing seams: `publishing.registry.registered_platforms()`, config resolution, `_nofollow_rationales._R`, `canary-seed` receipts. No new persistent state, no new DB tables.
- F2's receipt contract = the JSONL `canary-seed` already writes to stdout (verdict, platform, anchor inspection). F2 consumes it; the two compose as a pipeline: `canary-seed <p> | canary-flip <p> --stdin`.
- Both frontends and the OpenAPI spec are untouched by F1-F3 (all CLI/backend), so no `spec.py`/`schemas.py` budget pressure from the features. B1 adds only redirects (no new endpoints).

## 6. Error handling & testing

- **Errors:** raise canonical `_util.errors` exceptions (`UsageError`/`InputValidationError`/`DependencyError`/`ExternalServiceError`). F2 refuses (UsageError) on non-uncertain platform or non-`dofollow` verdict; F1 degrades gracefully (missing config → guidance, not crash); F3 preserves slug-collision skip.
- **Tests (TDD, network autouse-blocked):**
  - F1: config-present / config-missing / anon-ready / telemetry-empty cases; JSON output shape.
  - F2: patch-emit for a dofollow verdict; refuse on nofollow/ambiguous; refuse on already-True platform; `--apply` produces a working tree that re-imports with `dofollow is True`; `canary-pending.md` row updated.
  - F3: operator catalog YAML in a temp user dir registers a net-new platform in production mode; built-in txtfyi collision still skipped.
  - B1: each route 302s to the right `/app/*`; `…/jinja` fallback still renders; bulk-op endpoints preserved where parity is pending.
  - B2: e2e journeys pass in CI harness; `e2e.yml` runs them.
- **Gates:** `ruff`, `mypy`, `test_no_monolith_regrowth`, `test_no_complexity_regrowth`. New API/complexity headroom is ample for CLI-only work; watch the CC-30 global backstop on F2's transform.

## 7. Open questions

1. **A5 interpretation for F2 `--apply`:** is a new tool editing `__init__.py` in the working tree (after printing the diff, never committing) acceptable, or must promotion stay patch-only? Default is patch-only regardless; `--apply` gated on operator confirmation.
2. **B1 bulk-ops parity:** which specific SPA bulk ops (if any) are still missing on `/app/sites` and `/app/batch-campaign` at redirect time — resolve live before redirecting (may keep a legacy action endpoint alive per K5).
3. **Seal fire trigger:** confirm the fleet SPA branches (`feat/webui-phase-a`, `fix/webui-uiux-stabilization`) have merged before firing S1.

## 8. Collision & sequencing summary

| Unit | Files | Collision | Order |
|---|---|---|---|
| F1 doctor | new `cli/admin/doctor.py`, pyproject | free | any |
| F2 canary-flip | new `cli/spray/canary_flip.py`, pyproject | free | any |
| F3 catalog wire | `adapters/__init__.py` (`_lazy_init`), new test | free | any |
| B1 redirects | `routes/{sites,batch_campaign,history}.py` | free (SPA sessions = frontend-only) | before U9 |
| B2 e2e | `tests/e2e/*`, `e2e.yml` | free | any |
| S1 seal | CHANGELOG, new runbook (NOT pyproject) | free | last; fire after fleet merge |
| S2 roadmap | new `docs/plans/*` | free | any |

All work stays in worktree `bp-v060-finish`; commits stage files by explicit name (never `git add -A`); rebase onto latest `origin/main` before any merge.
