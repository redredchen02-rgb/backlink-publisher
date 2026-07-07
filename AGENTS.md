	# AGENTS.md — backlink-publisher
	
	See `README.md` for project overview and `docs/` for plans, brainstorms, ideation, and solutions.
	
	## Dev Commands
	
	### macOS / Linux
	```bash
	# Install
	pip install -e .          # full package
	pip install -e .[dev]     # + dev deps (pytest, radon==6.0.1, etc.)
	
	# Test (PYTHONHASHSEED=0 required — set by pytest-env in pyproject.toml)
	pytest tests/
	pytest tests/test_no_monolith_regrowth.py -k "R4"   # single budget test
	pytest tests/scripts/                               # worktree script tests
	pytest -m real_ssrf_check                           # live SSRF checks (off by default)
	pytest -m real_content_fetch                        # live content fetching (module-wide in test_content_fetch.py)
	
# Lint (CI uses ruff, not Black/flake8 — P12 migration completed)
ruff check src/ webui_app/ webui_store/
	
	# SLOC measurement (for monolith budget edits)
	python -m radon raw -s src/backlink_publisher/cli/plan_backlinks/core.py  # plan_backlinks is a package; core.py is the monitored file
	
	# WebUI
	python webui.py                                    # start dev server on :8888
	scripts/launcher.command                           # canonical operator launcher (FLASK_DEBUG=0 + pinned SECRET_KEY, crash-restart loop)
	```
	
	### Windows (PowerShell 5.1+)
	```batch
	REM Install
	.venv\Scripts\python -m pip install -e .[dev]
	
	REM Test (PYTHONHASHSEED=0 set by pytest-env in pyproject.toml)
	.venv\Scripts\python -m pytest tests/
	.venv\Scripts\python -m pytest tests/test_no_monolith_regrowth.py -k "R4"
	
REM Lint (ruff, not Black/flake8)
.venv\Scripts\python -m ruff check src/ webui_app/ webui_store/
	
	REM SLOC measurement
	.venv\Scripts\python -m radon raw -s src/backlink_publisher/cli/plan_backlinks/core.py
	
	REM WebUI
	.venv\Scripts\python webui.py                                    # dev server on :8888
	powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1     # canonical operator launcher (Windows)
	```
	
	> **One launcher (R9):** On macOS, `scripts/launcher.command` is the single git-tracked launcher. On Windows, its equivalent is `scripts/launcher.ps1`. The workspace-root `启动WebUI.bat` / `restart_webui.bat` are thin entry points that should resolve to it — keep the security posture (Werkzeug debug off, pinned `SECRET_KEY`) in these files only.

