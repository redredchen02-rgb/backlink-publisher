---
date: 2026-05-26
topic: round9-fresh-pass
focus: open-ended
---

# Ideation: Round 9 Fresh Pass

## Codebase Context

### Project shape
Python 3.11/3.12 SEO backlink-automation tool. 7 CLI entrypoints chained by JSONL stdin/stdout
(`plan-backlinks → validate-backlinks → publish-backlinks`, plus `report-anchors`, `equity-ledger`,
`footprint`, `phase0-seal`); stdout=JSONL data, stderr=diagnostics, exit 0. Flask WebUI (~21 route
modules + 3 api + 5 services), state in `webui_store/` (6 JSON singletons) + `events.db` (SQLite,
emerging single-source-of-truth). Adapter registry: one `register("x", Adapter, dofollow=..., **MANIFEST)`
line wires CLI/schema/throttle/UI; ~41 adapter files, ~30 registered, ~7 live. ~150 src modules /
~32.7k SLOC / ~3300 tests. CI = py_compile + ast.parse (no Black/flake8). HEAD `04d0443`. Dev model:
20+ `bp-*/` worktrees sharing one `.git`, many concurrent AI agents.

### In-flight RIGHT NOW (drafted plans 002–007, dirty main tree) — excluded from regeneration
registry-driven channel-binding unification; remove dead/impl adapters; projector budget rescue;
decompose validate-output-payload; retire orphaned quality guards; remove four channels.

