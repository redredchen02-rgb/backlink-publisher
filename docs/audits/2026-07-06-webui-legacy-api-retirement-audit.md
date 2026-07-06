---
title: "WebUI legacy API retirement audit — webui_app/api/*_api.py vs webui_app/api/v1/"
date: 2026-07-06
type: audit
status: reference
plan: 2026-07-06-003 (Unit 7 / R7)
baseline: docs/solutions/architecture-health-audit-2026-06-01.md
---

# WebUI Legacy API Retirement Audit (2026-07-06)

**Mandate (R7)**: audit-and-list ONLY. Per-module adjudication of the "dual API
layer" — legacy `webui_app/api/*_api.py` (18 modules) vs `webui_app/api/v1/`
(24 modules). No code changes, no deletions, no guard test (see §7).

**Conservative baseline honored**: the 2026-06-01 architecture-health audit ruled
"the bottleneck is convergence, not more splitting" and that
`pipeline_api.py`'s `_report_engine` import is deliberate seam design. This audit
does not re-litigate either ruling; every retirement claim below cites concrete
zero-reference proof or enumerates every referencing site.

---

## 1. Headline finding: the premise "dual API layer" is only half true

Verified by scan: **none of the 18 legacy `*_api.py` modules defines an HTTP
route** — `grep -l "Blueprint\|@bp\.\|route(" webui_app/api/*_api.py` matches
zero files. They are **service/facade classes** (`SitesAPI`, `DraftAPI`, …),
and every one of the 18 is imported by its `webui_app/api/v1/` wrapper as the
implementation behind the versioned HTTP surface (e.g.
`webui_app/api/v1/sites.py:24: from ..sites_api import SitesAPI`).

Consequences for adjudication:

- **No legacy module is deletable-as-dead-code today** — v1 depends on all 18.
- "Retirement" here means retiring a module's **legacy identity**: dropping its
  `webui_app/api/__init__.py` re-export, migrating any remaining
  legacy-route/test consumers, and (optionally, later) absorbing the file into
  its v1 wrapper. It does NOT mean deleting behavior.
- The *actual* duplicate HTTP surface lives in `webui_app/routes/` vs
  `/api/v1`, and convergence there is already underway: `routes/__init__.py`
  records that `llm_bp`, `channel_bind_save_bp`, `medium_login_bp`, `bind_bp`,
  `token_paste_bp`, and `image_gen_bp` were **deregistered in Plan
  2026-06-18-002 U8 5b**, replaced by `/api/v1/settings/*`.

Frontend scan (templates `url_for`/`fetch`, `webui_app/static/js`,
`frontend/src` axios): **zero** references to any legacy `*_api` module name
(expected — they have no URL surface). The Vue SPA and static JS `/api/v1`
usage: 48 hits. Non-v1 `fetch()` calls that remain (`/api/scheduled`,
`/api/campaign/…`, `/api/pr-queue/…`, `/api/keep-alive/…`, `/api/equity-ledger`,
`/api/optimization-status`, `/api/survival`, `/url-verify`) all target
**routes-layer blueprints**, not the audited modules; two of them
(`/api/scheduled`, `/api/campaign/…`) keep `scheduled_api` / route consumers of
the audited facades alive (see §4).

---

## 2. Inventory and mapping

Legacy modules: `ls webui_app/api/*_api.py` → 18 files, 3 281 SLOC total.
v1 package: 24 modules (19 resource modules + `__init__` / `errors` /
`schemas` / `spec` infra).