## Repo Layout
	
	Workspace root (not a git repo) holds `backlink-publisher/` (canonical) and `bp-<topic>/` (`git worktree` checkouts sharing `.git/`). Edit `backlink-publisher/`, never `bp-*/`, unless on that branch.
	
	### Windows path orientation
	
	| macOS path | Windows path |
	|---|---|
	| `.venv/bin/python` | `.venv\Scripts\python.exe` |
	| `.venv/bin/activate` | `.venv\Scripts\activate` (或 `.venv\Scripts\activate.bat`) |
	| `~/.config/backlink-publisher/` | `%USERPROFILE%\.config\backlink-publisher\` |
	| `~/.cache/backlink-publisher/` | `%USERPROFILE%\.cache\backlink-publisher\` |
	| `scripts/launcher.command` | `scripts\launcher.ps1` (PowerShell) |
	| `restart_webui.sh` | `restart_webui.bat` |
	| `启动WebUI.command` | `启动WebUI.bat` |
	| `PYTHONPATH=src:${PYTHONPATH}` (冒號) | `PYTHONPATH=src;%PYTHONPATH%` (分號) |
	
	All `.bat` / `.ps1` Windows-specific files are written fresh per-platform (not git worktree symlinks). Edit the canonical file under `backlink-publisher/scripts/` — workspace-root wrappers (`.bat`, `.command`) are entry-only and should delegate to the canonical script.

### WebUI

Flask app at `webui_app/` (37 route modules, `create_app()` factory). State persistence at `webui_store/` — **11** `_LazyStore`-backed singletons total (live-recounted 2026-07-06 via `grep -rn "_LazyStore(" webui_store/*.py` — 12 matching lines, minus the docstring example in `webui_store/base.py`; supersedes the earlier "10" figure — see also `CLAUDE.md`'s WebUI Layout section for the same count and method): eight declared and exported in `webui_store/__init__.py` (`history_store`, `profiles_store`, `drafts_store`, `schedule_store`, `queue_store`, `campaign_store`, `publish_defaults_store`, `batch_ops_store`), plus `channel_status_store` (`webui_store/channel_status.py`, imported eagerly into `__init__.py`'s namespace but itself `_LazyStore`-wrapped like the rest), plus `verify_health_store` (`webui_store/verify_health.py`, never re-exported through `webui_store/__init__.py.__all__`, which is why early counts missed it), plus `error_report_store` (`webui_store/error_reports.py`, landed via `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`). Launcher: `python webui.py`.

App-level CSRF guard `_global_csrf_guard` (PR #143, `webui_app/__init__.py`) enforces a token on every POST/PUT/PATCH/DELETE. Tests opt out via `app.config['CSRF_ENABLED'] = False` (or the legacy `WTF_CSRF_ENABLED` flag — both honored). The `_check_csrf_or_abort` helper has a single production call site inside the global guard; PR #148 removed all inline per-route calls.

### Frontend — Vue 3 SPA (primary) with legacy Jinja fallback (P12 Phase 3 migration)

The primary UI is a **Vue 3 SPA** at `/app/*`, built with Vite and served by Flask (single-origin, no CORS). The SPA uses Vue Router 5 (`createWebHistory('/app/')`), Pinia stores, and `@tanstack/vue-query` for server-state caching.

**Dual-stack architecture** (strangler-fig migration):
- SPA routes: `/app/publish`, `/app/monitor`, `/app/history`, `/app/drafts`, `/app/sites`, `/app/schedule`, `/app/batch-campaign`, `/app/settings`, `/app/pr-queue` (P12), `/app/*` catch-all → 404
- Legacy Jinja pages remain at their original URLs as fallback. When a page is migrated, the Jinja route redirects to `/app/<page>` (e.g., `/settings` → `/app/settings`, `/pr-queue` → `/app/pr-queue`).
- Remaining Jinja-only pages (being migrated in P12): `health`, `equity_ledger`, `survival_dashboard`, `keep_alive`, `command_center`, `optimization_status`, `pipeline_dashboard`, `campaign_progress` (11 total at P12 start → 10 remaining after pr_queue migration)

**Build pipeline:**
```bash
cd frontend/
npm ci                              # clean install from lockfile
npm run typecheck                   # vue-tsc --noEmit (TypeScript check)
npm run test                        # vitest unit tests (jsdom)
npm run build                       # Vite production build → webui_app/spa_dist/
```
- CI runs all 4 steps via `.github/workflows/frontend.yml` on `frontend/**` changes.
- Docker multi-stage build: `frontend-builder` stage → runtime imports `spa_dist/`.
- SPA is gated by `BACKLINK_PUBLISHER_SPA` env var (default `"1"`; `"0"` disables).
- Dev server: `npm run dev` on `:5173`, proxies `/api` → Flask `:8888`.

**SPA architecture:**
- `frontend/src/router/index.ts` — route definitions (lazy-loaded via `import()`)
- `frontend/src/pages/` — per-page `.vue` components
- `frontend/src/api/` — typed API modules (Axios-based `client.ts` + domain modules)
- `frontend/src/stores/` — Pinia stores (publish, notifications, theme)
- `frontend/src/layout/` — AppShell, SideNav, TopBar, navItems
- `frontend/src/components/` — shared components (StateBlock, Toast, etc.)

**Legacy Jinja pages (not yet migrated):** follow the old patterns below. When adding a new Jinja page, prefer creating an SPA route instead.

**Legacy Jinja conventions (being phased out):**
- `templates/base.html` owns the single `<head>`: Bootstrap/Icons CDN, `<meta name="csrf-token">`, `tokens.css`
- `static/js/lib/` is the shared ESM layer: `api.js`, `dom.js`, `profiles.js`
- `static/css/tokens.css` is the single `:root` token source
- Server→client data via read-once `{% block page_data %}<script>window.__<page>Bootstrap</script>`
- No inline `on*` handlers, no cross-script `window.*` globals, no untrusted `${…}` into `innerHTML`
- `readCsrf()` reads the `<meta>` per call — never cache in a module const

JS interaction is covered by `node --test` for the pure helpers in `static/js/lib/` (`tests/js/test_lib_api.mjs`, `tests/js/test_lib_dom.mjs`, `tests/js/lib_dom_check.mjs`); page-level interaction has no framework and is verified by an adversarial manual walkthrough (silent-fail paths: velog bind, paste-to-derive, synthetic-click bind delegation). pytest covers server-rendered structure + CSRF.

### CLI entrypoints

```bash
cat seeds.jsonl | plan-backlinks | validate-backlinks | publish-backlinks --mode draft
```

| Command | Source | Role |
|---|---|---|
| `bp` | `cli/bp.py` | Show grouped overview of all CLI commands |
| `plan-backlinks` | `cli/plan_backlinks/` | Generate articles from seed JSONL |
| `validate-backlinks` | `cli/validate_backlinks.py` | Validate + enrich |
| `publish-backlinks` | `cli/publish_backlinks/` (package) | Publish via platform adapters |
| `report-anchors` | `cli/report_anchors.py` | Post-hoc anchor profile |
| `equity-ledger` | `cli/equity_ledger.py` | Per-target backlink scorecard (read-only JSONL) |
| `footprint` | `cli/footprint.py` | Link footprint analysis |
| `phase0-seal` | `cli/phase0_seal.py` | Phase0 seal operations |
| `audit-state` | `cli/audit_state.py` | Dual-state divergence auditor (read-only) |
| `preflight-targets` | `cli/preflight_targets.py` | Destination-page health check before publish |
| `cull-channels` | `cli/cull_channels.py` | Read-only channel-quality cull advisory (Blast-radius R9) |
| `channel-scorecard` | `cli/channel_scorecard.py` (engine `scorecard/engine.py`) | Read-only per-channel keep/prune scorecard (JSONL): declared registry signals (dofollow / referral_value) beside measured liveness, as a signal vector (no composite). GA4/GSC/AI value axes are `inert:not-landed` (Wave-0 DESCOPE). Also surfaced as a `/ce:health` card. Advisory; exit 0. |
| `referral-attribute` | `cli/referral_attribute.py` (engine `referral/engine.py`) | Read-only channel-level referral attribution (JSONL): reuse `click-track`'s GA4 Data API path to pull referral sessions, map each GA4 `sessionSource` → backlink channel, and append per-channel `referral.observed` events for the scorecard `referral_traffic` axis and the g3 gate. **Network gated behind `--probe` (default = zero-network dry preview).** Targets positional; `--property` required unless configured. Latest snapshot per channel wins (re-running replaces, never double-counts). Zero publish-pipeline changes (dofollow preserved). Exit 0 advisory. Plan 2026-06-15-004. |
| `canary-targets` | `cli/canary_targets.py` | Read-only adapter-contract canary: re-fetch dofollow-tier canary posts, assert target backlink still dofollow (advisory; config-driven; exit 0). Runbook: `docs/runbooks/2026-05-27-canary-targets-operations.md` |
| `plan-gap` | `cli/plan_gap.py` (engine `gap/engine.py`) | Deficit-driven re-plan (read-only, pure): reads `equity-ledger` JSONL on stdin, emits `plan-backlinks` seed JSONL fanning each under-linked target across the active dofollow platforms it lacks a live-dofollow link on. Compose: `equity-ledger \| plan-gap --desired N --language LANG \| plan-backlinks`. Suppresses stale/unverified/failed by default (loud per-reason stderr counts); exit 0 advisory. |
| `recheck-backlinks` | `cli/recheck_backlinks.py` | Post-publish survival re-probe: liveness / dofollow-drift / link-stripped over published backlinks → `link.rechecked` events + `/ce:health` decay banner. **Network gated behind `--probe` (default = zero-network dry preview).** Exit 0 by default (advisory); `--fail-on-dead` exits 6 only on deterministic dead (host_gone/link_stripped). `dofollow_lost` is advisory (cross-checked vs manifest dofollow truth, may be cloaked). Externally cron/remote-trigger driven; flock guards overlapping runs. Probe identity (preflight UA) is distinct from publish — keep recheck off the publish host's IP/cookies to avoid anti-bot reputation bleed. Runbook: `docs/operations/recheck-backlinks-runbook.md` |
| `gate-probe` | `cli/gate_probe.py` (engines `gates/*`) | Phase-0 falsification gate (read-only premise probe): `--gate g2` (money-page silent-decay), `g3` (referer render-path audit + Tier-2 GA4 referral intake; static audit alone can KILL; credentials-unavailable → BLOCKED), `g5` (footprint-fingerprint survival re-fetch; anti-bot saturation → terminal INCONCLUSIVE). Emits one `GO`/`KILL`/`INCONCLUSIVE`/`BLOCKED` verdict JSONL on stdout for hand-curation into `docs/ideation/gate-verdicts.md`. First run per gate is a calibration pass (INCONCLUSIVE → set threshold → rerun). Exit 0 advisory. Plan 2026-06-01-005. |
| `probe-citations` | `cli/probe_citations.py` (kernel `geo/run.py`) | GEO AI-citation closed-loop probe: selects stale (target, query) pairs from events.db (oldest-first, D5 cursor), queries an AI engine (Perplexity v1), classifies the answer tier (site_cited/article_cited/absent/refused), and appends `citation.observed` events. **Network gated behind `--probe` (default = zero-network dry preview).** Exit 0 by default (advisory); `--fail-on-low-share` exits 6 only for measured above-floor targets (warming_up/never_probed suppressed, D10). flock guards overlapping runs. No `--api-key` flag (S4 — key in config/env only). Plan 2026-05-29-006 Unit 7. |
| `weights` | `cli/weights.py` (subcommands `collect`/`optimize`/`show`) | Dispatch-weight optimisation, consolidating the former `collect-signals` / `optimize-weights` / `show-optimization-state` scripts (Plan 2026-06-05-008 R2). Delegates to the per-subcommand modules (still `python -m` runnable). `weights optimize` runs the rules engine incl. the floored `aggregated_stats` strip penalty (R3). |

**Maintenance contract — adding a new CLI command:** register the command in `pyproject.toml [project.scripts]` **and** add it to the matching group in `src/backlink_publisher/cli/bp.py GROUPS`. `tests/test_bp_registry.py` enforces this in CI — a missing entry fails the build.

### Peripheral / meta modules (not the core 4-stage pipeline)

The product's core is the four-stage chain **plan → validate → publish → recheck**, whose durability number is surfaced by the **survival dashboard** (`/survival-dashboard`, % of mature links still live + dofollow; Plan 2026-06-05-008 R5) and the per-target dofollow history badge (R6). The following are **peripheral/meta** surfaces — kept importable and entrypoint-backed (so `test_no_orphan_code.py` stays green), but outside the core narrative (Plan 2026-06-05-008 R10). Demote ≠ remove: the WebUI health panel and config parser lazy-import them.

| Package | Entrypoint (keeps it non-orphan) | Why peripheral |
|---|---|---|
| `geo/` | `probe-citations` | GEO AI-citation probing — an experimental measurement axis, not link publishing. |
| `pr_outreach/` | `pr-opportunities` | Manual PR-outreach opportunity surfacing — advisory, no posting. |
| `click_track/` | `click-track` | Click-tracking redirect bookkeeping — adjacent analytics, separate from dispatch. |
| `debt_report/` (`cli/debt_report.py`) | `debt-report` | Engineering-debt reporting — meta/introspection, not the publish pipeline. |

> `comment_outreach/` (`cli/comment.py` → `comment`) is **load-bearing** (the manual comment-outreach queue), not peripheral — do not demote it.

### Gate-first governance (R16, Plan 2026-06-01-005)

A "build a Phase 1–N machine" brainstorm **may not enter `/ce:plan` until its cheap falsification gate returns `GO`** in `docs/ideation/gate-verdicts.md`. Pure-read detection / probes / refactors are exempt. A `KILL` permanently parks the downstream stage; `INCONCLUSIVE` must resample (never default to GO); `BLOCKED` (Tier-2 GA4/GSC credentials unavailable) parks the stage until credentials exist. Run the gate with `gate-probe --gate <id>`. Evidence rows carry aggregate / host-stripped values — **never raw operator money-page URLs** (the no-operator-domain rule applies to `docs/ideation/`, not only `docs/solutions/`).

### Activation readiness — verify-before-activate (Plan 2026-06-17-002, Phase 0)

Before activating a "built-but-unrun" subsystem (flipping enforce mode, loading a launchd plist, scheduling a probe):

1. **The subsystem's integration tests must actually pass (green)** — not merely "have no skip marker". A *plain red* test (the #24 failure mode) blocks activation of that subsystem.
2. **A `debt:`/`reason=` ref does not unlock activation.** It keeps a red test visible in the backlog; the subsystem stays blocked until the test is green.
3. **Do not `--admin`-merge past a subsystem's red integration** to enable its activation.

Gate: run `tests/test_activation_readiness_tripwire.py` (no test file hidden) + `assert_subsystem_green(<name>)`, per `docs/runbooks/2026-06-17-activation-readiness.md`. If activation lags verification by >2 weeks, re-run first.

### Publish-path forward-path drift (Plan 2026-05-27-006)

After each publish (fresh **and** `--resume`), `publish-backlinks` records a per-platform forward-path verdict in `canary-health.json` under the `_publish_path` sibling key (disjoint from the `canary-targets` evergreen records). This is a **distinct signal** from the evergreen decay detected by `canary-targets`:

- **Evergreen decay** (`canary-targets`): the *old* seeded canary post is re-fetched to check whether its links are still dofollow. Detects that a platform *retroactively changed* live posts.
- **Forward-path drift** (publish-path canary): checks whether *newly published* posts carry the required backlinks as dofollow anchors. Detects that the current publish adapter is *already injecting nofollow* or stripping links on new posts.

In v1 both are **advisory-only** — never gate publishing, never change exit codes. The forward-path verdict is visible as a distinct "Publish-path drift monitor" card on `/ce:health`. Gating (suppress nofollow posts) and coverage for blogger/ghpages/telegraph (which need extra fetch/SSRF handling) are deferred to a follow-up plan.

### Output contract

stdout = clean JSONL; stderr = diagnostics; exit code 0 on success. No human-readable output.

### Config

`~/.config/backlink-publisher/config.toml` (override via `BACKLINK_PUBLISHER_CONFIG_DIR`). Template: `config.example.toml`.

`save_config` taxonomy (Plan 2026-05-19-010):

- (a) **Emitted every call:** `[blogger]`, `[medium]`, one `[targets."<domain>"]` per resolved domain in the kwargs/Config emit set.
- (b) **Emitted conditionally:** `[blogger.oauth]` only when at least one credential field is non-empty.
- (c) **Depth-2 subsections under managed roots not emitted on this call** (`[medium.oauth]`, `[medium.browser]`, operator-added `[targets.X]` / `[blogger.X]` / `[medium.X]`, dormant `[blogger.oauth]`) — **preserved verbatim**.
- (d) **Unmanaged top-level sections** (`[sites.*]`, `[anchor.*]`, `[anchor_alarm]`, `[llm.*]`, arbitrary operator-added tables) — preserved verbatim when carrying key=value data.
- (e) **Pure-placeholder sections** (header + comments only, no data) — never *emitted* by the writer ab initio (a fresh `save_config` of an empty `Config` produces only `[blogger]` and `[medium]`). Placeholder sections that already exist on disk are preserved verbatim by the same pass as branches (c)/(d); branch (e) is about emission, not deletion. Canary: `tests/test_save_config_section_taxonomy_canary.py`.

Note: `merge_site_url_categories` is a second writer that text-edits `[sites."<main>".url_categories]` blocks in place and does not interact with the preservation pass.

**Credential-lifecycle note (post-2026-05-19):** managed-root credential subsections (`[medium.oauth]`, `[blogger.oauth]`) now persist on save and propagate into `.config-history/` rolling snapshots (cap 20). After credential rotation, up to 20 historical copies of revoked secrets remain on disk until aged out. If `BACKLINK_PUBLISHER_CONFIG_DIR` points to synced storage (Dropbox, NFS, dotfiles repo), credentials now propagate through the sync surface — keep the config dir on local-only storage.

**Medium sidecar precedence:** when both `[medium.oauth]` in `config.toml` and the sidecar file from Plan 2026-05-18-013 are populated, `[medium.oauth]` wins. The sidecar continues to provide fallback for operators who haven't migrated.

Note: operator-archival `[targets_meta.<domain>]` blocks are preserved-only — no pipeline code reads them; treat as documentation, not a functional override.

## Import Conventions

Plan 2026-05-20-006 deleted the legacy `sys.meta_path` bridge. The old flat names (`backlink_publisher.errors`, `backlink_publisher.adapters.*`, `backlink_publisher.content_fetch`, …) **no longer resolve** — `from backlink_publisher.errors import X` now raises `ModuleNotFoundError`. Use the canonical paths:

| Subpackage | Contents |
|---|---|
| `backlink_publisher.anchor.*` | `lang`, `metrics`, `profile`, `resolver`, `scheduler`, `preflight` |
| `backlink_publisher.content.*` | `fetch`, `scraper`, `themed_gen`, `body` |
| `backlink_publisher.linkcheck.*` | `http`, `language`, `verify` |
| `backlink_publisher._util.*` | `errors`, `io`, `jsonl`, `logger`, `markdown`, `url`, `net_safety`, `secrets`, `url_derive` |
| `backlink_publisher.publishing.adapters.*` | All publisher adapters (blogger, medium, telegraph, ghpages, devto, notion, mastodon, velog, …) |

Note: `from backlink_publisher.linkcheck import check_url` still works — `linkcheck` is a real package whose `__init__.py` does `from .http import *`, independent of the deleted bridge.

## Test Patterns

Network is mocked by 4 autouse conftest fixtures (config isolated, URL checks pass, content fetch passes, sockets blocked). Test live paths with:

```bash
pytest -m real_ssrf_check        # exercise real _check_url_for_ssrf
pytest -m real_content_fetch     # exercise real verify_urls_batch (module-wide in test_content_fetch.py)
```

Test fixtures: `fixtures/seed.jsonl` (E2E, at repo root), `tests/fixtures/sloc_canary.py` (radon), `tests/fixtures/footprint_attack/` (HTML samples).

**YAML fixtures — quote SHA values always.** PyYAML int-coerces unquoted all-digit scalars (`1234567` parses as `int`, not `str`); roughly 5% of 7-char hex SHAs are all-digit and fail schema validation only on Python 3.11+ CI, not local 3.12. Use `f"    - '{sha[:7]}'\n"` when embedding short SHAs in test fixtures. Precedent: PR #98 commit `3444cb6`.

## CI (GitHub Actions)

`backlink-publisher/.github/workflows/ci.yml` triggers on push/PR to `main`. `PYTHONHASHSEED=0` set once at workflow-root `env:` level, covering every job. Five jobs as of Phase 3 Sprint C (2026-07-02):

| Job | When | Py / Node | Timeout | Notes |
|---|---|---|---|---|
| `unit` | Every push/PR | 3.11+3.12 matrix | 15 min | pip-audit (advisory, `continue-on-error`); **two-step split (C1a)**: "seam" step runs `-m "unit and seam"` with **no** `--reruns` (790/9887 tests as of 2026-07-02 — persistence/IO-heavy modules where a flake is likely a real bug must stay red), then "rest" step runs `-m "unit and not seam"` with `--reruns 2 --reruns-delay 1` (9097/9887 tests, ordinary CI flakiness is the more likely cause there); syntax validation (`py_compile` + `ast.parse` sweep, **A1** re-add); `ruff check src/ webui_app/ webui_store/`; `lint-imports`; fixture verify (`generate_fixtures.py`); `mypy src/backlink_publisher --config-file mypy.ini` (blocking, P12) |
| `integration` | PR only | 3.12 | 25 min | `-m integration`, full-suite coverage gate (`--cov-fail-under=80`) |
| `e2e` (job inside `ci.yml`) | PR only | 3.12 | 30 min | `-m e2e`, single-core (no xdist), 120s per-test timeout |
| `benchmark` (**C2**, new) | Every push/PR | 3.12 | 15 min | Runs `tests/test_benchmarks.py --benchmark-only` (`continue-on-error: true`); publishes a fixed-name `benchmark-baseline` artifact on `main` pushes; on PRs, downloads the latest main baseline and diffs via `scripts/compare_benchmarks.py --threshold-pct 20` — **advisory/warn-only end to end**, the compare script always exits 0 |
| `frontend-lint` (**C3**, new) | Every push/PR (no path filter) | Node 24 | 10 min | `cd frontend && npm ci && npx tsc --noEmit && npx vite build`. `tsc --noEmit` currently exits red on pre-existing `@types/node` gaps predating this job (tracked separately, not fixed here); `vite build` succeeds and emits `webui_app/spa_dist/`, the path Flask's `/app/*` route serves |

**Seam auto-classification (C1a):** `tests/conftest.py` AST-scans each test module's own `import` statements for the `events.`/`gap.`/`idempotency.`/`ledger.`/`webui_app.api` prefixes (`_SEAM_IMPORT_PREFIXES`) and applies `pytest.mark.seam` automatically — no manual per-file list to maintain. A small, shrink-only `_SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS` list (each entry requires a rationale comment) opts out files whose seam-module import is coincidental (e.g. reads a static constant, no runtime interaction).

Additional workflows (all path-filtered, PR-only unless noted): `frontend.yml` (SPA typecheck + vitest + build on `frontend/**` changes — narrower trigger than `ci.yml`'s `frontend-lint`, which has no path filter and skips the vitest step), `e2e.yml` (Playwright `publish-journey` E2E against a live single-origin Flask instance, triggered by `frontend/**`, `webui_app/api/v1/pipeline.py`, `webui_app/routes/spa.py`, `tests/e2e/**`), `api-contract.yml` (OpenAPI 3.1 spec drift gate + Spectral lint + oasdiff breaking-change check + Schemathesis GET-only conformance fuzz against an ephemeral credential-free instance, triggered by `openapi/**`, `webui_app/api/**`), `plan-claims-gate.yml`, `plan-claims-radar.yml`, `phase0-seal-check.yml`, `plan-redrift-gate.yml`.

**Syntax validation:** `py_compile` + `ast.parse` sweep over every tracked `.py` file, re-added as its own `unit` job step by **A1** (2026-06-30-001) — this is additive to, not a replacement for, `ruff check` (an earlier P11 note here said `ruff` "replaces" the `py_compile`/`ast.parse` check; that is no longer accurate — both run on every push/PR now).
**Linting:** `ruff check src/ webui_app/ webui_store/`.
**Type checking:** `mypy src/backlink_publisher` — **blocking** as of P12 (previously advisory with `continue-on-error`).
**Import boundaries:** `lint-imports` enforces 2 forbidden contracts: `domain → cli` and `_util → domain` (known exceptions explicitly listed).
**Monolith budgets:** `test_no_monolith_regrowth.py` (SLOC ceilings for 41 files), `test_no_complexity_regrowth.py` (CC 30 backstop). Both carry `__tier__ = "unit"` and ride the seam auto-marker mechanism above — no dedicated CI step.
**Benchmarks:** `test_no_monolith_regrowth.py`/`test_no_complexity_regrowth.py`-adjacent but distinct — see the `benchmark` job above; warn-only, never gates the build.
**Coverage:** Branch coverage, 80% fail-under floor, per-unit + full-suite JSON artifacts uploaded.

(The workspace root has no CI — it's not a git repo. All CI lives inside `backlink-publisher/.github/workflows/ci.yml` plus the sibling workflow files listed above.)

## Environment Variables

| Var | Purpose |
|---|---|
| `BACKLINK_PUBLISHER_CONFIG_DIR` | Override config dir (default `~/.config/backlink-publisher/`). Also holds `[canary.<platform>]` config (`post_url`/`expected_target`/`marker`/`hard_skip`) and the `canary-targets` health store `canary-health.json` (0o600) |
| `BACKLINK_PUBLISHER_CACHE_DIR` | Override cache dir (default `~/.cache/backlink-publisher/`) |
| `BACKLINK_LLM_API_KEY` | LLM API key for anchor generation |
| `BACKLINK_NO_FETCH_VERIFY` | Skip content fetch verification |
| `BACKLINK_GATE_CACHE_TTL_SECONDS` | Override gate cache TTL |
| `BACKLINK_PUBLISHER_ALLOW_NETWORK=1` | **No longer binds off-loopback** (LITE edition refuses non-loopback `BIND_HOST`); only disables the credential-bind endpoints while set — see README "Security posture" |
| `BACKLINK_PUBLISHER_WORKTREE_AUTOREMOVE=1` | Auto-remove stale worktrees |
| `MEDIUM_THROTTLE_MIN`, `MEDIUM_THROTTLE_MAX` | Inter-post delay (default 60-300s) |
| `OAUTHLIB_INSECURE_TRANSPORT` | Allow HTTP for OAuth loopback |
| **Platform publish delays** — Post-publish sleep before the next operation. Setting to `0` collapses the post-publish link-verification window (30 s → 10 s) and suppresses the Medium throttle adjacency guard in `_engine.py`. ||
| `DEVTO_PUBLISH_DELAY_S` | dev.to post-publish delay (default 30 s) |
| `HASHNODE_PUBLISH_DELAY_S` | Hashnode post-publish delay (default 15 s) |
| `HATENA_PUBLISH_DELAY_S` | Hatena AtomPub post-publish delay (default 30 s) |
| `LINKEDIN_PUBLISH_DELAY_S` | LinkedIn post-publish delay (default 60 s; 429s observed at < 30 s) |
| `MEDIUM_PUBLISH_DELAY_S` | Medium API + browser post-publish delay (default 30 s) |
| `NOTION_PUBLISH_DELAY_S` | Notion post-publish delay (default 30 s) |
| `QIITA_PUBLISH_DELAY_S` | Qiita post-publish delay (default 5 s) |
| `RENTRY_PUBLISH_DELAY_S` | Rentry post-publish delay (default 10 s) |
| `SUBSTACK_PUBLISH_DELAY_S` | Substack post-publish delay (default 60 s) |
| `TUMBLR_PUBLISH_DELAY_S` | Tumblr post-publish delay (default 15 s) |
| `WORDPRESSCOM_PUBLISH_DELAY_S` | WordPress.com post-publish delay (default 15 s) |
| `WRITEAS_PUBLISH_DELAY_S` | Write.as post-publish delay (default 5 s) |
| `ZENN_PUBLISH_DELAY_S` | Zenn (GitHub push) post-publish delay (default 10 s) |
| **Velog throttle** ||
| `VELOG_THROTTLE_MIN_S` | Velog inter-post jitter lower bound (default 60 s). If > `VELOG_THROTTLE_MAX_S`, both fall back to defaults. |
| `VELOG_THROTTLE_MAX_S` | Velog inter-post jitter upper bound (default 180 s). Setting equal to `VELOG_THROTTLE_MIN_S` gives deterministic fixed-interval waits. |
| **Reliability circuit breaker** — only active with `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1` (default off = transparent passthrough) ||
| `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD` | **Live trip threshold**: consecutive non-ban `ExternalServiceError` before the circuit trips (default 5). Counted in the health-store `consecutive_failures` field by `publish_with_policy`. |
| `BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD` | **Live trip threshold**: consecutive non-ban `AuthExpiredError` / session expiry before trip (default 3). |
| `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS` | ⚠️ **Dead knob (006-U1)** — read only by `circuit.trip_on_error`, which nothing on the live publish path calls; it increments a *different* counter (circuit state-file `consecutive_errors`, not the health-store `consecutive_failures` the live path uses). Setting it does nothing to live trip behavior; `policy` warns once if set. Use `…_CIRCUIT_ERROR_THRESHOLD` instead. |
| **Link-checker network** ||
| `BACKLINK_LINKCHECK_REQUEST_TIMEOUT` | HTTP request timeout for URL checks (default 10 s) |
| `BACKLINK_LINKCHECK_MAX_CONCURRENT` | Max concurrent URL check coroutines (default 10) |
| `BACKLINK_LINKCHECK_MAX_RETRIES` | Max retry attempts per URL check (default 2) |
| `BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S` | Base delay for linear backoff between retries; actual sleep = base × attempt_number (default 1 s) |
| **Content fetch network** ||
| `BACKLINK_FETCH_TIMEOUT` | HTTP timeout for content fetches (default 10 s) |
| `BACKLINK_FETCH_MAX_RETRIES` | Max retry attempts for content fetch (default 2; `0` = no retry) |
| `BACKLINK_FETCH_HEAD_SCAN_BYTES` | Max bytes read for HTML head scan (default 262144) |
| `BACKLINK_FETCH_MAX_BODY_BYTES` | Max response body bytes before truncation (default 1048576) |
| `BACKLINK_FETCH_BODY_TOO_SMALL` | Minimum body bytes to consider a page valid (default 2048) |
| `BIND_HOST` / `PORT` | WebUI address |
| `PYTHONHASHSEED=0` | Required for footprint regression tests |

## Known Quirks

- `webui_app/services/` is real and sizeable: 19 source modules spanning bind jobs (`bind_job`), browser login, recheck/keep-alive (`recheck`, `keep_alive`, `keepalive_job`), copilot advisory (`copilot_advisor`/`copilot_models`/`copilot_ranking`/`copilot_recon`), credential/oauth services (`credential_service`, `oauth_service`), health projection, settings service, survival, SEO viz, medium liveness, pipeline service, themed-content, and url-verify throttle. Earlier drafts of this doc claimed it held only 5 modules; obsolete.
- Exit code table (0-6) is a documented contract, not enforced by `sys.exit()` in CLI code
- `bp-*/AGENTS.md` are stale copies — update this file, not those
- `docs/plans/`, `docs/brainstorms/` contain real operator domain names — don't propagate to `docs/solutions/`
	- `develop` branch doesn't exist (locally or remote); CI triggers only on `branches: [main]`
	- Local branches after the 2026-07-07 branch/PR merge consolidation (round 4, `docs/plans/2026-07-07-001-...-plan.md`): `main` (active — now includes PR #83 mypy-breakage fix plus PR #85 Settings mutation error-report coverage). Round 4 found most of what round 3 had left as "presumed active WIP" had since landed via 7 other PRs (#77-#83) merged directly by their owning sessions between round 3's closeout and round 4's start — 19 branches were confirmed already-merged ancestors of `origin/main` and pruned (archive-tagged first). 2 more (`docs/u4-test-measurement`, `fix/main-mypy-breakage`) were ahead-by-commit-count but confirmed fully stale by content-diff (their distinguishing content already independently present on `origin/main`) and pruned the same way. The two W-numbered units genuinely still open (W10, W13) turned out to be already-shipped on `main` too, via a separate reintegration path (`integration/w4-w5-w10-w13-reintegrate-u5`) — except W13's Settings-card coverage, which was hand-ported from `feat/w10-cross-page-deeplink` into a fresh branch and landed as PR #85. All of `feat/w10-cross-page-deeplink`, `feat/w13-mutation-error-reporting`, `integration/2026-07-06-005-w1-w2-w4-w5-w6-w10-w12-w13-w14-w15`, and `feat/w13-settings-mutation-error-reporting` (PR #85's own source branch) were archive-tagged and pruned once their content was accounted for. **Left untouched (confirmed live-active concurrent session, not just presumed)**: `feat/w8-spa-shell-upgrade` / worktree `bp-w8-shell` — has uncommitted edits to `Icon.vue`/`SideNav.vue`/`TopBar.vue`/`navItems.ts`; do not touch without re-verifying it's actually idle first. `bp-baseline-preref` (detached HEAD, kept as a baseline reference per round 3's decision) is likewise untouched. Also untouched (pre-existing, unrelated to this round): `origin/feat/webui-console-redesign`, `origin/feat/webui-publish-workbench` (already-landed/abandoned remnants from an earlier round, out of scope here). **Round 5 correction (`docs/plans/2026-07-07-004-...-plan.md`):** the `bp-baseline-preref` worktree checkout itself no longer exists (vanished during round 5's own planning pass, with no commit or plan doc explaining the removal — likely another concurrent session's cleanup). This does not lose the baseline reference: the underlying commit `f835820e` remains reachable as an ancestor of `main` and is still tagged `pre-reconcile-local-main` (round 3's own tag, created for exactly this durability), so it stays fully restorable via `git checkout pre-reconcile-local-main` even without the dedicated worktree directory.
- `~/.config/backlink-publisher/llm-settings.json` holds the LLM `api_key`; PR #140 routed writes through `safe_write.atomic_write` so the file lands `0o600`. Files written by pre-#140 code may still be `0644` until the next save.
- `docs/architecture/deterministic-planning-principle.md` defines the architecture boundary between deterministic planning (pure, testable) and non-deterministic publishing (platform-dependent). Advisory — not CI-enforced.

## Lessons capture (dual-track)

The project keeps lessons in two places:

- **Private auto-memory** — Legacy assistant sessions may write `feedback_*.md` files into a user-private project memory directory. These are fast-capture, operator-private, and never committed.
- **Public `docs/solutions/`** — High-value or recurring lessons get *promoted* into committed markdown entries under `docs/solutions/<category>/` (categories: `best-practices/`, `developer-experience/`, `integration-issues/`, `logic-errors/`, `test-failures/`, `ui-bugs/`, `workflow-issues/`). Searchable by YAML frontmatter fields (`module`, `tags`, `problem_type`). The promotion tool is `/ce:compound`.

**Promotion = rewriting, not copy-paste. Strip UUIDs, domains, absolute paths, user-identifying quotes.** The grep gates check against patterns in `~/.local/share/backlink-publisher/private-tokens.txt` — populate this file before first use of `/ce:compound` or gates pass vacuously.

Next curation review: **2026-08-15**. Next `/ce:compound` run should scan recent `feedback_*.md` and promote what's worth keeping.

### Bugfix discipline

**Don't patch blindly.** Every bugfix runs five steps: **reproduce → identify root cause → classify → apply the smallest safe fix → leave traceable evidence.** This applies to *all* fixes — only the written depth scales (table below), never the obligation to reproduce and classify.

- **Smallest safe fix** — change only what the root cause requires. No opportunistic refactors, scope creep, or unrelated cleanups in a bugfix; a reviewer should be able to tie the diff line-by-line to the cause.
- **Classify** using the `docs/solutions/` categories listed above (`logic-errors`, `test-failures`, `integration-issues`, `ui-bugs`, `workflow-issues`, `best-practices`, `developer-experience`). The fix-time label is the same one the fix carries if promoted via `/ce:compound`.
- `/investigate` is an optional aid for the reproduce + root-cause phases — it's a generic skill, not a project command, so the contract stands without it.

| Fix size | Reproduce | Root cause | Evidence carried |
|---|---|---|---|
| One-liner / typo / rename / doc | one-line note (no test) | one sentence | inline in commit/PR body |
| Normal bug | failing test or repro steps | short paragraph | commit/PR body |

**Overlay (not a size tier):** if the bug is a regression / recurring / subtle class — a judgment call, not a function of fix size — add a failing test to the suite, write *why prior code allowed it*, and promote via `/ce:compound`. Authors self-classify, so the floor (never exempt from reproduce + classify) is the load-bearing rule; the table is guidance, not a loophole.

### Before opening a PR

- [ ] **Bugfix?** Carry repro + root cause + a `docs/solutions/` label + smallest-safe-fix rationale in the PR body — see **Bugfix discipline** above.

## Plan-doc claims contract

> **Status (2026-05-20):** Cutoff is now in effect. Any plan-doc dated `2026-05-20` or later **must** include a `claims:` block (or explicit `claims: {}` opt-out) — otherwise `plan-check` exits 8 and the `plan-claims-gate` check fails. The gate is currently a non-required check during a 14-day soak; promotion to a required status check is scheduled for **2026-06-02** (see `docs/plans/2026-05-19-010-feat-plan-claims-gate-followups-plan.md`).

Plans authored on or after **2026-05-20** must carry a `claims:` block in their YAML frontmatter declaring the repo paths and SHAs that must still be reachable from `origin/main` at merge time. The `plan-check` CLI validates the block locally; the `plan-claims-gate` and `plan-claims-radar` workflows enforce it in CI and overnight. Plans dated before 2026-05-20 are grandfathered and silently skipped.

### Authoring

Frontmatter shape:

```yaml
---
title: "feat: ..."
type: feat
status: active
date: 2026-05-20            # ISO-8601; filename prefix must match (R11b lock)
origin: docs/brainstorms/...
claims:
  paths:
    - src/backlink_publisher/foo.py
    - tests/test_foo.py
  shas:
    - 7387953                # 7..40 lowercase hex chars
