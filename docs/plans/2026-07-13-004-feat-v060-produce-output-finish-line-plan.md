---
title: "feat: v0.6.0 finish-line + produce-output implementation plan"
type: feature
status: active
date: 2026-07-13
claims: {}  # unmerged feature branch feat/v060-finish-line; claims.paths validate against origin/main, so kept empty until merge (per plan-check gotcha)
spec: docs/brainstorms/2026-07-13-002-v060-produce-output-finish-line-design.md
---

# v0.6.0 Finish-Line + Produce-Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the collision-free v0.6.0 finish-line units plus produce-output features that lower the friction between "installed" and "first real dofollow backlink," and stage the version seal ready-to-fire.

**Architecture:** Five collision-free units — F1 `backlink-doctor` preflight CLI, F2 `canary-flip` promotion automation (completes U11), F3 catalog user-dir activation, B1 U4 route redirects (unblocks U9 deletion), B2 e2e expansion — plus S1 staged seal (no version flip yet) and S2 roadmap doc. All CLI/backend/test; no `frontend/` edits; all in worktree `bp-v060-finish` on branch `feat/v060-finish-line`.

**Tech Stack:** Python ≥3.11, argparse CLIs (`[project.scripts]`), Flask blueprints (redirects), pytest (network autouse-blocked, `PYTHONHASHSEED=0`), radon complexity budgets, ruff + mypy.

## Execution Status (2026-07-13, branch `feat/v060-finish-line`)

- **F1 backlink-doctor** ✅ shipped (`9719cf50`) · **F2 canary-flip** ✅ shipped (`dd90fb3f`) · **F3 catalog activation** ✅ shipped (`bdea847c`) · **S1 staged seal** ✅ (`0ff74228`) · **S2 roadmap** ✅ (`708bddb5`) · bp-registry fix (`5a7c86d5`).
- **B1 U4 redirects** ⏸ DEFERRED — wide test blast radius (shared `conftest._fetch_csrf` + `test_r6_dofollow_badge` in the active fleet zone) + gated U9 payoff. Migration recipe in the roadmap (`docs/plans/2026-07-13-005-...`).
- **B2 E2E expansion** ⏸ DEFERRED — Playwright/chromium/built-SPA lane not verifiable in this worktree. Recipe in the roadmap.
- Verification: 2386-test targeted sweep green (adapter/registry/publishing/spray/canary/bp/webui-boot/config), ruff + mypy clean on changed source. Full suite → CI (per repo guidance).

## Global Constraints

- Edit only worktree `bp-v060-finish`; **never** `git add -A` — stage files by explicit name (shared-directory hazard). Rebase onto latest `origin/main` before any merge.
- stdout = clean JSONL; stderr = human diagnostics; exit 0 on success. Raise canonical `_util.errors` exceptions (`UsageError`=1, `InputValidationError`=2, `DependencyError`=3, `ExternalServiceError`=4).
- Adapter registry rule: adding/flipping a platform touches `publishing/adapters/__init__.py` only — **never** `cli/*.py` or `schema.py`.
- Rule **A5**: canary tooling must not *silently* rewrite `publishing/adapters/__init__.py`. F2 default = emit a reviewable patch; `--apply` is explicit opt-in that prints the diff first and never commits.
- Registry baseline (verified `main` @ a69878ca): **7 dofollow / 9 nofollow / 8 uncertain (2 retired)**. Uncertain cohort: wordpresscom, substack, txtfyi, notesio, hatena, gitlabpages, + hashnode/writeas (retired).
- Version stays **0.5.0** on this branch (`pyproject.toml:7`) — S1 stages the seal but does NOT flip it.
- Redirect pattern = `_safe_flash_redirect(url_for("spa.spa", subpath="<page>"), flash_type=…, msg=…)` + a `…/jinja` fallback route (mirror `webui_app/routes/main.py`).
- Complexity headroom (radon, measured): `spec.py` 1652/1690, `schemas.py` 603/640; CC-30 global backstop. Features are CLI/backend and add no `/api/v1` endpoints → no spec/schema budget pressure.

---

## Task 1: F3 — Catalog user-dir activation