| # | Legacy module (SLOC) | v1 counterpart | Legacy refs beyond `api/__init__.py` re-export + v1 wrapper | `# debt:` markers | Verdict |
|---|---|---|---|---|---|
| 1 | `bind_api.py` (206) | `v1/bind.py` | none | 0 | 可退役 |
| 2 | `blogger_settings_api.py` (66) | `v1/oauth.py` | `routes/settings_basic.py:130` (live bp) | 0 | 保留 |
| 3 | `campaign_api.py` (190) | `v1/campaigns.py` | none | 4 | 可退役 |
| 4 | `channel_bind_api.py` (381) | `v1/channel_bind.py` | `channel_forms_api.py:61` (constant), `tests/test_credential_save_dispatch_drift.py:24` | 0 | 需遷移後退役 |
| 5 | `channel_forms_api.py` (85) | `v1/channels.py` | none | 0 | 可退役 |
| 6 | `channel_overview_api.py` (60) | `v1/channels.py` | none | 0 | 可退役 |
| 7 | `drafts_api.py` (411) | `v1/drafts.py` | `routes/drafts.py:12` (live bp), scheduler circular-import, 3 test files | 0 | 保留 |
| 8 | `global_settings_api.py` (136) | `v1/global_settings.py` | `routes/settings_basic.py:19` (live bp) | 0 | 保留 |
| 9 | `history_api.py` (244) | `v1/history.py` | `routes/history.py:16`, `routes/keep_alive.py:21` (live bps), 2 test files | 0 | 保留 |
| 10 | `image_gen_diagnostics_api.py` (215) | `v1/image_gen.py` | `routes/image_gen.py:23` (**deregistered** bp), test `_FACADE` string | 6 | 需遷移後退役 |
| 11 | `llm_diagnostics_api.py` (220) | `v1/llm.py` | `routes/llm.py:23` (**deregistered** bp, patch surface), `image_gen_diagnostics_api.py:38`, 2 test files | 3 | 需遷移後退役 |
| 12 | `llm_settings_api.py` (262) | `v1/llm.py` | `routes/llm.py:24` (**deregistered** bp, patch surface) | 0 | 需遷移後退役 |
| 13 | `medium_login_api.py` (127) | `v1/medium_login.py` | test `_FACADE` string only | 0 | 需遷移後退役 |
| 14 | `oauth_api.py` (121) | `v1/oauth.py` | `routes/oauth.py:33`, `routes/settings_basic.py:147` (live bps), 2 test files | 0 | 保留 |
| 15 | `pipeline_api.py` (16, shim) | `v1/pipeline.py` | 6 webui call-sites, 10 test files, `src/` docs — designated stable-import shim | 0 | 保留 |
| 16 | `scheduled_api.py` (24) | `v1/schedule.py` | `routes/schedule.py:15` (live bp; static JS fetches `/api/scheduled`), 1 test file | 1 | 保留 |
| 17 | `sites_api.py` (437) | `v1/sites.py` | none | 5 | 可退役 |
| 18 | `velog_login_api.py` (80) | `v1/velog.py` | `routes/settings_basic.py:161` (live bp) | 0 | 保留 |

v1 modules with **no legacy counterpart** (new-surface, out of retirement
scope): `app_config`, `error_reports`, `monitor`, `profiles`,
`settings_credentials`, plus infra `errors` / `schemas` / `spec` / `__init__`.
Note `scheduled_api` is the one legacy module **not** re-exported by
`webui_app/api/__init__.py`.

---

## 3. Tier 可退役 — 5 modules (zero references outside registration)

"Registration" = the `webui_app/api/__init__.py` re-export line + the module's
own v1 wrapper import. For these five, a word-boundary full-repo scan
(`*.py`, `*.js`, `*.html`, `*.vue`, `*.ts`; excludes only each module's own
file and `egg-info`) found **nothing else** — no routes, no services, no tests,
no scripts, no templates, no SPA:

| Module | Complete reference list (proof) |
|---|---|
| `bind_api.py` | `api/v1/bind.py:33`, `api/__init__.py:13` |
| `campaign_api.py` | `api/v1/campaigns.py:18`, `api/__init__.py:15` |
| `channel_forms_api.py` | `api/v1/channels.py:23`, `api/__init__.py:17` |
| `channel_overview_api.py` | `api/v1/channels.py:24`, `api/__init__.py:18` |
| `sites_api.py` | `api/v1/sites.py:24`, `api/__init__.py:28` |

What "可退役" concretely licenses (when someone is authorized to act): drop the
five `api/__init__.py` re-export lines, and optionally relocate/absorb each
file under `api/v1/` (their code is live — it IS the v1 implementation; only
the legacy *identity* retires). Their v1 tests already patch the v1 module
(e.g. `tests/test_webui_api_v1_sites.py` patches the module-level `SitesAPI`
instance in `v1/sites.py`), so no test churn. Combined weight: **978 SLOC**,
`sites_api.py` (437) the largest. Caveat: absorbing `sites_api.py` into
`v1/sites.py` would need a `monolith_budget.toml` check first.

---

## 4. Tier 需遷移後退役 — 5 modules (every referencing site listed)

Remaining legacy consumers are cheap, enumerable migrations — mostly test
patch-strings and two route modules whose blueprints were **already
deregistered** in U8 5b (they survive only as test patch surfaces).

**`medium_login_api.py`** — migrate 1 site:
- `tests/test_webui_api_v1_medium_login.py:31` — `_FACADE = "webui_app.api.medium_login_api"` (patch-string; retarget when the module moves).

**`channel_bind_api.py`** — migrate 2 sites (both read one constant):
- `webui_app/api/channel_forms_api.py:61` — `from .channel_bind_api import _SKIP_CHANNELS`
- `tests/test_credential_save_dispatch_drift.py:24` — `from webui_app.api.channel_bind_api import _SKIP_CHANNELS` (conftest.py:105 documents this as a coincidental constant-only import)

**`image_gen_diagnostics_api.py`** — migrate 2 sites:
- `webui_app/routes/image_gen.py:23` — import from a route module whose `image_gen_bp` was deregistered in U8 5b (`routes/__init__.py` comment); the route module itself is a retirement candidate, kept as lift-parity patch surface
- `tests/test_webui_api_v1_image_gen.py:30` — `_FACADE = "webui_app.api.image_gen_diagnostics_api"`