### Recently SHIPPED — excluded
Equity Ledger, Health Dashboard, events projector fix, token-drift exit fix, Blogger OAuth security,
`fetch().json()` guards, secret-file 0600 contract, events.db kind-contract + reconcile hardening,
**Dual-State Divergence Auditor (#238)**.

### Grounding verified against source during critique (with corrections to the brief)
- **`content/scraper.py:103 fetch_work_metadata`** + soft-404 detector (`_soft404.is_soft_404_title`) +
  title/h1 extractors all exist, but are **never pointed at the destination/target URL** — plan-time
  content is authored from `seed_keywords`/`topic` only. (Premise TRUE — survivor #1.)
- The republish swallow is in **`projector.py:289-291`** (catches `sqlite3.IntegrityError` on UNIQUE
  `live_url`, does `skipped_due_to_dedup += 1; continue`) — NOT in `reconcile.py` as the brief said.
  The swallowed event survives only as a local int counter, never persisted. (Premise TRUE — survivor #2.)
- **`ledger/aggregate.py` buckets by dofollow class only**; `LinkRecord` carries **no** link-kind field
  and `LINK_KINDS` lives only in plan-time seed schema (`schema.py:104`). `events.kind` is indexed in
  events.db, so a kind×dofollow cross-tab is feasible but needs a NEW query path, not a free re-projection.
- **`_util/markdown.py:304` `validate_zh_short_payload` HARD-REQUIRES `target="_blank"`** on every `<a>`
  (emits `missing_target_blank:` errors otherwise). `footprint.py concentration_pct` then alarms on that
  exact `target_value` dimension across the whole emitted corpus — **the tool mandates the footprint it
  later flags.** (Corrects #12's "cheap win" premise → reframed as synthesis survivor #4.)
- **`anchor/resolver.py:100` `_MIN_KO_HANGUL_RATIO = 0.30`** carries `TODO(ko-corpus-calibration)`
  "unvalidated." (Premise TRUE — survivor #5.)
- **`webui_app/scheduler.py:161 _restore_scheduled_jobs()` ALREADY rehydrates** scheduled jobs from
  durable `_drafts_store` at launch (past-due ones rescheduled to now+5s). The brief's "armed jobs
  silently vanish on quit" is FALSE → scheduler idea killed.
- **`velog_cookies_flat.txt` / `velog_credentials_dump.json` (0644) at repo root are UNTRACKED and
  already `.gitignore`'d** (`git check-ignore` matches both). The "live leak reaching the repo" framing
  is FALSE; residual is a local-fs world-readable hygiene issue only → secret-gate idea demoted.
- `events/persona.py` computes a salted `persona_id` per event (0600 salt, `os.urandom(32)`, single most
  defensively-documented module; single-tenant reversibility already acknowledged in its docstring).
  Nothing aggregates by it — but persona ideas overlap the excluded fleet-footprint reject.

### Past learnings consulted (docs/solutions/, 52 files)
Recurring problem classes: (1) **silent data-drop at serialization/classification seams** (#1 class,
partial per-seam fixes only) — survivor #2 is a concrete operator-visible instance; (2) tests that
enshrine the bug (prose-only); (3) multi-agent/worktree coordination (prose-only, REJECTED every round
as dev-meta); (4) git/shell worktree portability; (5) bind/Cloudflare anti-bot (unsolved frontier);
(6) plan-grounding drift (CI-enforced). Hard rule: **no runtime LLM**. Hard gate: **no nofollow adapters**.

## Ranked Ideas

### 1. Destination-Page Preflight
**Description:** A read-only check (new `validate-backlinks` mode or standalone verb) that fetches each
seed's **target/money-page URL once** via the existing `content/fetch.py` + `content/scraper.py`, and
emits a per-target receipt: is it indexable (HTTP 200, not `noindex`, not a soft-404, not redirected
away, has `<title>`/`<h1>`), and does the planned anchor's **language/topic match** the destination's
title/h1/served-locale (e.g. a Hangul anchor pointing at an English-only page). No body generation, no
runtime LLM — pure DOM extraction + string/codepoint comparison. Report-only; never gates by default.
**Rationale:** Both critics' top-3. Every primitive is verified present (`fetch_work_metadata`,
`_soft404`, title/h1 extractors) and demonstrably never aimed at the target URL. A backlink planted at
a noindex/404/redirected money page is dead equity *and* a relevance/footprint liability — and today the
operator finds out only after rankings suffer. This closes the tool's biggest blind premise ("we author
toward a page we never read").
**Downsides:** Adds a network fetch to the plan/validate path (must use the `real_content_fetch` marker;
autouse conftest blocks fetches by default). Destination locale detection is heuristic. Operators on
intentionally-noindex tier-2 pages need an opt-out.
**Confidence:** 80%
**Complexity:** Medium
**Status:** Explored (ce:brainstorm 2026-05-26)

### 2. Reconcile Swallow Recovery Log
**Description:** When the projector hits the `articles.live_url` UNIQUE collision (`projector.py:289-291`,
currently `skipped_due_to_dedup += 1; continue`), append the swallowed republish to a sidecar
`events.kind` (e.g. `reconcile_swallowed`) instead of dropping it. Preserves the record for both
visibility *and* later repair of NULL-`live_url` orphans. The non-raising / degrade-to-stale contract is
left unchanged — this is purely additive capture.
**Rationale:** The shipped #238 auditor *detects* the resulting divergence after the fact but cannot see
the swallow *event*; this captures it at the moment of drop, turning a silent counter into a queryable,
repairable record. Concrete operator-visible instance of the #1 recurring bug class (silent data-drop at
seams) — and it compounds, rather than duplicates, work already on `main`.
**Downsides:** Marginal until a repair/replay consumer is built on top (value critic's caveat); adds rows
to events.db. Must keep the capture itself fail-safe so it never turns the non-raising path into a raise.
**Confidence:** 78%
**Complexity:** Low–Medium
**Status:** Unexplored

### 3. Link-Kind × Dofollow Equity Cross-Tab
**Description:** A new aggregation (read directly from the indexed `events.kind` column, since `LinkRecord`
doesn't carry kind) producing a per-target cross-tab of LINK_KINDS (main_domain / target / supporting /
extra / category / detail) against dofollow class. Surfaces "your dofollow equity is landing on
supporting/detail pages, not money pages" and flags degenerate kind-mixes (e.g. 100% `target`, itself an
unnatural-profile footprint).
**Rationale:** Directly answers a real SEO question the tool can't answer today ("am I wasting my best
links?"). The kind dimension is already indexed in events.db but `ledger/aggregate.py` throws it away,
bucketing by dofollow class only.
**Downsides:** Grounding-wounded: needs a new query path carrying kind from events.db into aggregation
(NOT the "free second projection" the raw idea claimed). Adjacent to the excluded "Target-Page Link-Kind
Distribution Map" — must stay scoped to OUR emitted kind×dofollow mix, not destination inbound kinds.
**Confidence:** 62%
**Complexity:** Medium
**Status:** Unexplored

### 4. Emit-Side Footprint Self-Sabotage Audit
**Description:** Audit the dimensions where the tool's **own emit/validation rules manufacture the
self-similarity** that `footprint.py` then alarms on — starting with `validate_zh_short_payload`'s
mandatory `target="_blank"` (`_util/markdown.py:304`), fixed `rel` values, and attribute ordering. For
each operator-controllable forced-uniform dimension, either relax the validation rule or vary the emitted
value, so footprint reduction happens at the *source* instead of being measured after the fact.
Incorporates the salvaged insight from the killed ambient-baseline idea: weight footprint dimensions by
**rarity/identifiability**, not raw self-consistency.
**Rationale:** Synthesis of two findings — `footprint.py` measures self-similarity, and the tool's own
validation contract *requires* one of the worst offenders. The cheapest footprint reduction is to stop
manufacturing the footprint. For a black-hat-adjacent tool this is genuine detection-surface reduction.
**Downsides:** Bold and not cheap: `target="_blank"` is load-bearing in `validate_zh_short_payload` and
multiple markdown emit paths (markdown.py:20/35/252) — unwinding it means changing a validation contract
and its tests, carefully. Some dimensions (rel=noopener) are ubiquitous-and-safe; needs the rarity lens
to avoid churning harmless invariants.
**Confidence:** 55%
**Complexity:** Medium–High
**Status:** Unexplored

### 5. Anchor-Language Ratio Calibration
**Description:** Replace the hardcoded, admittedly-unvalidated `_MIN_KO_HANGUL_RATIO = 0.30`
(`anchor/resolver.py:100`, `TODO(ko-corpus-calibration)`) with a dev-time-derived, per-language constant
checked into a small data file — computed by sweeping the threshold against a labeled accept/reject
sample (codepoint statistics only, no runtime LLM). Emit the realized vs configured ratio as a diagnostic.
**Rationale:** Airtight premise (most-grounded idea on the list). Anchor-language mix is a real footprint
knob, and a guessed constant either over- or under-mixes Hangul/Latin brand anchors silently.
**Downsides:** Low ambition — it tunes one float. Value critic's note: keep the calibration lightweight
(replace the magic number with a measured value); don't build heavy harness machinery for one constant.
The self-calibrate-from-emitted-corpus variant has a circularity risk (calibrating "natural" from your
own emissions) and should be avoided.
**Confidence:** 72%
**Complexity:** Low
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 6 | Scheduler Persistence Backbone | FALSE premise — `scheduler.py:161 _restore_scheduled_jobs()` already rehydrates from durable `_drafts_store`; armed jobs do NOT silently vanish. |
| 4* | Plaintext Secret-Leak Tripwire + Gate | Both files are UNTRACKED and already `.gitignore`'d; CI-gate fights an already-blocked path. Residual local-fs 0644 hygiene is covered by extending the shipped 0600 contract / excluded boot-time chmod sweep. |
| 7 | Persona Concentration Sentinel | Overlaps excluded "persona-scoped fleet footprint analytics"; aggregating persona_id to flag cross-host spread is fleet footprint analysis renamed. |
| 8 | Fail-Closed Classification Primitive | Generic-primitive form of excluded "silent-drop tripwire" + "phantom-success enforcer"; operator never feels it. Its operator-visible slice is captured concretely by survivor #2. |
| 9 | Negative-Assertion Test Auditor | Pure dev-meta; soft AST report over 3300 tests nobody reads; same class as rejected "Solutions-as-Lint". |
| 10 | CLI Output-Contract Self-Test Generator | Hair-splits the excluded "exit-code conformance gate"; `test_cli_exit_code_literals.py` + `test_exit_code_contract.py` already exist. Not an operator outcome. |
| 11 | Footprint Anomaly Reframe vs Ambient-Web Baseline | Insight correct (footprint measures self-similarity, wrong axis) but the static "ambient-web corpus" is unsourceable/unmaintainable and the wrong comparison for a single-operator tool. Rarity insight salvaged into survivor #4. |
| 12 | Stop Emitting `target="_blank"` | NOT a cheap win — `validate_zh_short_payload` hard-requires it and multiple emit paths inject it. Folded into survivor #4 (relax the contract that mandates it). |
| 13 | Link-Equity Decay Forecast | Cheap and actionable, but shape-overlaps excluded "link-liveness watchdog" + "Bind-Credential Expiry Forecast" (project timestamp→expiry, roll up per target). Held back to respect round-9 exclusion discipline. |
| 14 | Manifest-Driven Throttle | Dev-meta config relocation, zero operator-facing change; `_manifests.py:387` `Policy(throttle_band=...)` already half-exists; excluded "ThrottleClock"/"AdapterCapability manifest" class. |
| 15 | Persona-ID Anonymization Reframe | Module already documents single-tenant reversibility as deliberate; no export/share trust boundary exists today — solution chasing a non-problem. |

## Session Log
- 2026-05-26: Round 9 fresh pass — 40 raw candidates from 5 framed sub-agents → 15 after merge/dedupe →
  2 adversarial critics (grounding+overlap / value+cost, both file-level) → **5 survivors**. Critics
  corrected 3 false/overstated premises from the grounding brief (scheduler durability, secret-file git
  status, reconcile-vs-projector swallow location). Bar kept high; decay-forecast + fail-closed-primitive
  held back for exclusion-overlap/dev-meta despite cheap-and-real value.
- 2026-05-26: Selected **#1 Destination-Page Preflight** for ce:brainstorm handoff.