Makes operator-authored catalog YAMLs load in production (today they load only in tests), giving the low-code channel a real use-path and making `verify-dofollow`'s write-back live.

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/__init__.py` (`_lazy_init`, ~line 420-426; `register_catalog_entries` already accepts `user_config_dir`)
- Test: `tests/test_adapter_catalog_user_dir.py` (new)

**Interfaces:**
- Consumes: `register_catalog_entries(built_in_dir: str = "", user_config_dir: str = "")` (existing, line 486); config-dir resolver (find via `grep -rn "BACKLINK_PUBLISHER_CONFIG_DIR" src/backlink_publisher/` → the canonical `resolve_config_dir()`/`_resolve_config_dir()` used elsewhere).
- Produces: production `_lazy_init()` now registers slugs found in `<config_dir>/catalog/*.yaml` that don't collide with hand-written adapters.

- [ ] **Step 1: Find the config-dir resolver.** Run `grep -rn "BACKLINK_PUBLISHER_CONFIG_DIR\|def resolve_config_dir\|def _resolve_config_dir" src/backlink_publisher/ | head`. Note the exact importable resolver (e.g. `from backlink_publisher.config....paths import resolve_config_dir`).

- [ ] **Step 2: Write the failing test.**

```python
# tests/test_adapter_catalog_user_dir.py
import textwrap
from pathlib import Path
import pytest

def test_user_catalog_yaml_registers_in_production(tmp_path, monkeypatch):
    cfg = tmp_path / "config"; (cfg / "catalog").mkdir(parents=True)
    (cfg / "catalog" / "examplepaste.yaml").write_text(textwrap.dedent("""
        slug: examplepaste
        display_name: Example Paste
        dofollow: uncertain
        rationale: "canary pending; anonymous pastebin used as a low-code channel fixture for the user-dir wiring test"
        referral_value: low
        auth_type: none
        publish:
          method: form_post
          url: https://example.test/post
          fields: {content: "{body}"}
          permalink: {strategy: redirect}
    """).strip(), encoding="utf-8")
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    # force a fresh registry init
    import importlib, backlink_publisher.publishing.adapters as A
    importlib.reload(A)
    from backlink_publisher.publishing.registry import registered_platforms
    A._lazy_init()
    assert "examplepaste" in registered_platforms()
```

(Adjust the YAML keys to match `catalog/catalog_schema.py`'s `validate_entry` — read it first: `Read src/backlink_publisher/publishing/adapters/catalog/catalog_schema.py`.)

- [ ] **Step 3: Run test to verify it fails.** `PYTHONPATH=src pytest tests/test_adapter_catalog_user_dir.py -v` → FAIL (`examplepaste` not registered, because `_lazy_init` passes no `user_config_dir`).

- [ ] **Step 4: Implement.** In `_lazy_init` (line 426), resolve the config dir and pass its `catalog` subdir:

```python
def _lazy_init() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True
    register_all_adapters()
    from <config-paths-module> import resolve_config_dir  # from Step 1
    _user_catalog = str(_Path(resolve_config_dir()) / "catalog")
    register_catalog_entries(built_in_dir=_builtin_catalog, user_config_dir=_user_catalog)
```

Keep the slug-collision skip intact (hand-written adapters win) so built-in `txtfyi` is unaffected. If `resolve_config_dir()` can raise when unset, wrap in a guard that falls back to `user_config_dir=""`.

- [ ] **Step 5: Run tests.** `PYTHONPATH=src pytest tests/test_adapter_catalog_user_dir.py tests/test_adapter_catalog_registration.py tests/test_register_all_adapters.py -v` → all PASS (built-in txtfyi still skipped; new user slug registers).

- [ ] **Step 6: Gate + commit.** `python -m ruff check src/backlink_publisher/publishing/adapters/__init__.py` and `python -m mypy src/backlink_publisher/publishing/adapters/__init__.py`.

```bash
git add src/backlink_publisher/publishing/adapters/__init__.py tests/test_adapter_catalog_user_dir.py
git commit -m "feat(catalog): load operator catalog YAMLs in production (F3, U11 sub-goal)"
```

---

## Task 2: F1 — `backlink-doctor` preflight

New read-only CLI that prints the shortest path to a first real dofollow backlink.

**Files:**
- Create: `src/backlink_publisher/cli/admin/doctor.py`
- Modify: `pyproject.toml` (`[project.scripts]` — add `backlink-doctor = "backlink_publisher.cli.admin.doctor:main"`)
- Test: `tests/test_doctor_cli.py` (new)

**Interfaces:**
- Consumes: `publishing.registry.registered_platforms()`, `dofollow_status()`, `auth_type()` (verify names via `grep -n "^def \|^    def " src/backlink_publisher/publishing/registry.py`), config loader `load_config()`, `app_meta.pro_status_payload()`.
- Produces: `main(argv: list[str] | None = None) -> None`; a pure `build_report(config, registry_view) -> dict` returning `{"ready_now": [...], "needs_config": [...], "high_value_gaps": [...], "telemetry_empty": bool, "shortest_path": str}` for testability.

- [ ] **Step 1: Write the failing test (pure report builder).**

```python
# tests/test_doctor_cli.py
from backlink_publisher.cli.admin.doctor import build_report

def test_report_surfaces_anon_dofollow_as_ready_now():
    report = build_report(config=None, registry_view=[
        {"platform": "rentry", "dofollow": True, "auth_type": "anon"},
        {"platform": "blogger", "dofollow": True, "auth_type": "oauth"},
        {"platform": "txtfyi", "dofollow": "uncertain", "auth_type": "anon"},
    ])
    assert "rentry" in report["ready_now"]
    assert "blogger" in report["high_value_gaps"]
    assert "rentry" in report["shortest_path"]  # names the zero-credential path
```

- [ ] **Step 2: Run test to verify it fails.** `PYTHONPATH=src pytest tests/test_doctor_cli.py -v` → FAIL (`No module named ...doctor`).

- [ ] **Step 3: Implement `build_report` + `main`.**

```python
# src/backlink_publisher/cli/admin/doctor.py
"""backlink-doctor — read-only preflight: shortest path to a first real dofollow backlink."""
from __future__ import annotations
import argparse, json, sys
from typing import Any

def build_report(config: Any, registry_view: list[dict]) -> dict:
    ready_now, needs_config, high_value_gaps = [], [], []
    for r in registry_view:
        if r["dofollow"] is True and r["auth_type"] == "anon":
            ready_now.append(r["platform"])
        elif r["dofollow"] is True:
            high_value_gaps.append(r["platform"])
    first = ready_now[0] if ready_now else None
    shortest = (
        f"{first} needs no account — publish a real dofollow backlink now: "
        f"plan-backlinks ... | publish-backlinks --platform {first}"
        if first else "bind one dofollow=True channel to produce your first backlink"
    )
    return {"ready_now": ready_now, "needs_config": needs_config,
            "high_value_gaps": high_value_gaps, "telemetry_empty": True,
            "shortest_path": shortest}

def _registry_view() -> list[dict]:
    import backlink_publisher.publishing.adapters  # noqa: F401 (populate registry)
    from backlink_publisher.publishing.registry import (
        registered_platforms, dofollow_status, auth_type)
    return [{"platform": p, "dofollow": dofollow_status(p), "auth_type": auth_type(p)}
            for p in registered_platforms()]

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="backlink-doctor",
        description="Read-only preflight for producing a first real dofollow backlink.")
    ap.add_argument("--json", action="store_true", help="emit machine JSON on stdout")
    args = ap.parse_args(argv)
    report = build_report(config=None, registry_view=_registry_view())
    print(json.dumps(report))  # stdout = machine
    if not args.json:
        print(f"\nShortest path: {report['shortest_path']}", file=sys.stderr)
        print(f"Ready now (no creds): {', '.join(report['ready_now']) or '(none)'}", file=sys.stderr)
        print(f"High-value, needs setup: {', '.join(report['high_value_gaps']) or '(none)'}", file=sys.stderr)
    sys.exit(0)
```

(Verify `auth_type` is a real registry function in Step 1's grep; if it's exposed differently, adapt `_registry_view`. Extend config checks — `config.toml` target/pool presence, `llm-settings.json` 0o600, real telemetry-empty detection — as follow-up steps once the pure core is green; keep each behind a tested `build_report` extension.)

- [ ] **Step 4: Run test.** `PYTHONPATH=src pytest tests/test_doctor_cli.py -v` → PASS.

- [ ] **Step 5: Register the console script.** Add to `pyproject.toml [project.scripts]` (alphabetical): `backlink-doctor = "backlink_publisher.cli.admin.doctor:main"`. Reinstall: `.venv/Scripts/python.exe -m pip install -e ".[dev]" -q`. Verify: `.venv/Scripts/backlink-doctor.exe --json` prints JSON + exits 0.

- [ ] **Step 6: Gate + commit.** ruff + mypy the new file.

```bash
git add src/backlink_publisher/cli/admin/doctor.py tests/test_doctor_cli.py pyproject.toml
git commit -m "feat(cli): backlink-doctor preflight — shortest path to first real backlink (F1)"
```

---

## Task 3: F2 — `canary-flip` promotion automation (completes U11)

Turns a confirmed canary verdict into a ready-to-apply patch (or `--apply` working-tree edit), replacing ~6 manual steps. Respects A5.

**Files:**
- Create: `src/backlink_publisher/cli/spray/canary_flip.py`
- Modify: `pyproject.toml` (`[project.scripts]` — `canary-flip = "backlink_publisher.cli.spray.canary_flip:main"`)
- Test: `tests/test_canary_flip_cli.py` (new)

**Interfaces:**
- Consumes: canary-seed receipt JSONL `{platform, verdict, post_url, rel_tokens, ...}` (verdict ∈ `dofollow|nofollow|ambiguous`); `dofollow_status(platform)` and `registered_platforms()` for eligibility; the register-block shape (multi-line `register(\n  "<p>",\n  <Adapter>,\n  dofollow="uncertain", ...\n  rationale=_R["<p>"],\n  referral_value=...,\n  **<P>_MANIFEST,\n)`).
- Produces: `main(argv)`; pure `plan_flip(source: str, rationales: str, platform: str) -> FlipEdits` returning the new `__init__.py` text + new `_nofollow_rationales.py` text (or raising `UsageError`); a `render_patch(edits) -> str` unified diff.

- [ ] **Step 1: Write the failing test (pure planner).**

```python
# tests/test_canary_flip_cli.py
import pytest
from backlink_publisher.cli.spray.canary_flip import plan_flip
from backlink_publisher._util.errors import UsageError

SRC = '''    register(
        "txtfyi",
        TxtfyiFormPostAdapter,
        dofollow="uncertain",  # R4 canary pending; Phase 0 preliminary = dofollow
        rationale=_R["txtfyi"],
        referral_value="low",  # anonymous pastebin; modest DA + R4 pending
        **TXTFYI_MANIFEST,
    )
'''
RATIONALES = '_R = {\n    "txtfyi": "some long rationale string over eighty chars ................................",\n}\n'

def test_plan_flip_sets_true_and_strips_kwargs():
    edits = plan_flip(SRC, RATIONALES, "txtfyi")
    assert 'dofollow=True' in edits.new_source
    assert 'dofollow="uncertain"' not in edits.new_source
    assert 'rationale=_R["txtfyi"]' not in edits.new_source
    assert 'referral_value=' not in edits.new_source
    assert '**TXTFYI_MANIFEST' in edits.new_source  # untouched
    assert '"txtfyi":' not in edits.new_rationales   # _R entry removed

def test_plan_flip_refuses_unknown_block():
    with pytest.raises(UsageError):
        plan_flip(SRC, RATIONALES, "notesio")  # no notesio block in SRC
```

- [ ] **Step 2: Run test to verify it fails.** `PYTHONPATH=src pytest tests/test_canary_flip_cli.py -v` → FAIL (no module).

- [ ] **Step 3: Implement the planner + CLI.** Locate the register block by scanning for a line `register(` whose following stripped line == `"<platform>",`; operate only within that block (until the line that is exactly `    )`). Within it: replace the `dofollow="uncertain", …` line with `dofollow=True,  # OUR canary <date>: dofollow confirmed`; drop lines starting with `rationale=` and `referral_value=`. Remove the `"<platform>": …` entry from `_R`. Validate with `ast.parse(new_source)` before returning; raise `UsageError` if the block isn't found or the platform isn't currently `"uncertain"`.

```python
# src/backlink_publisher/cli/spray/canary_flip.py  (core sketch)
from __future__ import annotations
import argparse, ast, json, sys, difflib
from dataclasses import dataclass
from pathlib import Path
from backlink_publisher._util.errors import UsageError

@dataclass
class FlipEdits:
    new_source: str
    new_rationales: str

def _find_block(lines: list[str], platform: str) -> tuple[int, int]:
    target = f'"{platform}",'
    for i, ln in enumerate(lines):
        if ln.strip() == "register(" and i + 1 < len(lines) and lines[i+1].strip() == target:
            for j in range(i + 1, len(lines)):
                if lines[j].rstrip() == "    )":
                    return i, j
    raise UsageError(f"canary-flip: no register(\"{platform}\", ...) block found")

def plan_flip(source: str, rationales: str, platform: str, *, date: str = "") -> FlipEdits:
    lines = source.splitlines(keepends=False)
    i, j = _find_block(lines, platform)
    out = []
    for k in range(i, j + 1):
        ln = lines[k]
        s = ln.strip()
        if s.startswith('dofollow="uncertain"'):
            stamp = f" {date}" if date else ""
            out.append(f"        dofollow=True,  # OUR canary{stamp}: dofollow confirmed")
        elif s.startswith("rationale=") or s.startswith("referral_value="):
            continue  # drop
        else:
            out.append(ln)
    if not any('dofollow=True' in x for x in out):
        raise UsageError(f"canary-flip: {platform} is not currently dofollow=\"uncertain\"")
    new_source = "\n".join(lines[:i] + out + lines[j + 1:]) + ("\n" if source.endswith("\n") else "")
    ast.parse(new_source)  # fail loudly if the edit broke syntax
    # remove the _R entry (line-based; the entry is one "<platform>": "..." line)
    r_lines = [x for x in rationales.splitlines() if not x.strip().startswith(f'"{platform}":')]
    new_rationales = "\n".join(r_lines) + ("\n" if rationales.endswith("\n") else "")
    return FlipEdits(new_source=new_source, new_rationales=new_rationales)

def render_patch(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}"))
```

The `main()` reads the receipt (`--from-receipt`/`--stdin`), refuses on verdict != `dofollow`, loads the two source files, calls `plan_flip`, and by default prints the unified diff + writes `canary-flip-<platform>.patch`; with `--apply` it writes the files in place after printing the diff (never commits). It also updates the platform row in `docs/discovery/canary-pending.md` to `flipped` in the patch/apply.

- [ ] **Step 4: Run tests.** `PYTHONPATH=src pytest tests/test_canary_flip_cli.py -v` → PASS.

- [ ] **Step 5: Round-trip guard.** Add a test that `--apply` on a temp copy yields a file that `ast.parse`s and, when imported, reports the platform as `dofollow is True`. Register the console script in `pyproject.toml`; reinstall; smoke `canary-flip txtfyi --from-receipt <fixture>` prints a diff + exits 0.

- [ ] **Step 6: Gate + commit.** ruff + mypy; confirm no CC-30 breach (`python -m radon cc -s src/backlink_publisher/cli/spray/canary_flip.py`).

```bash
git add src/backlink_publisher/cli/spray/canary_flip.py tests/test_canary_flip_cli.py pyproject.toml
git commit -m "feat(canary): canary-flip promotion automation — completes U11 flip-or-kill (F2)"
```

---

## Task 4: B1 — U4 route redirects (unblocks U9)

302-redirect the three remaining dual-live legacy routes to their SPA siblings.

**Files:**
- Modify: `webui_app/routes/sites.py`, `webui_app/routes/batch_campaign.py`, `webui_app/routes/history.py`
- Test: `tests/test_webui_u4_redirects.py` (new)

**Interfaces:**
- Consumes: `_safe_flash_redirect`, `url_for("spa.spa", subpath="<page>")`, `_render` (all from `webui_app/helpers/*`, as used in `routes/main.py`).
- Produces: bare `/sites`, `/batch-campaign`, `/ce:history` return 302 → `/app/sites|batch-campaign|history`; each gains a `…/jinja` fallback preserving the old render.

- [ ] **Step 1: Confirm SPA bulk-ops parity (K5 precondition).** `grep -rn "bulk-publish-now\|bulk-cancel\|bulk-recheck\|purge-failed" frontend/src/ webui_app/api/` — confirm the SPA pages expose the bulk ops that the legacy `/sites` / `/batch-campaign` pages offer. If a specific op is SPA-missing, keep its legacy POST action endpoint alive (redirect only the GET page render) and note it inline.

- [ ] **Step 2: Write the failing test.**

```python
# tests/test_webui_u4_redirects.py
import pytest
from webui_app import create_app

@pytest.fixture
def client():
    app = create_app(); app.config["CSRF_ENABLED"] = False
    return app.test_client()

@pytest.mark.parametrize("path,frag", [
    ("/sites", "/app/sites"),
    ("/batch-campaign", "/app/batch-campaign"),
    ("/ce:history", "/app/history"),
])
def test_legacy_route_redirects_to_spa(client, path, frag):
    resp = client.get(path)
    assert resp.status_code == 302
    assert frag in resp.headers["Location"]

def test_jinja_fallback_still_renders(client):
    assert client.get("/sites/jinja").status_code == 200
```

(Confirm the exact legacy path for history — `grep -n "route(" webui_app/routes/history.py`; it may be `/ce:history`. Match the redirect subpath to the real SPA route name in `frontend/src/router/`.)

- [ ] **Step 3: Run test to verify it fails.** `PYTHONPATH=src pytest tests/test_webui_u4_redirects.py -v` → FAIL (currently 200 render, no `/jinja`).

- [ ] **Step 4: Implement, one route at a time.** For `routes/sites.py`, mirror `main.py`: rename the existing render view to `…_jinja` at `/sites/jinja`, and add a bare `/sites` that returns `_safe_flash_redirect(url_for("spa.spa", subpath="sites"), flash_type=request.args.get("flash_type",""), msg=request.args.get("flash_msg",""))`. Preserve any POST action routes on the blueprint unchanged. Repeat for `batch_campaign.py` (`subpath="batch-campaign"`) and `history.py` (`subpath="history"`). Keep each route's blueprint name stable so `url_for` callers elsewhere don't break — run `grep -rn "url_for('sites\|url_for(\"sites" webui_app/` to catch inbound refs.

- [ ] **Step 5: Run tests.** `PYTHONPATH=src pytest tests/test_webui_u4_redirects.py -v` and the existing route tests for these three (`pytest tests/ -k "sites or batch_campaign or history" -q`) → PASS.

- [ ] **Step 6: Commit.**

```bash
git add webui_app/routes/sites.py webui_app/routes/batch_campaign.py webui_app/routes/history.py tests/test_webui_u4_redirects.py
git commit -m "feat(webui): redirect /sites /batch-campaign /ce:history to SPA (U4/B1, unblocks U9)"
```

---

## Task 5: B2 — E2E expansion (U13)

Add health-console, workbench, and pagination e2e journeys.

**Files:**
- Create: `tests/e2e/health_console_journey.py`, `tests/e2e/workbench_journey.py`, `tests/e2e/pagination_journey.py`
- Modify: `.github/workflows/e2e.yml` (run the new specs)

**Interfaces:**
- Consumes: the existing e2e harness pattern in `tests/e2e/publish_journey.py` (read it first — copy its app-boot / client fixture / assertion style exactly).

- [ ] **Step 1: Read the existing pattern.** `Read tests/e2e/publish_journey.py` and `Read .github/workflows/e2e.yml` — note how the runner invokes the journey (module entry vs pytest) and how the app is booted.

- [ ] **Step 2: Write `health_console_journey.py`** mirroring that pattern: boot app, GET `/health` (SPA) + the `/api/v1/health_dashboard` panels, assert the ~20 fail-open panels return without 500. Add `workbench_journey.py` (create operation → poll `/api/v1/operations/:id` → settle) and `pagination_journey.py` (GET `/api/v1/history?limit=2&offset=0` → assert page shape + `total`).

- [ ] **Step 3: Run locally.** Invoke each journey the same way `e2e.yml` does (e.g. `PYTHONPATH=src python tests/e2e/health_console_journey.py`) → exit 0.

- [ ] **Step 4: Wire into CI.** Add the three specs to `e2e.yml`'s run step (next to `publish_journey.py`).

- [ ] **Step 5: Commit.**

```bash
git add tests/e2e/health_console_journey.py tests/e2e/workbench_journey.py tests/e2e/pagination_journey.py .github/workflows/e2e.yml
git commit -m "test(e2e): health-console, workbench, pagination journeys (U13/B2)"
```

---

## Task 6: S1 — Stage the v0.6.0 seal (do NOT fire)

Prepare everything except the version-line flip.

**Files:**
- Create: `docs/runbooks/seal-v0.6.0.md`
- Modify: `CHANGELOG.md` (populate `[Unreleased]` with this cycle's highlights — do NOT rename to `[0.6.0]`)

**Interfaces:** none (docs only).

- [ ] **Step 1: Read `CHANGELOG.md`** — confirm the Keep-a-Changelog structure and the existing `[Unreleased]` content.

- [ ] **Step 2: Populate `[Unreleased]`** with Added: backlink-doctor, canary-flip, catalog user-dir; Changed: /sites,/batch-campaign,/ce:history redirects; Added: e2e journeys. Keep it under `[Unreleased]` (the seal runbook promotes it).

- [ ] **Step 3: Write `docs/runbooks/seal-v0.6.0.md`** — the exact fire checklist: (1) confirm `feat/webui-phase-a` + `fix/webui-uiux-stabilization` merged; (2) `pyproject.toml:7` and `:276` → `0.6.0`; (3) `.venv/Scripts/python.exe -m pip install -e ".[dev]"`; (4) `PYTHONPATH=src python scripts/gen_openapi.py` then verify `gen_openapi.py --check`; (5) promote CHANGELOG `[Unreleased]` → `[0.6.0] - <date>`, add fresh `[Unreleased]`, fix compare links; (6) full `pytest` + `ruff` + `mypy` + `make reconcile-check`; (7) `git tag v0.6.0`. Note: `frontend/package.json` stays `0.0.0`; no automated seal CLI exists.

- [ ] **Step 4: Commit.**

```bash
git add docs/runbooks/seal-v0.6.0.md CHANGELOG.md
git commit -m "docs: stage v0.6.0 seal — CHANGELOG unreleased + fire runbook (S1, held trigger)"
```

---

## Task 7: S2 — Authoritative roadmap doc

Sequences fleet-owned + parked units and gives the operator a first-real-campaign runbook.

**Files:**
- Create: `docs/plans/2026-07-13-005-v060-roadmap-and-first-campaign.md`

- [ ] **Step 1: Write the roadmap.** Sections: (a) IN v0.6.0 (this branch's units + fleet-owned U5-rollout/U8/U9 pending merge); (b) DEFERRED to 0.6.1; (c) U9 deletion sequence (`U4✓ → U6✓ → U7 → stability window → delete ~12.5k LOC legacy Jinja`, with the safe-vs-collision item list from research); (d) U10 park status + un-park trigger (real telemetry, which F1 helps produce); (e) U11 remaining manual step now collapsed by F2; (f) **operator runbook**: the F1 shortest-path, binding one high-value channel (ghpages token before browser logins), running `canary-seed`→`canary-flip` on txtfyi/notesio.

- [ ] **Step 2: Commit.**

```bash
git add docs/plans/2026-07-13-005-v060-roadmap-and-first-campaign.md
git commit -m "docs: v0.6.0 roadmap + first-real-campaign runbook (S2)"
```

---

## Self-Review

**Spec coverage:** F1→Task 2, F2→Task 3, F3→Task 1, B1→Task 4, B2→Task 5, S1→Task 6, S2→Task 7. All seven spec units mapped. Non-goals (no frontend, no adapter/catalog deletion, no version flip, no autonomous publish) encoded in Global Constraints.

**Placeholder scan:** `<config-paths-module>`, `<date>`, `<fixture>`, `<page>` are interface anchors resolved by an explicit preceding grep/read step — not silent gaps. No "TBD/TODO/add error handling."

**Type consistency:** `build_report(config, registry_view) -> dict`, `plan_flip(source, rationales, platform) -> FlipEdits`, `FlipEdits(new_source, new_rationales)`, `_safe_flash_redirect(target, flash_type=, msg=)` used consistently across tasks.

**Ordering:** Tasks 1-3 (features) and 4-5 (finish-line) are independent; 6-7 (docs) reference them. B1 (Task 4) is the U9 unblocker documented in Task 7's sequence. No cross-task type drift.