**`llm_diagnostics_api.py`** — migrate 4 sites:
- `webui_app/routes/llm.py:23` — deregistered-bp module, retained solely as patch surface for `test_webui_unit3_security` (per `routes/__init__.py` comment)
- `webui_app/api/image_gen_diagnostics_api.py:38` — `from .llm_diagnostics_api import DiagnosticResult`
- `tests/test_webui_api_v1_llm_diagnostics.py:55` — `_FACADE` patch-string
- `tests/test_webui_llm_test_persist.py:110-143` — 8 `patch("webui_app.api.llm_diagnostics_api.…")` targets

**`llm_settings_api.py`** — migrate 1 site:
- `webui_app/routes/llm.py:24` — same deregistered patch-surface module as above

---

## 5. Tier 保留 — 8 modules (concrete reasons)

These are the deliberate **single-source facades shared by two live surfaces**:
registered legacy HTML/form blueprints AND `/api/v1`. Retiring them requires
first decommissioning the legacy route surface — a separate, unplanned
workstream. Per the 2026-06-01 baseline, forcing that now is churn without a
demonstrated duplicate-maintenance cost (the logic already lives in exactly one
place — these modules).

| Module | Live legacy consumers keeping it |
|---|---|
| `pipeline_api.py` | Designated 16-line re-export shim to `backlink_publisher.sdk.api` (plan 2026-06-22-001 U5a docstring: "import paths remain stable"). Consumers: `routes/checkpoint.py:14`, `routes/pipeline_publish.py:17`, `routes/batch.py:15`, `routes/pipeline_plan.py:18`, `services/seo_viz.py:21`, `campaign_worker.py:223`, 10 test files; `tests/test_pipeline_api_seam.py:35` explicitly whitelists it as a re-export shim. Baseline already ruled its `_report_engine` seam deliberate — not re-litigated. |
| `drafts_api.py` | `routes/drafts.py:12` (registered `drafts_bp`); known circular-import knot `scheduler → api.pipeline_api → api.__init__ → drafts_api → scheduler` that `tests/test_autopilot_scheduler.py:24` and `tests/test_webui_scheduler_restore_queue.py:66` must stub around; `tests/test_drafts_bulk_routes.py` (4 sites). |
| `history_api.py` | `routes/history.py:16`, `routes/keep_alive.py:21` (both registered); `tests/test_r6_dofollow_badge.py` (5 sites), `tests/test_history_template_rendering.py:32`. |
| `oauth_api.py` | `routes/oauth.py:33`, `routes/settings_basic.py:147` (both registered); `tests/test_webui_routes_oauth.py` + `tests/test_webui_api_v1_oauth.py` patch `webui_app.api.oauth_api.*` (18 patch sites). |
| `global_settings_api.py` | `routes/settings_basic.py:19` (registered `settings_basic_bp`). |
| `blogger_settings_api.py` | `routes/settings_basic.py:130`. |
| `velog_login_api.py` | `routes/settings_basic.py:161`. |
| `scheduled_api.py` | `routes/schedule.py:15` (registered `schedule_bp`; `webui_app/static/js` still `fetch('/api/scheduled')`); `tests/test_webui_sites_routes.py:171,180`. Only 24 SLOC; v1/schedule.py deliberately reuses it ("no new facade"). |

---

## 6. Summary counts

| Tier | Count | Modules |
|---|---|---|
| 可退役 | 5 | bind_api, campaign_api, channel_forms_api, channel_overview_api, sites_api |
| 需遷移後退役 | 5 | channel_bind_api, image_gen_diagnostics_api, llm_diagnostics_api, llm_settings_api, medium_login_api |
| 保留 | 8 | blogger_settings_api, drafts_api, global_settings_api, history_api, oauth_api, pipeline_api, scheduled_api, velog_login_api |

Debt-marker footprint: legacy side 19 markers across 5 modules (concentrated in
`image_gen_diagnostics_api` ×6, `sites_api` ×5, `campaign_api` ×4); v1 side 3
markers (`monitor` ×1, `pipeline` ×2). Debt markers do not block retirement of
any 可退役 module — they travel with the code.

---

## 7. Machine-readable retirable list

Plain list, single source of truth for any future tooling. A module belongs
here iff its complete non-self reference set is `webui_app/api/__init__.py`
re-export + its own `webui_app/api/v1/` wrapper import (§3 proof).

```
RETIRABLE_LEGACY_API_MODULES = [
    "webui_app/api/bind_api.py",
    "webui_app/api/campaign_api.py",
    "webui_app/api/channel_forms_api.py",
    "webui_app/api/channel_overview_api.py",
    "webui_app/api/sites_api.py",
]
```

**CI guard test deliberately NOT added**: review recommended a guard test that
enforces this list (fails if a new reference to a retirable module appears, or
if a retired module resurfaces). That guard is **deferred pending explicit user
authorization** — the R7 mandate for this unit is audit-and-list only. Anyone
implementing the guard later should regenerate the reference scan first; this
list is a snapshot at commit 763d0280's tree.
