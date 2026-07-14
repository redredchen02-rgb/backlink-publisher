---
title: "v0.6.0 roadmap, deletion analysis & first-real-campaign runbook"
type: roadmap
status: active
date: 2026-07-13
claims: {}  # unmerged feature branch feat/v060-finish-line
spec: docs/brainstorms/2026-07-13-002-v060-produce-output-finish-line-design.md
---

# v0.6.0 Roadmap, Deletion Analysis & First-Campaign Runbook

Authoritative sequencing for closing out v0.6.0, grounded in three code-verified
research passes on `main` @ `a69878ca` (2026-07-13). This is the "完整規畫新功能 +
用不到的刪除功能" deliverable: what ships in 0.6.0, what's deferred, what is (and
crucially is **not**) safe to delete, and how the operator gets the tool to
produce its first real dofollow backlink.

## 1. What is IN v0.6.0

### Landed on `main` (prior cycles)
U1 test-gate green · U2 Docker healthcheck · U3 batch-op parity · U6 `/ce:health`→SPA `/health` · U12 ESLint + frontend CI · U4 partial (`/` already redirects).

### Shipped on `feat/v060-finish-line` (this cycle — produce-output core)
- **F1 `backlink-doctor`** — preflight: shortest path to a first real dofollow backlink.
- **F2 `canary-flip`** — completes U11 flip-or-kill: one-command, A5-respecting promotion of an `uncertain` platform (patch by default; `--apply` opt-in).
- **F3 catalog activation** — operator catalog YAMLs load in production; `verify-dofollow` write-back becomes live.
- **S1 staged seal** — CHANGELOG `[Unreleased]` + `docs/runbooks/seal-v0.6.0.md` (trigger held).

### Owned by the active fleet (pending merge — belong in 0.6.0 if merged before the seal)
- **U5** broad DataTable/pagination rollout → `feat/webui-phase-a`.
- **U8** Ctrl+K command palette + TopBar hierarchy → `fix/webui-uiux-stabilization` (Bootstrap-CDN removal already landed).
- **U7** `/ce:command-center` → SPA `/app/monitor` absorption → mostly unclaimed; verify against `feat/webui-phase-a` before starting.

## 2. Deletion analysis — "用不到的刪除功能" (the honest answer)

Research finding: **the safe-to-delete-now inventory is effectively empty.** The
two things that *look* like unused features are load-bearing:

