---
date: 2026-05-20
topic: round6-fresh-pass
focus: open-ended
---

# Ideation: Round 6 Fresh Pass

## Codebase Context

### Project shape
Python 3.11+/3.12 CLI tool (`backlink-publisher`) for SEO backlink automation. Six CLI entrypoints chain via JSONL: `plan-backlinks → validate-backlinks → publish-backlinks → footprint → report-anchors → phase0-seal`. Flask WebUI at `webui_app/` (12 route modules + `create_app()` factory). Adapters live under `publishing/adapters/` and register via one-line `register("x", XAdapter)`. 6 dofollow platforms live: Medium, Blogger, Telegraph, Velog, GitHub Pages, Writeas. Hashnode CF-blocked; Dev.to/Mastodon/WP.com reverted (PR #109) as nofollow.

### Recent state (load-bearing)
- 14-day `plan-claims-gate` soak ends 2026-06-02 (becomes required check)
- `_DOFOLLOW_BY_CHANNEL` map exists in `webui_app/binding_status.py:31-58` but doesn't gate new adapter registration → PR #108 → #109 9-minute revert
- `save_config()` silently drops 5 sections: `[targets.*]`, `[sites.*]`, `[anchor_alarm]`, `[anchor.proportions]`, `[llm.anchor_provider]` → WebUI routing UI is read-only
- Browser-bind silent failures (medium-login 3-attempt fail 2026-05-20; Phase 0 spike pending)
- `events/projector.py` is the new state-of-truth (R9 work; 580 SLOC near ceiling)
- `.config-history/` 20-snapshot cap propagates rotated OAuth tokens + cookies if iCloud-synced
- 6 monolith files at SLOC ceiling; plan_backlinks.py 1270 is the highest pressure
- 4 autouse conftest fixtures isolate every test (sandbox config dir, pass URL/content checks, block sockets)
- 20+ `bp-*/` worktrees share `.git/`; editable pip install binds one tree at a time

### Past learnings consulted
- `best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md` — WebUI sibling > retrofit
- `best-practices/plan-time-url-validation-prevents-publish-404-2026-05-15.md` — PR #113 v1.0; R4/R6/R10/R11/R12 deferred
- `test-failures/negative-assertion-locks-in-bug-2026-05-15.md` + `inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md` — characterization-test pattern
- `logic-errors/save-config-write-paths-bypass-preservation-2026-05-15.md` + `logic-errors/playwright-framenavigated-orphaned-during-cross-origin-sso-2026-05-19.md`
- Memory: 27+ feedback entries, esp. `feedback_grep_dofollow_map_before_shipping_adapter`, `feedback_bind_channel_diagnostic_playbook`, `feedback_plan_doc_on_cutoff_needs_claims_block`

### Round exclusion
Survivors from rounds 1–5 (~40 ideas) were explicitly disqualified from regeneration: ErrorClass enum oracle, safe_write carve, ThrottleClock, monolith LOC test (shipped), publish lease via events.db, token bump-version invariant, plan-doc frontmatter + HEAD-drift gate, footprint loop closure, config bisect, knowledge embedding bundle, `--strict-recon`, soft-kill STOP, runs cohort, auto-retry, proactive OAuth, checkpoint+resume, bulk URL, RAG co-authoring, post-publish health monitor, append-only event log, link velocity governor, mandatory pre-publish gate, multi-candidate Medium selectors, dofollow adapter, config safety net, anchor entropy alarm, footprint emission audit, silent-drop tripwire, gate property-test, secret redactor, config echo chamber, MEMORY→solutions sediment, operational backbone, SQLite StateStore, adapter Protocol+conformance, HTTP cassettes+snapshots, kill validate-backlinks, kill auto-publish, durability backbone, token hardening backbone, osascript sandbox, containerized stub-adapter, onboarding kit, vintage+quota, time-decayed anchor profile.

## Ranked Ideas

### 1. AdapterCapability declarative manifest
**Description:** Replace the scattered `_DOFOLLOW_BY_CHANNEL` map, the duck-typed `embed_banner` opt-in, the per-platform throttle attrs, and the WebUI binding-card allowlist with a single `AdapterCapability` dataclass exported per adapter at `register()` time. Capability fields cover `dofollow: bool | "mixed"`, `banner_upload`, `oauth_dialect`, `daily_cap`, observed `rel_attrs`. Registry exposes `dofollow_platforms()` derived from the manifest. CI gate fails any new adapter shipping `dofollow=False` without `rationale=` ≥80 chars (monolith-budget pattern).
**Rationale:** PR #108 → #109's 9-minute revert was a value-validation hole. Triple agreement across operator-pain, missing-capability, and leverage agents. Closes future "ship-a-nofollow-platform" as a type error.
**Confidence:** 85%
**Complexity:** Medium
**Status:** Explored (brainstorm 2026-05-20)

### 2. `save_config` round-trip closure for known sections
**Description:** Extend `config/writer.py` `_preserve_unknown_sections` to round-trip the 5 documented-as-dropped sections — `[targets.*]`, `[sites.*]`, `[anchor_alarm]`, `[anchor.proportions]`, `[llm.anchor_provider]`. Drive WebUI routing/anchor editors with the restored round-trip so binding cards stop being read-only forms.
**Rationale:** CLAUDE.md + AGENTS.md call this out; PR #99 + PR #114 laid the infrastructure. Closes the biggest "WebUI is half a product" complaint.
**Confidence:** 90%
**Complexity:** Medium
**Status:** Unexplored

### 3. `bp explain <row_id>` — pipeline causality replay
**Description:** New sub-command: given any `id` from `publish-history` or `events.db`, reconstruct the full causal chain (seed row → anchor pick → adapter fallback tier → throttle gate → banner branch) by reading typed events. Pure read against `events.db`, no re-execution.
**Confidence:** 80%
**Complexity:** Medium
**Status:** Unexplored

### 4. Indexation Oracle (Google `site:` / GSC per backlink)
**Description:** Periodic post-publish check that queries Google `site:`, Bing URL Inspection API, or GSC URL Inspection API for each published backlink URL. Emits `{url, indexed_at, first_seen_in_serp, status}` events. Powers an indexation half-life dashboard.
**Rationale:** Closes the biggest unmet domain gap: publish success ≠ SEO success.
**Confidence:** 65%
**Complexity:** High
**Status:** Unexplored

### 5. Tier-2 plan invariant test generator (`scripts/derive-claims-tests.py`)
**Description:** Parse `docs/plans/*.md` `## Verification` sections, extract grep predicates, and emit `tests/test_plan_<id>_verification.py` autogenerated regression checks. Every shipped plan compounds the test suite without anyone hand-writing tests.
**Confidence:** 70%
**Complexity:** High
**Status:** Unexplored

### 6. Browser-bind black-box recorder
**Description:** On non-zero exit from `medium-login` / `velog-login` / `bind-channel`, auto-write `~/.config/backlink-publisher/bind-traces/<channel>-<ts>/` containing trace.zip, screenshot at predicate timeout, Cookies SQLite snapshot (redacted), final URL, network log, and a `diagnose.txt` running the 5-rule diagnostic playbook.
**Confidence:** 85%
**Complexity:** Low-Medium
**Status:** Unexplored

### 7. `.config-history/` redaction-at-rest + iCloud sync guard
**Description:** Strip secret-shaped values before writing snapshots. Drop `.nosync` sentinel. At first run, warn if config dir is under iCloud/Dropbox. Add `--with-secrets` to `bp config bisect` backed by age/sops vault.
**Confidence:** 80%
**Complexity:** Medium
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | `bp doctor` preflight aggregator | Overlaps with #6 + #1; add as follow-up |
| 2 | `bp tail` unified log surface | Operator can `tail -f`; events.db exists; merge layer not load-bearing |
| 3 | `bp publish --rehearse` shadow tree | Big scope; autouse fixtures serve at test layer; defer |
| 4 | Adapter mock-server Docker sandbox | Speculative payoff at solo-operator scale |
| 5 | Live dofollow probe (auto-generate map) | Better as follow-up *verification* on #1; standalone needs scratch accounts |
| 6 | Anchor drift forecaster (predictive) | Math identical to round-3 entropy alarm; UX shift only |
| 7 | Footprint diff across operators | Speculative — solo-operator constraint |
| 8 | Reverse-backlink audit (vs Ahrefs/GSC) | Adjacent to #4; picked simpler external-truth check |
| 9 | Seeds-from-site generator | Cold-start tax doesn't bind mature solo operator |
| 10 | Per-target-URL velocity throttle | Close to round-2 #4 "Link Velocity Governor" |
| 11 | Live liveness sentinel (longitudinal) | Too close to excluded round-2 "post-publish health monitor" |
| 12 | Delete `_LegacyPathFinder` via codemod | Low leverage on future work |
| 13 | Self-destruct stale dirs on `pip install -e` | Stale dirs are doc noise |
| 14 | Worktree `bp-shell` wrapper | Agent-facing pain; risk of locking out contributors |
| 15 | Kill autouse fixture quartet | Breaks 3200+ tests for marginal gain |
| 16 | Six-CLI argparse → declarative schema | Conflates SLOC headroom with exit-code enforcement |
| 17 | Auto-rewrite plan-claims SHAs on squash-merge | Small-scope; folds into plan-claims-gate v1.1 |
| 18 | Strip `webui.py`, console-script entry | Env-isolation already fixed at helper layer (PR #94) |
| 19 | `docs/promote.py` plan→solution promotion | Deferred in favor of #5 (stronger plan-side automation) |
| 20 | Recorded-fixture HTTP cassette test harness | Duplicates 2026-05-15 open-ideation survivor #5 |

## Session Log
- 2026-05-20: Round 6 fresh pass — 4 sub-agents (operator-pain / missing-capability / inversion-removal / leverage-compounding), ~30 raw candidates, 26 unique after dedup + 3 cross-cuts merged, 7 survived adversarial filter.
- 2026-05-20: Selected idea #1 (AdapterCapability declarative manifest) for brainstorm handoff. Brainstorm output: `docs/brainstorms/2026-05-20-adapter-dofollow-gate-requirements.md`.
- 2026-05-20 15:24: Recreated after a concurrent `git reset` wiped both this file and the brainstorm doc (untracked files lost; rebuilt from in-context content).