---
```

Two ways to opt out of drift detection on a plan that has no code anchors (governance docs, process changes):

```yaml
claims: {}                    # explicit empty escape hatch — still passes lint
```

The schema rejects unknown keys, glob characters (`*`, `?`, `[`) in paths, mixed-case or non-hex SHAs, and a frontmatter `date:` that disagrees with the filename's `YYYY-MM-DD-NNN-` prefix (the backdate exploit).

### Running locally

```bash
plan-check docs/plans/2026-05-20-001-feat-foo-plan.md            # human output
plan-check --json docs/plans/2026-05-20-001-feat-foo-plan.md     # JSON output
```

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | pass, grandfathered, or empty-claims escape hatch |
| 1 | `UsageError` (missing/bad argument) |
| 2 | schema violation — malformed frontmatter, unknown key, glob in path, bad SHA format, filename/date mismatch |
| 7 | drift — one or more paths missing or SHAs unreachable on `origin/main` |
| 8 | post-cutoff plan with no `claims:` block |

`plan-check` emits a `RECON info fetch_head_age_seconds=<n>` line on stderr whenever it resolves claims against `origin/main` (the happy/drift paths) so freshness is visible. Grandfathered (`date < 2026-05-20`) and explicit-empty-claims (`claims: {}` or bare `claims:`) paths return silently with no stderr — they exit 0 before reaching the resolution stage. On offline fetch failure during resolution it emits `RECON warn fetch_skipped reason=<r> fetch_head_age_seconds=<n>` and still exits 0 — authoring should not be hostage to flaky networks (D16). CI never hits the skip path because its checkout step always succeeds.

### CI surfaces

- **`plan-claims-gate`** (`.github/workflows/plan-claims-gate.yml`) — runs on every PR with base `main`. Enumerates the plan-docs touched by the diff and runs `plan-check` against each. Non-required at ship; promote to required after 14 days clean (D9). Stack PRs whose base is not `main` won't fire this gate — workaround per `reference_ci_workflow_pr_filter` is `gh pr close && gh pr reopen` after rebasing onto `main`.
- **`plan-claims-radar`** (`.github/workflows/plan-claims-radar.yml`) — runs on a 09:00 UTC cron (and `workflow_dispatch`). Enumerates all post-cutoff plans, files a single rolling open issue titled `plan-claims drift radar: open since YYYY-MM-DD` summarizing the drifting plans. The radar is **never** a required check — informational only. Operator closes the issue manually after acknowledging the drift.

**No orphaned guard scripts.** A quality guard must live as a CI-executed test or workflow step — never an inert `scripts/check_*.py` that nothing runs (which gives every parallel agent false confidence). Any `scripts/check_*.py` must be referenced by a REPO_ROOT-reachable CI surface (a `.github/workflows/*.yml` workflow, a `scripts/install-*.sh` hook installer, or `.pre-commit-config.yaml`); `tests/test_no_orphaned_guard_scripts.py` enforces this and fails the build naming any unreferenced guard. Wire a guard into CI, or delete it.

### Update-plan-on-ship discipline

When an implementing PR lands, the author flips `status: active → shipped` and re-resolves the `claims:` block against post-merge `origin/main`. **Do NOT bump the `date:` field** — it stays pinned at the original authoring date, preserving grandfather status for plans that pre-date the cutoff. The R11b filename↔date lock also requires `date:` to match the filename prefix, so bumping it would break the lock.

### Status vocabulary canon

The closed set of valid `status:` tokens for `docs/plans/*.md`:

| Token | Meaning | Done-family? |
|---|---|---|
| `active` | Genuine open work — executing or ready to execute | No |
| `completed` | All units landed (canonical done head) | **Yes** |
| `shipped` | Landed-alias written by update-on-ship discipline | **Yes** |
| `parked` | Intentionally deferred — must have a written resume trigger | No |

**Done-family** (`completed` + `shipped`) = closed work that counts as converged.

**Deterministic open-work query** (anchored, avoids prose false-matches):
```bash
python3 -c "
import re, pathlib
canon = {'active','completed','shipped','parked'}
for p in sorted(pathlib.Path('docs/plans').glob('*.md')):
    m = re.search(r'^status:\s*(\S+)', p.read_text(), re.MULTILINE)
    tok = m.group(1) if m else ''
    if tok not in canon:
        print(f'OFF-CANON  {p.name}: {tok!r}')
    elif tok == 'active':
        print(f'OPEN       {p.name}')
"
```

Off-canon tokens (`done`, `complete`, `ready`, `archived`, `phase1-complete`, `partial`, `open`) are **not valid** — normalize to the canon set on discovery.

### Canonical reference

Implementation plan: `docs/plans/2026-05-19-009-feat-plan-claims-and-head-drift-gate-plan.md`.

## Worktree Cleanup

Accumulated `bp-<topic>/` worktrees can be cleaned with:

- **`bash scripts/prune-stale-worktrees.sh`** — detects worktrees merged into `origin/main` (via `gh pr list` or `merge-base`), skips dirty dirs. Flags: `--dry-run`, `--force`, `--help`. Exit 2 on failure.
- **`bash scripts/install-post-merge-hook.sh`** — installs a `post-merge` hook that notifies after `git pull` on `main`. Auto-remove via `BACKLINK_PUBLISHER_WORKTREE_AUTOREMOVE=1`.

Shared safety in `scripts/_worktree_safety.sh`. Tests: `tests/scripts/test_prune_stale_worktrees.py`.

## Monolith Budget

`monolith_budget.toml` tracks radon SLOC ceilings for **41** source/script files (authoritative list is in the TOML — the original 17 hot-path files plus every remaining 500+ raw-LOC file audited in Plan 2026-06-15-002 P1-3; when in doubt, trust the TOML). Enforced by `tests/test_no_monolith_regrowth.py` (R4 hard-fail + R7 warning canary across `src/` + the P1-3 `webui_app`/`webui_store` canary + radon version pinning). The table below lists the originally-monitored 17; the 24 P1-3 additions are all KEEP/CANDIDATE-audited and documented inline in the TOML.

| File | Ceiling |
|---|---|
| `cli/plan_backlinks/core.py` | 250 |
| `cli/publish_backlinks/__init__.py` | 240 |
| `cli/validate_backlinks.py` | 150 |
| `cli/report_anchors.py` | 120 |
| `cli/plan_check.py` | 260 |
| `cli/phase0_seal.py` | 465 |
| `cli/_publish_helpers.py` | 480 |
| `cli/generate_backlink_text.py` | 390 |
| `cli/canary_seed.py` | 230 |
| `content/fetch.py` | 250 |
| `config/writer.py` | 240 |
| `_util/markdown.py` | 240 |
| `_util/http_probe.py` | 210 |
| `events/projector.py` | 110 |
| `events/_project_reducers.py` | 620 |
| `publishing/adapters/__init__.py` | 340 |
| `scripts/platform_discovery.py` | 340 |

If a PR exceeds a ceiling, edit `monolith_budget.toml` in the same PR — raise it and add `rationale` (≥80 chars). `git blame` is the defense; no override label. Bumping `radon` (pinned `==6.0.1`) requires re-measuring all monitored ceilings + updating `SLOC_CANARY_EXPECTED` in `tests/fixtures/sloc_canary.py`.

References: `docs/plans/2026-05-18-006-feat-monolith-sloc-ceiling-plan.md`, `docs/brainstorms/2026-05-18-monolith-loc-ceiling-requirements.md`.

## Adding a new publisher adapter

Post-R9, a new platform is one `register("x", XAdapter)` call away from reaching both the CLI argparse layer and `schema.validate_publish_payload`. The dispatcher, schema enum, throttle gating, and LinkedIn-style rejection all read from `publishing.registry.registered_platforms()` — you do not edit any CLI file or `schema.py` to add a new platform.

### 1. Subclass `Publisher`

Reference: `src/backlink_publisher/publishing/adapters/blogger_api.py::BloggerAPIAdapter`.

```python
# src/backlink_publisher/publishing/adapters/yourplatform.py
from typing import Any

from backlink_publisher.config import Config
from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher.publishing.registry import Publisher
from .base import AdapterResult

class YourPlatformAdapter(Publisher):
    @classmethod
    def available(cls, config: Config) -> bool:
        return True

    def publish(self, payload: dict[str, Any], mode: str, config: Config) -> AdapterResult:
        ...
```

### 2. Implement `publish()`

- Call `extract_publish_html(payload, "yourplatform")` from `publishing.content_negotiation`
- Wrap remote calls in `retry_transient_call` from `.retry` for 429/5xx backoff
- Return `AdapterResult(status="drafted"|"published", ...)`
- Set `post_publish_delay_seconds=N` for rate-limit avoidance
- Raise `DependencyError` (falls through to next adapter) or `ExternalServiceError` (propagates immediately)

### 3. Register

Add one line to `src/backlink_publisher/publishing/adapters/__init__.py`:

```python
from .yourplatform import YourPlatformAdapter
register("yourplatform", YourPlatformAdapter, dofollow=True)
```

`dofollow=` is a **required** keyword argument (Plan 2026-05-20-009). Legal values are `True`, `False`, or `"uncertain"`. Anything other than `True` additionally requires `rationale=` of ≥80 stripped chars explaining why a non-dofollow platform is shipping (mirrors `monolith_budget.toml` rationale discipline; length-only — content is reviewer concern). The gate is enforced at import time (missing `dofollow=` raises `TypeError`) and at CI time by `tests/test_adapter_dofollow_gate.py`.

### 3b. Declare manifest metadata (Plan 2026-05-25-002)

The same `register()` call accepts four optional declarative kwargs that collapse channel-specific wiring across `binding_status.py`, `webui_app/__init__.py`, `helpers/contexts.py`, and templates into a single SSoT. Reference: the **Velog pilot** at `adapters/__init__.py` (lines starting `register("velog", ...)`).

```python
from .._manifest_types import BindDescriptor, Policy, UiMeta

register(
    "yourplatform",
    YourPlatformAdapter,
    dofollow=True,
    ui=UiMeta(
        display_name="Your Platform",         # used by inject_platforms
        domain="yourplatform.com",
        category="dev-blog",                  # or "social", "wiki", ...
        icon="bi-globe2",                     # Bootstrap icon name
    ),
    bind=[
        BindDescriptor(
            backend="token-paste",            # or "cookie", "oauth", "chrome", "cdp"
            storage_state_path="<config_dir>/yourplatform-token.json",
            login_endpoint="/api/yourplatform/login",  # if applicable
            card_template="_settings_channel_yourplatform.html",  # under webui_app/templates/
            extras={                          # escape hatch for platform-specific paths
                "browser_recipe": "backlink_publisher.publishing.browser_publish.recipes.yourplatform",
            },
        ),
    ],
    policy=Policy(
        throttle_band=(60, 180),              # tuple[int, int] seconds
        env_keys={"min": "YOURPLATFORM_THROTTLE_MIN",
                  "max": "YOURPLATFORM_THROTTLE_MAX"},
        retry_id="default",
        liveness_probe_sec=900,
        language_whitelist=("en", "ko"),      # () = no restriction
    ),
    visibility="active",                      # default; or "experimental" / "hidden" / "retired"
)
```

**Why bother**:
- `inject_platforms()` automatically picks up `display_name` from `UiMeta` (no template edit)
- `hidden_from_ui()` / `_settings_context.dashboard_channels` filter automatically via `visibility="hidden"` / `"retired"` (no second wire site)
- `tests/test_manifest_contract.py` validates the manifest shape on every CI run and prints a migration progress board

**`visibility` lifecycle**:

| state | behaviour |
|---|---|
| `"active"` | default; listed everywhere |
| `"experimental"` | opt-in only (CLI `--include-experimental`, WebUI advanced mode) |
| `"hidden"` | UI suppressed; existing bound configs still work (PR #136 write.as pattern) |
| `"retired"` | UI suppressed + `save_config` stops round-tripping its TOML sections (Unit 2b — pending) |

**All four kwargs are optional**. Omitting them is the "legacy" path — channel still registers, but won't benefit from the reverse-lookup wiring. `tests/test_manifest_contract.py` prints `legacy_platforms()` count to surface migration progress.

If the platform name appears in `publishing.registry._REJECTED_PLATFORMS` (the negative-knowledge map seeded from PR #108→#109's `devto` / `mastodon` / `wordpresscom` reverts), `register()` raises `RegistryError` at import time. Un-rejection path: delete the entry from `_REJECTED_PLATFORMS` in the same PR as the new `register()` call — the deletion diff makes the un-rejection visible to reviewers; no `accept_rejection_override` kwarg exists.

Do NOT edit:
- `cli/publish_backlinks/__init__.py` (reads `registered_platforms()` dynamically)
- `cli/plan_backlinks.py` `--default-platform` choices
- `cli/validate_backlinks.py` unsupported-platform rejection
- `schema.py` `supported_platforms()` or `reject_unsupported_platform()`

For fallback chains (like Medium's `APIAdapter → BraveAdapter → BrowserAdapter`), pass all classes in one `register()` call.

### 4. Add config (if needed)

Follow `BloggerOAuthConfig` pattern: frozen dataclass → `Config` field → TOML key → loader path → token helpers.

### 5. Add an optional dependency (if needed)

```toml
[project.optional-dependencies]
yourplatform = ["yourplatform-sdk>=2.0"]
```

### 6. Add tests

Minimum: happy-path mock test, `DependencyError` test, `ExternalServiceError` test. XSS contract test required if adding a `ROUTE_TIER_MATRIX["yourplatform"] = "a"` entry.

The R9 proof in `tests/test_r9_extension_readiness.py` already exercises cross-layer wiring — registering is sufficient to inherit it.

### PR checklist

- [ ] Adapter file under `src/backlink_publisher/publishing/adapters/`
- [ ] One-line `register(...)` in `adapters/__init__.py`
- [ ] Config dataclass / loader / TOML example (if needed)
- [ ] `pyproject.toml` optional-dependency entry (if needed)
- [ ] 3+ adapter tests (happy / DependencyError / ExternalServiceError)
- [ ] XSS contract test (if tier-`"a"` entry added)
- [ ] `README.md` Prerequisites updated
- [ ] `git diff --stat src/backlink_publisher/cli/ src/backlink_publisher/schema.py` is empty

Related: `docs/plans/2026-05-18-009-refactor-cli-extension-readiness-plan.md` (the R9 plan that made this recipe possible), `src/backlink_publisher/publishing/registry.py` (the `Publisher` ABC and dispatcher).

## Adding banner embedding to an adapter

When `Config.image_gen` is set, `plan-backlinks` produces a `banner` dict per row containing `{path, alt, mime, sha, source_url}` (the `source_url` field was added in Plan 2026-05-20-004 Unit 1 R12 so the fallback path documented below is actually reachable; rows produced before that amendment treat the missing key as `None`). To get that banner onto the platform's own CDN at publish time (so the embedded URL survives the upstream image-gen CDN's TTL), an adapter opts in by defining `embed_banner(self, artifact_path: Path, alt: str) -> str | None`. The dispatcher (`publishing.banner_dispatcher.apply`, called from `publishing.registry.dispatch` when the caller passes `banner_emit=...`) checks `hasattr(adapter, "embed_banner")` — no registration, no protocol class — and:

- Returns the platform-hosted URL on success → dispatcher prepends `![alt](platform_url)\n\n` to `payload["content_markdown"]` before `adapter.publish()` runs. Emits `banner.embedded`.
- Returns `None` → dispatcher falls back to `banner["source_url"]` (when truthy). Emits `banner.source_url_fallback` with `reason="adapter_returned_none"`. If `source_url` is also `None`/missing (b64-only provider OR pre-R12 row), the banner is silently omitted with `banner.skipped_no_artifact`.
- Raises `BannerUploadError` → handled by `config.image_gen.strict`: `false` (default) logs warn and publishes without the banner (emits `banner.failed`); `true` propagates out of `dispatch()` and the publish loop records a row-level `error_class="banner_upload"` checkpoint (the run continues with the next row, NOT exit-3 like other DependencyError families).
- Raises non-`BannerUploadError` (adapter bug) → propagates unconditionally, even when `strict=False`. Strict gating governs only banner-specific failures, never adapter implementation bugs.

Adapters that don't define `embed_banner` are handled by the same dispatcher: `source_url` is prepended via the not-opted-in branch, emitting `banner.source_url_fallback` with `reason="adapter_no_method"`. If no `source_url` either, emits `banner.skipped_no_method` and the body is unchanged.

Per-platform upload contract:
- **telegraph**: `POST https://telegra.ph/upload` with raw bytes; returns `telegra.ph/file/<sha>.<ext>` URL.
- **velog**: `image_upload_url` GraphQL mutation returns a presigned URL → PUT bytes.
- **ghpages**: commit the file to `<repo>/assets/banners/<sha>.<ext>` and return the `raw.githubusercontent.com` URL.

- **blogger**: data-URI base64 inline (probe-confirmed at Unit 3 time) or the legacy `images.insert` backdoor if still alive.

**Medium does NOT implement `embed_banner`.** All three Medium fallback adapters (`MediumAPIAdapter`, `MediumBraveAdapter`, `MediumBrowserAdapter`) omit the method so the dispatcher reaches the not-opted-in branch and prepends `![alt](source_url)`. Medium's publish-time auto-rehost then snapshots the upstream provider's CDN URL into Medium's own image hosting, yielding a Medium-hosted URL in the published post without us writing platform-specific upload logic for each Medium fallback. **Verification required at implementer time**: confirm Medium auto-rehost still works in the current year by publishing one row to a scratch Medium account and inspecting the rendered `<img src>`. If auto-rehost is dead, Medium needs its own upload path or banners must be explicitly disabled for Medium.

Error classes related to banner embedding:
- `BannerUploadError(DependencyError)` — raised by per-adapter `embed_banner` implementations on media-API failure (4xx/5xx, multipart serialization error, presign failure, etc.). NOT a credential failure; channel-status `mark_expired` must NOT fire on this exception. Strict-mode propagation lands a row-level checkpoint with `error_class="banner_upload"` — distinct from `AuthExpiredError`'s `error_class="auth_expired"`.

Reference: Plan 2026-05-20-001 Units 1-6 + Plan 2026-05-20-004 Unit 1 (this dispatcher + R12) + `src/backlink_publisher/publishing/adapters/image_gen/` for the artifact contract.

## Binding a channel

Browser-based credential binding is **orthogonal** to publisher adapters. Adding a new publish-platform follows the recipe above; teaching the platform's credential lifecycle to the operator-facing surface follows this section. Plan: `docs/plans/2026-05-19-001-feat-settings-browser-binding-plan.md`.

### Channels

The closed set lives in one place: `src/backlink_publisher/cli/_bind/channels/__init__.py::CHANNELS = frozenset({"velog", "medium", "blogger"})`. Every entry point (CLI argparse, webui routes, `AuthExpiredError` ctor, `mark_bound` / `mark_expired`) imports from there and validates membership before constructing paths or argv — defense in depth against `channel=../traversal` injection. Adding a fourth channel means: (1) extend `CHANNELS`; (2) ship its `ChannelRecipe` in `src/backlink_publisher/cli/_bind/recipes/<name>.py`; (3) update the CLI argparse `--channel` choices (auto-derived from `CHANNELS` already).

### Entry points

- `bind-channel --channel <velog|medium|blogger>` — single binding CLI, drives a headed Playwright session, emits RECON events on stdout as JSONL, writes `<config_dir>/<channel>-storage-state.json` with mode `0600`.
- `velog-login` — transparent alias for `bind-channel --channel velog`. Honored for backwards compatibility with plan-012. Prints an alias banner to stderr; otherwise identical.

Storage state always lands inside `BACKLINK_PUBLISHER_CONFIG_DIR` (defaults to `~/.config/backlink-publisher/`). The driver writes to a temp file then `os.rename`s — partial writes never leave a half-bound file. `mark_bound` happens after the rename so a kill in between leaves the file but keeps the status as `unbound` / `expired` (next click re-binds idempotently).

### Settings UI flow

`GET /settings` shows each channel card with a binding subsection (rendered from `webui_app/templates/_settings_channel_binding.html`):

- **Badge states** (rendered via `role="status" aria-live="polite"`):
  - `已绑定 ✓` — last `mark_bound` succeeded and the storage_state file still exists on disk.
  - `已过期 ⚠` — adapter raised `AuthExpiredError` at publish time, **or** `reconcile_on_load` found the storage_state file missing on app start.
  - `未绑定` — no record in `channel-status.json`.
  - `绑定中…` — JS poller saw `status: "running"` from `GET /settings/channels/<channel>/bind/<job_id>`.
- **Re-bind button** issues `POST /settings/channels/<channel>/bind` with the page CSRF token; both routes are loopback-only (`Blueprint.before_request` rejects non-`127.0.0.1`/`::1` with 403). The button writes `sessionStorage["bind:lastChannel"]` so a page reload re-opens the same card.
- **Failed binds** map their `error_code` to a Chinese operator message via `webui_app.services.bind_job.BIND_ERROR_MESSAGES` — adding a new `error_code` requires a Chinese mapping (the `tests/test_bind_error_messages.py` gate enforces this).

### Publish-time auth flip

When a publish adapter hits a 401/403 it raises `AuthExpiredError(channel="...", reason="...")` (the ctor revalidates `channel ∈ CHANNELS`). The `publish_backlinks` dispatch site catches this **before** the generic `except DependencyError`, calls `webui_store.channel_status.mark_expired(exc.channel)`, writes a checkpoint row with `error_class="auth_expired"`, then exits with code 3. Because `AuthExpiredError` inherits from `DependencyError`, callers that still `except DependencyError` keep working — they just lose the channel-specific side effects.

### Operator script — "how do I re-bind Medium?"

1. Open the WebUI (`webui` or `python webui.py`).
2. Navigate to `/settings`, expand the Medium card.
3. Click **重新绑定**. A headed Chromium window opens; complete the Medium login.
4. The badge transitions `绑定中…` → `已绑定 ✓`. The card stays open after the page reload thanks to `sessionStorage["bind:lastChannel"]`.

Alternative CLI path: `bind-channel --channel medium` (then complete login in the headed browser).

### What about Velog?

Velog is the **adapter** in plan-012 but its **credential lifecycle** lives here. plan-012 originally specified a standalone `velog-login` CLI and a `DependencyError("velog cookie expired")` raise on auth failure; plan 2026-05-19-001 unified that with the cross-channel surface. See the inline amendment in plan-012 (Unit 3 + Unit 4) for the exact contract changes.

#### Velog null-after-retry diagnostics (plan 2026-05-22-004)

When `writePost` returns `null` on both the initial attempt and the silent-drop
retry, the adapter now runs a lightweight `currentUser` liveness probe before
deciding the error class:

- **Cookie dead** (`probe_reason=no_current_user|http_4xx|probe_unreachable`) →
  `AuthExpiredError` → channel flips to expired → operator must re-bind.
- **Cookie alive** (`probe_reason=<username>`) → `ContentRejectedError` →
  row fails, batch continues, channel status unchanged. The WebUI history card
  shows an amber "内容被拒（Cookie 有效）" hint. **Do not re-bind** — inspect
  the `debug/velog-null-<article_id>.json` artifact in `config_dir` instead.

The debug artifact (0600, written by `_save_null_artifact`) contains the full
response body, response headers, and any GraphQL `errors[]` array — none of
which appear in the 200-char-truncated log that was there before this fix.

<!-- chillvibe-codex:start -->
## ChillVibe Codex

This repo uses the `chillvibe-codex` plugin.

For non-trivial software work, use `chillvibe-codex:cto` as the CTO-first main-session operating layer and treat the conversation as a factory work item.

Follow this chain:

```text
AGENTS.md -> CTO -> skills/plugins -> MCP -> authorized subagents -> scripts/gates -> memory
```

Rules:

- This `AGENTS.md` remains the repo-local source of governance.
- Use `ARCHITECTURE.md` as the repo-local architecture map for runtime boundaries, layers, entrypoints, state, and verification surfaces.
- If `PERSONA.md` exists, treat it as the repo-local human-collaboration persona overlay after `AGENTS.md`; it cannot override governance, safety, or verification gates.
- Plugin skills provide shared ChillVibe operating rules.
- Use `chillvibe-codex:cto` for context/intent analysis, work-item normalization, routing, fan-out decisions, SOP recovery, and synthesis.
- For non-trivial work, CTO must produce or preserve a preliminary analysis result before implementation planning: context, underlying problem, why/optimization target, evidence, unknowns, options, recommendation, and next step.
- Use `chillvibe-codex:autopilot` only after S0 is confirmed and CTO routes the task into the S1-S7 delivery production line.
- Large implementation work must define Commit Segments before execution: planned commit title, included scope, excluded scope, write boundary, verification, artifact links, and stop conditions.
- Stage advancement requires explicit validation, not hooks/rules/subagent text.
- Every non-trivial completed work item must follow `references/contracts/completion-report-contract.md` and end with a Traditional Chinese Completion Report that covers target, status, completed work, evidence, gaps/risks, current repo/plugin/SOP state, Memory Delta, next-step options, and CTO recommendation. When implementation or verification happened, report the current implementation state, user scenario, behavior/file-scope differences, risks, evidence, and next step directly in chat; SDD files are supporting detail, not a substitute.
<!-- chillvibe-codex:end -->
