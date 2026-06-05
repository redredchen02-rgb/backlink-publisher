---
date: 2026-06-05
plan_id: 2026-06-05-005
title: Config-Driven Lightweight Adapter Framework + Dofollow Priority Tier
status: completed
source_brainstorm: docs/brainstorms/2026-06-05-config-driven-lightweight-adapters-requirements.md
source_ideation: docs/ideation/2026-06-05-backlog-convergence-ideation.md (idea #2)
claims: {}
---

# Plan: Config-Driven Lightweight Adapter Framework + Dofollow Priority Tier

## ⚠️ Execution sequencing constraint (read first)

This plan was authored **while a live agent held a large uncommitted working set**
in the canonical tree (publish-verification-writeback follow-on). Several of this
plan's implementation targets are in that hot set and **must not be edited until
the live agent's changes land**:

| Hot file (live agent) | Affects which unit |
|---|---|
| `publishing/registry.py` (register() signature, RegistryEntry) | U1, U3 (register call shape) |
| `pyproject.toml` `[project.scripts]` | U4 (`verify-dofollow` entrypoint) |
| `cli/publish_backlinks/*`, `cli/_publish_cli.py` | U5 (`--tier-1` flag) |
| `webui_app/routes/pipeline.py`, `templates/*` | U6 (WebUI tier section) |

**Build order:** U1+U2 (catalog format + ConfigDrivenAdapter) are mostly in the
*clean* zone (`publishing/adapters/`, new `catalog/` dir) and can start first.
U3–U6 touch hot files → **gated on the live agent finishing + a clean
`PYTHONHASHSEED=0` suite**. Verify with `git status --short` before each unit.
Per memory `git-mutation-in-shared-tree-collides`, do code work in an isolated
clone, not this shared tree.

## Overview

The system has 24 publishing platforms but only ~5 hit the ideal "anonymous +
dofollow" combination. Each new lookalike platform currently needs a hand-written
Python adapter despite near-identical logic (GET form → extract hidden fields →
POST → follow redirect). This plan adds a **YAML-catalog adapter framework** so a
new HTTP-form-POST or API-key platform is **one `.yaml` file, zero Python**, plus
a `verify-dofollow` CLI and a Tier-1 (`--tier-1` / `--dofollow-only`) dispatch
priority derived from the existing `dofollow` field.

Non-goals (from brainstorm Scope Boundaries): OAuth/browser-login platforms,
auto-discovery of new platforms, migrating existing hand-written adapters, and
scheduled verification.

## Grounding (verified read-only against current tree)

- **Registration is already table-driven.** `adapters/__init__.py` makes ~24
  `register(platform, AdapterClass, dofollow=…, **MANIFEST)` calls into
  `publishing.registry.register`. Adding platforms is the documented one-line
  recipe (CLAUDE.md → adapter registry). A YAML auto-scan extends this by
  generating `register()` calls from catalog files at import time.
- **`register()` contract** (`registry.py:295`): `dofollow` is a **required**
  kwarg (`True|False|"uncertain"`); `rationale` required (≥80 stripped chars) and
  `referral_value` (`high|low`) required whenever `dofollow != True`. The catalog
  schema (R5) must surface all three so generated `register()` calls pass the gate.
- **`RegistryEntry` is `@dataclass(frozen=True)`** → no runtime hot-reload. This
  confirms brainstorm R8: a `dofollow` flip needs a process restart to re-tier.
- **`http_form_post.py`** exposes the exact seams ConfigDrivenAdapter needs:
  `fetch_form(url)`, `extract_hidden_fields(html, names)`, `submit_form(...)`,
  `attach_link_verification(...)`, `detect_challenge(resp)`. ConfigDrivenAdapter
  composes these — no new HTTP code.
- **Model adapters** to mirror: `txtfyi_api.py`, `notesio_api.py`, `rentry_api.py`
  (anonymous form-POST), `mataroa_api.py` / `hackmd_api.py` (API-key REST).
- **PyYAML** is already a production dependency; all catalog loads MUST use
  `yaml.safe_load()` (brainstorm Dependencies — blocks `!!python/object` injection).

## Resolved pre-planning decisions

- **Catalog path (brainstorm "Resolve Before Planning"):** adopt the brainstorm's
  recommended **built-in `publishing/adapters/catalog/` + user-override
  `$BACKLINK_PUBLISHER_CONFIG_DIR/catalog/`** (mirrors the config.toml mechanism).
  Built-in scanned first; user dir overlays by slug. *Assumption stated — flip to
  built-in-only if the user prefers a smaller surface.*
- **`ConfigDrivenAdapter` shape (deferred → resolved):** a single `Publisher`
  subclass instantiated per catalog entry (matches the lazy class-instantiation
  path in `dispatch()`), NOT a factory of one-off classes. One class, data-driven.
- **Atomic catalog write (R7, deferred → resolved):** reuse
  `_util/safe_write.atomic_write` (same path used by llm-settings, PR #140) —
  do not hand-roll tmp-rename.

## Units of Work

### U1 — Catalog YAML schema + loader (clean zone)
- New `publishing/adapters/catalog/` dir + a `catalog_schema.py` defining/validating
  fields: `slug, endpoint, auth_type(none|api_key_header|api_key_query),
  content_field, csrf_prefetch(bool), csrf_field_names(list?), permalink_via
  (redirect|json_path|regex), permalink_arg, min_delay_s, dofollow
  (true|uncertain|false), rationale(≥80 when !true), referral_value(high|low when
  !true)`.
- Loader: `yaml.safe_load()` only; validate every field; reject unknown keys;
  enforce the register()-gate invariants **at load time** (fail fast with a clear
  error naming the offending `.yaml`).
- One reference catalog entry committed as a fixture (a real anonymous form-POST
  platform, `dofollow: uncertain`).
- Tests: schema validation (happy + each failure mode), safe_load enforcement,
  gate-invariant rejection.

### U2 — `ConfigDrivenAdapter` (clean zone)
- `publishing/adapters/config_driven.py`: `Publisher` subclass taking a validated
  catalog entry. `auth_type=none` → `fetch_form`/`extract_hidden_fields`/
  `submit_form` path; `api_key_*` → `requests.post` with Authorization/api-key
  header or query param. Permalink resolved via `permalink_via`. Honors `min_delay_s`.
- Returns the standard `AdapterResult` (`base.py`). Reuses `attach_link_verification`.
- Tests: both auth paths (mocked HTTP), permalink extraction per `permalink_via`,
  challenge detection, dry-run sentinel parity with hand-written adapters.

### U3 — Auto-scan registration (⚠️ touches `adapters/__init__.py`; reads register())
- At import, scan built-in then user catalog dir; for each valid entry call
  `register(slug, ConfigDrivenAdapter-bound-instance, dofollow=…, rationale=…,
  referral_value=…)`. User-dir slug overrides built-in.
- **Gated on registry.py settling** (live agent may change register() signature).
- Tests: a fixture `.yaml` appears in `registered_platforms()` with zero Python
  edits (the headline success criterion); duplicate-slug override precedence;
  malformed catalog file fails import loudly, not silently.

### U4 — `verify-dofollow <slug>` CLI (⚠️ touches `pyproject.toml` [scripts])
- First successful publish appends the live URL to
  `$BACKLINK_PUBLISHER_CONFIG_DIR/verify-queue.jsonl` (R6).
- `verify-dofollow <slug>`: read latest URL → `link_attr_verifier.verify_link_attributes`
  → print `dofollow=True/False` → write back the catalog YAML `dofollow` via
  `safe_write.atomic_write` (R7). New console script in `[project.scripts]`.
- Tests: queue append on publish; CLI reads+verifies+writes back (mocked verifier);
  atomic write leaves no partial file; exit codes per the documented table.

### U5 — Tier dispatch flag (⚠️ touches publish-backlinks CLI — hot)
- Tier derived from `dofollow` (R9): T1=`True`, T2=`uncertain`, T3=`False` — no new
  priority field. `publish-backlinks --tier-1` (canonical) / `--dofollow-only`
  (alias, mutually exclusive) restricts dispatch to T1. No flag = unchanged.
- Tests: `--tier-1` dispatches only `dofollow=True` platforms, exit 0; alias parity;
  no-flag behavior byte-identical to today.

### U6 — WebUI priority-channel section (⚠️ touches routes/pipeline + templates — hot)
- "渠道" page: top "優先渠道" group (Tier 1 + `referral_value=high`); "一鍵僅發
  Tier 1" button → existing publish endpoint with `tier=1`. Confirm whether backend
  takes a `tier` param on `POST /publish` or needs a thin wrapper (brainstorm R11
  "Needs research" — resolve against the *settled* pipeline route).
- Follow frontend anti-rot rules (CLAUDE.md): `data-action` delegation, no inline
  handlers, `esc()` for any interpolation, `v=asset_version` on static URLs.

## Test & budget strategy
- Each unit ships its own tests; full gate is `PYTHONHASHSEED=0 pytest tests/`.
- New files (`config_driven.py`, `catalog_schema.py`, cli module) land with
  `monolith_budget.toml` SLOC ceilings + `complexity_budget.toml` CC entries in the
  **same change** if any function is born >ceiling (CLAUDE.md two-gate rule).
- R9 extension-readiness test (`test_r9_extension_readiness.py`) must stay green —
  do **not** edit `cli/*.py` or `schema.py` to add a platform; the whole point is
  catalog-driven registration.

## Risks
1. **Live-agent collision (highest, operational).** registry.py/pyproject/publish
   CLI are hot. Mitigation: build U1–U2 first in an isolated clone; gate U3–U6 on a
   clean tree + green suite; re-verify `git status` before each unit.
2. **register()-gate drift.** If the live agent changes the register() signature,
   U3's generated calls break. Mitigation: U3 grounds on the *settled* signature.
3. **YAML injection.** Enforced `yaml.safe_load()` only (U1 test asserts it).
4. **Frozen-registry expectation.** Users may expect a `dofollow` flip to take
   effect live; it needs a restart (R8). Surface in CLI output + WebUI copy.
5. **Catalog-vs-handwritten divergence.** Existing txtfyi/notesio/rentry stay
   hand-written (no migration). Document that catalog is for *new* platforms to
   avoid two sources of truth confusion.

## Success criteria (from brainstorm)
- Add an HTTP form-POST platform: one YAML, `pytest tests/` green, zero Python edits.
- Add an api_key REST platform: YAML + `config.example.toml` api_key note, zero Python.
- `verify-dofollow <slug>` flips the catalog `dofollow` field; next dispatch re-tiers.
- `publish-backlinks --tier-1` delivers only to `dofollow=True`, exit 0.
- WebUI "優先渠道" lists Tier 1 and can one-click send.