| Candidate | Verdict | Why NOT to delete |
|---|---|---|
| Retired adapters `hashnode`/`writeas` | **KEEP** | `visibility="retired"` **by design** (explicit registry comment); still resolvable for `--platform` dispatch; asserted by `test_register_all_adapters`; documented in `docs/notes/retired-platforms/`. Deleting is a regression. |
| Catalog YAML channel (`adapters/catalog/`, `config_driven.py`) | **KEEP** | A wired, tested framework (8 test files) awaiting its first real YAML. "No-op" only because its one built-in slug (`txtfyi`) collides with a hand-written adapter. F3 just gave it a live use-path. |
| Dead/unreachable Python | **NONE** | CI already runs orphan-module (`test_no_orphan_code`) + vulture (`test_dead_code_advisory`) gates. `debt_registry.toml` has zero deletable-dead-code items. The `_LegacyPathFinder` shim was already physically removed (PR #124). |
| Stale/duplicate plan docs | Low value | Only duplicate numeric prefixes; content is historical record, kept by convention. |

**The only substantial deletion is ~12.5k LOC of legacy Jinja — and that IS unit U9** (below). It is not free-fire deletion; it is a *sequenced* retirement.

## 3. The U9 legacy-retirement sequence (the real deletion, gated)

Ordering gate (plan K5): **U3 ✓ → U4 → U6 ✓ → U7 → operator-confirmed stability window (1–2 weeks) → U9 delete.** Measured legacy surface on `main`: `templates/*.html` ~4,499 LOC (21 files), `static/js/**` ~5,477 LOC (25 files), page CSS ~2,602 LOC.

- **Safe to delete after the stability window** (redirect already live): `schedule.html`, `pr_queue.html`, `survival_dashboard.html`, `optimization_status.html`, `equity_ledger.html`, `keep_alive.html` + their page JS/CSS.
- **Must land U4 redirect first** (SPA sibling exists but legacy is still the only reachable entry): `index.html`, `sites.html`, `batch_campaign.html`, `command_center.html`, plus `/ce:health` legacy.
- **Must-keep even inside U9**: `base.html`, shared partials, `static/css/tokens.css` (single shared token source), `static/js/lib/*` (shared ESM), and the `llm.py`/`image_gen.py` routes (deliberate test-patch targets).
- **File-collision to coordinate**: `webui_app/routes/settings_basic.py` is actively edited by `opt/reachable-harm-wave-a`.

## 4. Deferred units (with rationale + migration recipes)

### U4 route redirects — DEFERRED (was B1)
`/sites`, `/batch-campaign`, `/ce:history` still render legacy directly. Deferred
because the redirect has a **wide, cross-cutting test blast radius during active
fleet churn**, and its payoff (U9) is gated by the stability window above.

**Blast radius (measured):**
- `tests/conftest.py::_fetch_csrf` and `test_webui_content_fetch_gate.py::_fetch_csrf` GET `/sites` and parse the CSRF token from rendered HTML — a **shared helper**; a 302 breaks every test that fetches CSRF via `/sites`.
- `test_history_template_rendering.py` (~10) and **`test_r6_dofollow_badge.py`** (~7) assert on rendered `/ce:history` HTML — and the R6 dofollow-badge feature is exactly what `feat/webui-phase-a` is churning. High collision.
- `test_webui_batch_campaign.py` (~6) asserts rendered `/batch-campaign` HTML.
- Inbound legacy links: `templates/health.html` → `/sites`; `templates/campaign_progress.html` → `/batch-campaign`.

**Migration recipe (do this once the fleet settles, per route, mirroring `routes/schedule.py`):**
1. Rename the render view to `…_jinja` at `GET /<route>/jinja`; add a bare `GET /<route>` returning `redirect(url_for("spa.spa", subpath="<page>"), 302)`.
2. Repoint `conftest._fetch_csrf` and `test_webui_content_fetch_gate._fetch_csrf` to `GET /sites/jinja`.
3. Repoint the `test_history_template_rendering` / `test_r6_dofollow_badge` / `test_webui_batch_campaign` legacy-HTML assertions to the `…/jinja` routes.
4. Update the two inbound legacy links to `…/jinja` (or leave them — they'll follow the redirect).
5. Point the internal `sites_save_three_url` success redirect at `/sites/jinja?saved=…` so the legacy form's confirmation flow stays self-contained; the SPA save flow uses `/api/v1/*`.
6. Keep all POST/API sub-routes (`/sites/save-three-url`, `/sites/autopilot`, `/sites/scrape-preview`, …) — those retire in U9, not U4.

### U13 E2E expansion — DEFERRED (was B2)
Add health-console / workbench / pagination journeys. Deferred because the e2e
lane is **Playwright + chromium + a built SPA bundle** (`tests/e2e/publish_journey.py`
pattern: `pytestmark = enable_socket`, live werkzeug server, real browser),
which can't be authored-and-verified without that toolchain, and the built bundle
is fleet-churned. Recipe: mirror `publish_journey.py` (self-skips when the SPA
bundle / chromium / sockets are absent), add the three specs to `.github/workflows/e2e.yml`'s run step. A lighter interim option is Flask-test-client integration journeys in `tests/` (no browser) for the health-dashboard + operations chains.

### U10 lane-parallel publish engine — PARKED (measurement gate)
Stays parked: zero real publish telemetry means no data supports the mixed-run
premise. **Un-park trigger:** the first real publish run's `row_timing_summary`
(now emitted to stderr) shows a mixed-platform run where lane parallelism would
help. **F1 + the first-campaign runbook below are the fastest path to producing
that telemetry.**

## 5. Operator runbook — produce your first real dofollow backlink

The tool has never produced a real backlink on this machine (empty
`events.db`/history). It can — trivially. Fastest path:

1. **Run the preflight:** `backlink-doctor` → it names the zero-credential path
   (`rentry`/`telegraph` are `dofollow=True`, `auth_type="anon"`) and lists the
   config gaps.
2. **Fill the two required configs** (`~/.config/backlink-publisher/`):
   - `config.toml` with a `[target.*]` section: `main_url` + `anchor_keywords`/pools.
   - `llm-settings.json` (`0o600`) for article-body generation at plan time.
3. **Produce a real anonymous dofollow backlink now** (no account):
   `plan-backlinks <seeds> | validate-backlinks | publish-backlinks --platform rentry`.
   This writes the first `events.db` row — converting the adapters from
   "mock-tested" to "observed working" and unblocking the U10 measurement gate.
4. **Bind one high-value channel and shake out its real auth path** — prefer the
   most deterministic first: `ghpages` (token/PAT) before the fragile
   `live_browser` logins (`medium`/`velog`).
5. **Close the flip-or-kill loop for the anonymous `uncertain` pair** (`txtfyi`,
   `notesio`): `canary-seed txtfyi > verdict.jsonl` then
   `canary-flip txtfyi --from-receipt verdict.jsonl` → review the emitted patch →
   `git apply` (or `--apply`) → add a regression test asserting
   `dofollow_status("txtfyi") is True`. Repeat for `notesio`. (This also lets you
   fix the already-stale `hackmd`/`mataroa` rows in `canary-pending.md`.)

## 6. Seal

When the fleet SPA branches (`feat/webui-phase-a`, `fix/webui-uiux-stabilization`)
merge, follow `docs/runbooks/seal-v0.6.0.md` to bump 0.5.0 → 0.6.0, regenerate the
OpenAPI spec, promote the CHANGELOG, and tag `v0.6.0`.
