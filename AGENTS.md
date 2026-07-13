# AGENTS.md — backlink-publisher

See `README.md` for project overview, `ARCHITECTURE.md` for the architecture map, and `docs/` for plans, brainstorms, ideation, and solutions. `CLAUDE.md` holds the auto-loaded quick reference (WebUI layout incl. the live store/service lists, import paths, budgets) — details listed there are not repeated here.

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
python serve.py                                    # production entrypoint (waitress, no dev-server warning)
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
.venv\Scripts\python serve.py                                    # production entrypoint (waitress, no dev-server warning)
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1    # canonical operator launcher (Windows)
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

Flask app at `webui_app/` (37 route modules, `create_app()` factory). State persistence at `webui_store/` — **13** `_LazyStore`-backed singleton stores as of 2026-07-13. The full enumeration, recount method (`grep -rn "_LazyStore(" webui_store/*.py`, minus the docstring example in `base.py`), and per-store gotchas live in `CLAUDE.md → WebUI Layout` — keep that section as the single source of truth for store/service counts. Launcher: `python webui.py` (dev, Werkzeug); production entrypoint: `python serve.py` (waitress, `threads=1` by default — see `serve.py`'s own docstring for why).

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
- `frontend/` source layout (router/pages/api/stores/layout/components): see `CLAUDE.md → Dual-frontend`.

**Legacy Jinja pages (not yet migrated):** follow the conventions below. When adding a new page, prefer creating an SPA route instead.

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
| `channel-scorecard` | `cli/channel_scorecard.py` (engine `scorecard/engine.py`) | Read-only per-channel keep/prune scorecard (JSONL): declared registry signals (dofollow / referral_value) beside measured liveness, as a signal vector (no composite). GA4/GSC/AI axes are `inert:not-landed` (Wave-0 DESCOPE). Surfaced as a `/ce:health` card. Advisory; exit 0. |
| `referral-attribute` | `cli/referral_attribute.py` (engine `referral/engine.py`) | Read-only channel-level referral attribution (JSONL): pulls GA4 referral sessions via `click-track`'s Data API path, maps `sessionSource` → channel, appends per-channel `referral.observed` events (feeds the scorecard `referral_traffic` axis + the g3 gate). **Network gated behind `--probe` (default = zero-network dry preview).** `--property` required unless configured. Latest snapshot per channel wins (re-running replaces, never double-counts). Exit 0 advisory. Plan 2026-06-15-004. |
| `canary-targets` | `cli/canary_targets.py` | Read-only adapter-contract canary: re-fetch dofollow-tier canary posts, assert target backlink still dofollow (advisory; config-driven; exit 0). Runbook: `docs/runbooks/2026-05-27-canary-targets-operations.md` |
| `plan-gap` | `cli/plan_gap.py` (engine `gap/engine.py`) | Deficit-driven re-plan (read-only, pure): reads `equity-ledger` JSONL on stdin, emits `plan-backlinks` seeds fanning each under-linked target across the active dofollow platforms it lacks a live-dofollow link on. Compose: `equity-ledger \| plan-gap --desired N --language LANG \| plan-backlinks`. Suppresses stale/unverified/failed by default (loud per-reason stderr counts); exit 0 advisory. |
| `recheck-backlinks` | `cli/recheck_backlinks.py` | Post-publish survival re-probe (liveness / dofollow-drift / link-stripped) → `link.rechecked` events + `/ce:health` decay banner. **Network gated behind `--probe` (default = zero-network dry preview).** Exit 0 advisory; `--fail-on-dead` exits 6 only on deterministic dead (host_gone/link_stripped); `dofollow_lost` stays advisory (cross-checked vs manifest dofollow truth, may be cloaked). Externally cron/remote-trigger driven; flock guards overlapping runs. Keep the recheck probe identity (preflight UA) off the publish host's IP/cookies — anti-bot reputation bleed. Runbook: `docs/operations/recheck-backlinks-runbook.md` |
| `gate-probe` | `cli/gate_probe.py` (engines `gates/*`) | Phase-0 falsification gate (read-only premise probe): `--gate g2` (money-page silent-decay), `g3` (referer render-path audit + Tier-2 GA4 referral intake; static audit alone can KILL; credentials-unavailable → BLOCKED), `g5` (footprint-fingerprint survival re-fetch; anti-bot saturation → terminal INCONCLUSIVE). Emits one `GO`/`KILL`/`INCONCLUSIVE`/`BLOCKED` verdict JSONL on stdout for hand-curation into `docs/ideation/gate-verdicts.md`. First run per gate is a calibration pass. Exit 0 advisory. Plan 2026-06-01-005. |
| `probe-citations` | `cli/probe_citations.py` (kernel `geo/run.py`) | GEO AI-citation closed-loop probe: selects stale (target, query) pairs from events.db (oldest-first, D5 cursor), queries an AI engine (Perplexity v1), classifies the answer tier (site_cited/article_cited/absent/refused), appends `citation.observed` events. **Network gated behind `--probe` (default = zero-network dry preview).** Exit 0 advisory; `--fail-on-low-share` exits 6 only for measured above-floor targets (warming_up/never_probed suppressed, D10). flock guards overlapping runs. No `--api-key` flag (S4 — key in config/env only). Plan 2026-05-29-006 Unit 7. |
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

After each publish (fresh **and** `--resume`), `publish-backlinks` records a per-platform forward-path verdict in `canary-health.json` under the `_publish_path` sibling key (disjoint from the `canary-targets` evergreen records). Two distinct signals: **evergreen decay** (`canary-targets`) re-fetches the *old* seeded canary post to detect platforms retroactively changing live posts; **forward-path drift** checks whether *newly published* posts carry the required backlinks as dofollow, detecting adapters already injecting nofollow or stripping links. In v1 both are **advisory-only** — never gate publishing, never change exit codes. The forward-path verdict shows as the "Publish-path drift monitor" card on `/ce:health`. Gating and blogger/ghpages/telegraph coverage (extra fetch/SSRF handling) are deferred to a follow-up plan.

### Output contract

stdout = clean JSONL; stderr = diagnostics; exit code 0 on success. No human-readable output.

### Config

`~/.config/backlink-publisher/config.toml` (override via `BACKLINK_PUBLISHER_CONFIG_DIR`). Template: `config.example.toml`.

`save_config` taxonomy (Plan 2026-05-19-010):

- (a) **Emitted every call:** `[blogger]`, `[medium]`, one `[targets."<domain>"]` per resolved domain in the kwargs/Config emit set.
- (b) **Emitted conditionally:** `[blogger.oauth]` only when at least one credential field is non-empty.
- (c) **Depth-2 subsections under managed roots not emitted on this call** (`[medium.oauth]`, `[medium.browser]`, operator-added `[targets.X]` / `[blogger.X]` / `[medium.X]`, dormant `[blogger.oauth]`) — **preserved verbatim**.
- (d) **Unmanaged top-level sections** (`[sites.*]`, `[anchor.*]`, `[anchor_alarm]`, `[llm.*]`, arbitrary operator-added tables) — preserved verbatim when carrying key=value data.
- (e) **Pure-placeholder sections** (header + comments only, no data) — never *emitted* by the writer ab initio; placeholder sections already on disk are preserved verbatim by the same pass as (c)/(d). Branch (e) is about emission, not deletion. Canary: `tests/test_save_config_section_taxonomy_canary.py`.

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
| `unit` | Every push/PR | 3.11+3.12 matrix | 15 min | pip-audit (advisory, `continue-on-error`); **two-step split (C1a)**: "seam" step runs `-m "unit and seam"` with **no** `--reruns` (persistence/IO-heavy modules where a flake is likely a real bug must stay red), then "rest" step runs `-m "unit and not seam"` with `--reruns 2 --reruns-delay 1`; syntax validation (`py_compile` + `ast.parse` sweep, **A1** re-add); `ruff check src/ webui_app/ webui_store/`; `lint-imports`; fixture verify (`generate_fixtures.py`); `mypy src/backlink_publisher` (config in `pyproject.toml [tool.mypy]`; blocking, P12) |
| `integration` | PR only | 3.12 | 25 min | `-m integration`, full-suite coverage gate (`--cov-fail-under=80`) |
| `e2e` (job inside `ci.yml`) | PR only | 3.12 | 30 min | `-m e2e`, single-core (no xdist), 120s per-test timeout |
| `benchmark` (**C2**) | Every push/PR | 3.12 | 15 min | `tests/test_benchmarks.py --benchmark-only` (`continue-on-error: true`); publishes a fixed-name `benchmark-baseline` artifact on `main` pushes; PRs diff against it via `scripts/compare_benchmarks.py --threshold-pct 20` — **advisory/warn-only end to end** |
| `frontend-lint` (**C3**) | Every push/PR (no path filter) | Node 24 | 10 min | `cd frontend && npm ci && npx tsc --noEmit && npx vite build`. `tsc --noEmit` currently exits red on pre-existing `@types/node` gaps predating this job (tracked separately); `vite build` succeeds and emits `webui_app/spa_dist/` |

**Seam auto-classification (C1a):** `tests/conftest.py` AST-scans each test module's own `import` statements for the `events.`/`gap.`/`idempotency.`/`ledger.`/`webui_app.api` prefixes (`_SEAM_IMPORT_PREFIXES`) and applies `pytest.mark.seam` automatically — no manual per-file list. A small, shrink-only `_SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS` list (each entry requires a rationale comment) opts out files whose seam-module import is coincidental.

Additional workflows (all path-filtered, PR-only unless noted): `frontend.yml` (SPA typecheck + vitest + build on `frontend/**` changes — narrower trigger than `ci.yml`'s `frontend-lint`, which has no path filter and skips vitest), `e2e.yml` (Playwright `publish-journey` E2E against a live single-origin Flask instance, triggered by `frontend/**`, `webui_app/api/v1/pipeline.py`, `webui_app/routes/spa.py`, `tests/e2e/**`), `api-contract.yml` (OpenAPI 3.1 spec drift gate + Spectral lint + oasdiff breaking-change check + Schemathesis GET-only conformance fuzz against an ephemeral credential-free instance, triggered by `openapi/**`, `webui_app/api/**`), `plan-claims-gate.yml`, `plan-claims-radar.yml`, `phase0-seal-check.yml`, `plan-redrift-gate.yml`.

**Syntax validation:** `py_compile` + `ast.parse` sweep over every tracked `.py` file (A1) — additive to `ruff check`; both run on every push/PR.
**Linting:** `ruff check src/ webui_app/ webui_store/`.
**Type checking:** `mypy src/backlink_publisher` — **blocking** as of P12.
**Import boundaries:** `lint-imports` enforces 2 forbidden contracts: `domain → cli` and `_util → domain` (known exceptions explicitly listed).
**Monolith budgets:** `test_no_monolith_regrowth.py` (SLOC ceilings) and `test_no_complexity_regrowth.py` (CC 30 backstop). Both carry `__tier__ = "unit"` and ride the seam auto-marker — no dedicated CI step.
**Coverage:** Branch coverage, 80% fail-under floor, per-unit + full-suite JSON artifacts uploaded.

(The workspace root has no CI — it's not a git repo. All CI lives inside `backlink-publisher/.github/workflows/`.)

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
| `<PLATFORM>_PUBLISH_DELAY_S` | Post-publish sleep before the next operation. Defaults (seconds): `DEVTO` 30, `HASHNODE` 15, `HATENA` 30, `LINKEDIN` 60 (429s observed at <30s), `MEDIUM` 30 (API + browser), `NOTION` 30, `QIITA` 5, `RENTRY` 10, `SUBSTACK` 60, `TUMBLR` 15, `WORDPRESSCOM` 15, `WRITEAS` 5, `ZENN` 10 (GitHub push). Setting `0` collapses the post-publish link-verification window (30 s → 10 s) and suppresses the Medium throttle adjacency guard in `_engine.py`. |
| `VELOG_THROTTLE_MIN_S` / `VELOG_THROTTLE_MAX_S` | Velog inter-post jitter bounds (defaults 60 s / 180 s). If min > max, both fall back to defaults; min == max gives deterministic fixed-interval waits. |
| **Reliability circuit breaker** — only active with `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1` (default off = transparent passthrough) ||
| `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD` | **Live trip threshold**: consecutive non-ban `ExternalServiceError` before the circuit trips (default 5). Counted in the health-store `consecutive_failures` field by `publish_with_policy`. |
| `BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD` | **Live trip threshold**: consecutive non-ban `AuthExpiredError` / session expiry before trip (default 3). |
| `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS` | ⚠️ **Dead knob (006-U1)** — read only by `circuit.trip_on_error`, which nothing on the live publish path calls; it increments a *different* counter than the live path uses. Setting it does nothing; `policy` warns once if set. Use `…_CIRCUIT_ERROR_THRESHOLD` instead. |
| `BACKLINK_LINKCHECK_REQUEST_TIMEOUT` | HTTP request timeout for URL checks (default 10 s) |
| `BACKLINK_LINKCHECK_MAX_CONCURRENT` | Max concurrent URL check coroutines (default 10) |
| `BACKLINK_LINKCHECK_MAX_RETRIES` | Max retry attempts per URL check (default 2) |
| `BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S` | Base delay for linear backoff; actual sleep = base × attempt_number (default 1 s) |
| `BACKLINK_FETCH_TIMEOUT` | HTTP timeout for content fetches (default 10 s) |
| `BACKLINK_FETCH_MAX_RETRIES` | Max retry attempts for content fetch (default 2; `0` = no retry) |
| `BACKLINK_FETCH_HEAD_SCAN_BYTES` | Max bytes read for HTML head scan (default 262144) |
| `BACKLINK_FETCH_MAX_BODY_BYTES` | Max response body bytes before truncation (default 1048576) |
| `BACKLINK_FETCH_BODY_TOO_SMALL` | Minimum body bytes to consider a page valid (default 2048) |
| `BIND_HOST` / `PORT` | WebUI address |
| `WSGI_THREADS` | `serve.py`'s waitress worker-thread count (default `1`). Keep at `1` unless the `webui_app/routes/drafts.py` bulk-publish-now single-flight gap is closed first — raising it prints a startup warning but does not block |
| `PYTHONHASHSEED=0` | Required for footprint regression tests |

## Known Quirks

- `webui_app/services/` is real and sizeable (24 modules as of 2026-07-13) — the live module list is maintained in `CLAUDE.md → WebUI Layout`.
- Exit code table (0-6) is a documented contract, not enforced by `sys.exit()` in CLI code
- `bp-*/AGENTS.md` are stale copies — update this file, not those
- `docs/plans/`, `docs/brainstorms/` contain real operator domain names — don't propagate to `docs/solutions/`
- `develop` branch doesn't exist (locally or remote); CI triggers only on `branches: [main]`
- **Branch state (post-consolidation rounds 3–5, 2026-07-07):** `main` is the only active local branch — all W-unit work landed via PRs #77–#85. **Do not touch** `feat/w8-spa-shell-upgrade` / worktree `bp-w8-shell` (confirmed live concurrent session with uncommitted edits) without re-verifying it is actually idle. Baseline reference: tag `pre-reconcile-local-main` (commit `f835820e`) — its dedicated worktree is gone but the tag keeps it restorable. Pre-existing remnants `origin/feat/webui-console-redesign` / `origin/feat/webui-publish-workbench` are out of scope. Full audit trail: `docs/archive/2026-07-13-branch-consolidation-history.md` + plans `2026-07-07-001` / `2026-07-07-004`.
- `~/.config/backlink-publisher/llm-settings.json` holds the LLM `api_key`; PR #140 routed writes through `safe_write.atomic_write` so the file lands `0o600`. Files written by pre-#140 code may still be `0644` until the next save.
- `docs/architecture/deterministic-planning-principle.md` defines the architecture boundary between deterministic planning (pure, testable) and non-deterministic publishing (platform-dependent). Advisory — not CI-enforced.

## Lessons capture (dual-track)

The project keeps lessons in two places:

- **Private auto-memory** — Legacy assistant sessions may write `feedback_*.md` files into a user-private project memory directory. Fast-capture, operator-private, never committed.
- **Public `docs/solutions/`** — High-value or recurring lessons get *promoted* into committed markdown entries under `docs/solutions/<category>/` (categories: `best-practices/`, `developer-experience/`, `integration-issues/`, `logic-errors/`, `test-failures/`, `ui-bugs/`, `workflow-issues/`). Searchable by YAML frontmatter fields (`module`, `tags`, `problem_type`). The promotion tool is `/ce:compound`.

**Promotion = rewriting, not copy-paste. Strip UUIDs, domains, absolute paths, user-identifying quotes.** The grep gates check against patterns in `~/.local/share/backlink-publisher/private-tokens.txt` — populate this file before first use of `/ce:compound` or gates pass vacuously.

Next curation review: **2026-08-15**. Next `/ce:compound` run should scan recent `feedback_*.md` and promote what's worth keeping.

### Bugfix discipline

**Don't patch blindly.** Every bugfix runs five steps: **reproduce → identify root cause → classify → apply the smallest safe fix → leave traceable evidence.** This applies to *all* fixes — only the written depth scales (table below), never the obligation to reproduce and classify.

- **Smallest safe fix** — change only what the root cause requires. No opportunistic refactors, scope creep, or unrelated cleanups in a bugfix; a reviewer should be able to tie the diff line-by-line to the cause.
- **Classify** using the `docs/solutions/` categories listed above. The fix-time label is the same one the fix carries if promoted via `/ce:compound`.
- `/investigate` is an optional aid for the reproduce + root-cause phases — a generic skill, not a project command; the contract stands without it.

| Fix size | Reproduce | Root cause | Evidence carried |
|---|---|---|---|
| One-liner / typo / rename / doc | one-line note (no test) | one sentence | inline in commit/PR body |
| Normal bug | failing test or repro steps | short paragraph | commit/PR body |

**Overlay (not a size tier):** if the bug is a regression / recurring / subtle class — a judgment call, not a function of fix size — add a failing test to the suite, write *why prior code allowed it*, and promote via `/ce:compound`. Authors self-classify, so the floor (never exempt from reproduce + classify) is the load-bearing rule; the table is guidance, not a loophole.

### Before opening a PR

- [ ] **Bugfix?** Carry repro + root cause + a `docs/solutions/` label + smallest-safe-fix rationale in the PR body — see **Bugfix discipline** above.

## Plan-doc claims contract

Cutoff in effect since **2026-05-20**: any plan-doc dated on/after that date **must** include a `claims:` block (or explicit `claims: {}` opt-out) in its YAML frontmatter — otherwise `plan-check` exits 8 and the `plan-claims-gate` check fails. Earlier plans are grandfathered and silently skipped. The `claims:` block declares the repo paths and SHAs that must still be reachable from `origin/main` at merge time; `plan-check` validates locally, `plan-claims-gate` / `plan-claims-radar` enforce in CI and overnight. (Promotion of the gate to a required status check was scheduled for 2026-06-02 — see `docs/plans/2026-05-19-010-feat-plan-claims-gate-followups-plan.md`.)

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

Opt-out for plans with no code anchors (governance docs, process changes):

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

`plan-check` emits a `RECON info fetch_head_age_seconds=<n>` line on stderr whenever it resolves claims against `origin/main`. Grandfathered and explicit-empty-claims paths return silently, exit 0, before reaching resolution. On offline fetch failure during resolution it emits `RECON warn fetch_skipped reason=<r> …` and still exits 0 — authoring should not be hostage to flaky networks (D16). CI never hits the skip path because its checkout always succeeds.

### CI surfaces

- **`plan-claims-gate`** (`.github/workflows/plan-claims-gate.yml`) — runs on every PR with base `main`; runs `plan-check` against each plan-doc touched by the diff. Stack PRs whose base is not `main` won't fire this gate — workaround per `reference_ci_workflow_pr_filter` is `gh pr close && gh pr reopen` after rebasing onto `main`.
- **`plan-claims-radar`** (`.github/workflows/plan-claims-radar.yml`) — 09:00 UTC cron (and `workflow_dispatch`). Enumerates all post-cutoff plans, files a single rolling open issue summarizing drifting plans. **Never** a required check — informational only; operator closes the issue manually.

**No orphaned guard scripts.** A quality guard must live as a CI-executed test or workflow step — never an inert `scripts/check_*.py` that nothing runs. Any `scripts/check_*.py` must be referenced by a REPO_ROOT-reachable CI surface (a `.github/workflows/*.yml` workflow, a `scripts/install-*.sh` hook installer, or `.pre-commit-config.yaml`); `tests/test_no_orphaned_guard_scripts.py` enforces this and fails the build naming any unreferenced guard. Wire a guard into CI, or delete it.

### Update-plan-on-ship discipline

When an implementing PR lands, the author flips `status: active → shipped` and re-resolves the `claims:` block against post-merge `origin/main`. **Do NOT bump the `date:` field** — it stays pinned at the original authoring date, preserving grandfather status; the R11b filename↔date lock also requires `date:` to match the filename prefix.

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

`monolith_budget.toml` is the **authoritative list** of radon SLOC ceilings (41 files as of Plan 2026-06-15-002 P1-3: the original 17 hot-path files plus every remaining 500+ raw-LOC file, each KEEP/CANDIDATE-audited with inline rationale — when in doubt, trust the TOML). Enforced by `tests/test_no_monolith_regrowth.py` (R4 hard-fail + R7 warning canary across `src/` + the P1-3 `webui_app`/`webui_store` canary + radon version pinning).

If a PR exceeds a ceiling, edit `monolith_budget.toml` in the same PR — raise it and add `rationale` (≥80 chars). `git blame` is the defense; no override label. Bumping `radon` (pinned `==6.0.1`) requires re-measuring all monitored ceilings + updating `SLOC_CANARY_EXPECTED` in `tests/fixtures/sloc_canary.py`.

References: `docs/plans/2026-05-18-006-feat-monolith-sloc-ceiling-plan.md`, `docs/brainstorms/2026-05-18-monolith-loc-ceiling-requirements.md`.

## Adding a new publisher adapter

Full recipe (adapter skeleton, `publish()` contract, manifest kwargs, config/deps/tests, PR checklist, banner embedding): **`docs/recipes/adding-a-publisher-adapter.md`**. Hard invariants:

- One `register("x", XAdapter, dofollow=...)` line in `publishing/adapters/__init__.py` wires the CLI argparse layer, `schema.validate_publish_payload`, throttle gating, and rejection — **never edit `cli/*.py` or `schema.py`** for a new platform (`git diff --stat src/backlink_publisher/cli/ src/backlink_publisher/schema.py` must be empty).
- `dofollow=` is **required** (`True` / `False` / `"uncertain"`); non-`True` values also require `rationale=` ≥80 chars. Enforced at import time (`TypeError`) and in CI (`tests/test_adapter_dofollow_gate.py`).
- Optional manifest kwargs `ui=` / `bind=` / `policy=` / `visibility=` collapse channel wiring into one SSoT (Velog pilot is the reference; `tests/test_manifest_contract.py` validates shape + prints migration progress).
- Platforms listed in `publishing.registry._REJECTED_PLATFORMS` raise `RegistryError` at import; un-reject only by deleting the entry in the same PR as the new `register()` call.
- Raise `DependencyError` to fall through to the next adapter; `ExternalServiceError` propagates. Wrap remote calls in `retry_transient_call`.
- Banner embedding is duck-typed opt-in: `embed_banner(artifact_path, alt) -> str | None`. `BannerUploadError(DependencyError)` is a media failure, **not** a credential failure — `mark_expired` must NOT fire on it; `config.image_gen.strict` governs only banner-specific failures, never adapter bugs.

## Binding a channel

Full flow (Settings UI badges, operator re-bind script, Velog null-after-retry diagnostics): **`docs/recipes/channel-binding.md`**. Hard invariants:

- Credential binding is **orthogonal** to publisher adapters. The closed channel set is `src/backlink_publisher/cli/_bind/channels/__init__.py::CHANNELS = frozenset({"velog", "medium", "blogger"})` — every entry point validates membership before constructing paths or argv (defense against `channel=../traversal`).
- `bind-channel --channel <name>` drives a headed Playwright session and writes `<config_dir>/<channel>-storage-state.json` (mode `0600`, temp-file + `os.rename`, `mark_bound` after the rename so kills stay idempotent). `velog-login` is a transparent alias.
- Bind routes are loopback-only (403 otherwise). New bind `error_code`s require a Chinese operator message in `BIND_ERROR_MESSAGES` (`tests/test_bind_error_messages.py` enforces).
- Publish-time 401/403 → `AuthExpiredError(channel=...)` → caught **before** generic `DependencyError` → `mark_expired(channel)` + checkpoint `error_class="auth_expired"` + exit 3.
- Velog `writePost` null-after-retry runs a `currentUser` probe: cookie dead → `AuthExpiredError` (re-bind); cookie alive → `ContentRejectedError` (**do not re-bind** — inspect `debug/velog-null-<article_id>.json` in config_dir).

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
