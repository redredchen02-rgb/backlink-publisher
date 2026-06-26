# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- **Test collection errors (R12 Phase A):** 16 test files with `__tier__` assigned before `from __future__ import annotations` — reordered to comply with PEP 236, unblocking 366 tests. 3 additional test files had broken import paths from the U8 CLI reorganization (`keepalive_status`, `plan_check_helpers`, `report_anchors`, `cli_health_check`, `state_backup`) — updated to `cli.ops`, `cli.plan`, `cli.admin` subdirectories. Full suite now collects **11,962 tests with 0 errors**.
- **Complexity budget zeroed (R12 Phase B):** Decomposed `sites_save_three_url` (CC 38) into `_validate_three_url_fields` (CC 18) + `_derive_three_url_fields` (CC 12) + thin shell (CC 11). Removed the last `[functions]` entry from `complexity_budget.toml` — all functions now under the CC-30 backstop.
- **TODO/FIXME cleanup (R12 Phase C):** Promoted the sole remaining TODO (`ko-corpus-calibration` in `linkcheck/language.py`) to `debt_registry.toml`. Closed the last active plan (`2026-06-23-001` HistoryPage article_urls column — already implemented).

### Changed

- **CLI test split confirmed:** `test_cli_generate_backlink_text.py` already decomposed into split1 (557 SLOC) and split2 (531 SLOC); budget ceiling lowered to 10.
- **SPA migration roadmap updated:** Phase 1 and Phase 2 checkboxes marked complete; Jinja-only inventory documented for Phase 3 planning.
- **Monolith budgets tightened for 5 U8 shim files:** `phase0_seal.py`, `plan_check.py`, `report_anchors.py`, `generate_backlink_text.py`, `canary_seed.py` all became 2-SLOC backward-compat shims; ceilings lowered from 465/260/120/390/230 → 40 each.
- **Orphan code ALLOWLIST expanded:** Added 7 files to the pre-existing allowlist (U8 shims, cli helpers, formatting utility). Normalized Windows path separator in the scan-to-allowlist comparison.

### Newly Surfaced (pre-existing, unblocked by collection fix)

Fixing the 19 collection errors unblocked **366 previously-masked tests**. Among them:

- **`test_cli_generate_backlink_text_split2`** — 89 failures: some subprocess `--help` assertions broke after U8 CLI reorganization (entry-point paths changed); remaining failures are pre-existing test bugs in LLM orchestration mocks. Was 0% collected before the fix.
- **`test_config.py`** — 7 failures: test-state isolation issues where earlier tests leak config mutations into later tests. All pre-existing and unrelated to code changes.

These are tracked as pre-existing debt — not caused by this round's changes. The `test_no_monolith_regrowth.py` warning canaries for `spray_backlinks/core.py` (517 SLOC) and `webui_app/api/v1/spec.py` (1259 SLOC) also remain as pre-existing soft warnings.

## [0.5.0] - 2026-06-26

### Added

- **Vue 3 SPA** (`frontend/src/`): full single-page application replacing the piecemeal Jinja pages. Routes: `/app/settings`, `/app/monitor`, `/app/history`, `/app/sites`, `/app/profiles`. TanStack Query for data fetching with automatic stale-indicator wiring; Pinia for SPA-local state.
- **`/api/v1` JSON backend** (`webui_app/api/v1/`): versioned REST surface consumed by the SPA. Covers pipeline (plan / validate / preview / publish), LLM settings + diagnostics, image-gen, velog, site settings, credentials, monitor, history, profiles, and CSRF token endpoint. All endpoints emit RFC 9457 problem+json on error.
- **Embeddable SDK runtime** (`src/backlink_publisher/sdk/`): `PipelineAPI` and `publish_inprocess()` run the publish pipeline in-process without subprocess round-trips; used by both the `/api/v1/pipeline` routes and standalone integrations.
- **Design system** (`frontend/src/styles/`): CSS custom-property token set (`tokens.css`), `data-table` shared layout, `StateBlock` four-state component (loading / empty / error / ready) with stale indicator.
- **`useErrorToast` composable**: XSS-safe fixed-template error classification; adopted across 13 Vue pages — raw server text never reaches the DOM.
- **Parallel-safe optimisation lanes** (`perf/parallel-safe-lanes`): five independent correctness + performance improvements landed as cherry-picked commits; `sqlite3.Row.get` latent bug fixed.
- Unified empty-state onboarding CTA across the index and settings pages: distinguishes true zero-config (a 去配置 call-to-action) from a filtered-empty view (清除筛选) from a load failure (inline error with retry), so an empty screen always tells the operator what to do next. (#40)
- Shared error taxonomy (`ui/errors.js`): a closed set of network / permission / server / unknown categories with fixed copy templates, routed through the index, settings, and monitor-hub error paths so failure messaging reads identically across pages and never leaks raw server text. (#40)
- Core-flow CSS token-compliance gate (`tests/test_webui_css_no_raw_colors.py`, allowlist-scoped to core pages): bare Bootstrap colour classes and raw colour literals on the core flow are collapsed into `tokens.css` and held there by the gate; fast-follow pages are explicitly excluded. (#40)
- **GSC indexation + ranking feedback loop** (`probe-index`, `probe-ranking`): two new CLI commands query Google Search Console Search Analytics API to record whether published pages have GSC impressions (`gsc.page_signal`) and to snapshot keyword positions (`ranking.snapshot`). Results surface on the `/ce:health` dashboard in two new panels: GSC page-signal status and keyword ranking trend (baseline vs. latest, with delta and trend arrow). Baseline snapshot is taken advisory before `plan-backlinks` runs. Rolling 30-day dedup avoids re-probing recently checked URLs. flock guards prevent overlapping runs. LaunchAgent plists provided for daily/weekly scheduling.
- **Autopilot status visibility**: `/sites` page now shows a `狀態` column for each site — `—` when disabled, `⚠ 上次失敗` (red) when `alert_pending`, `⏭ X 小時後` (green, computed by `formatRelative()`) when a next run is scheduled, or `排程中…` when enabled but no job queued yet. Status is server-rendered on page load; toggle action updates it immediately via JSON response `next_run_time`.
- **Health page alert badge**: `autopilot-alert-banner` now shows a failure count badge and a `/sites →` jump link, so operators know how many sites need attention at a glance.

### Fixed

- `drafts insert_first` now guarantees a newly inserted draft prepends even when it collides with a future or sub-millisecond `inserted_at` timestamp — previously surfaced as an ordering "flake", it was a real bug where a fresh draft could fail to appear first. (#42)
- `monitor_hub.load()` guards against out-of-order render under rapid refresh: a per-load `AbortController` aborts the prior in-flight fetch and drops any superseded response, so a slower earlier request can no longer overwrite a faster later one. (#43)
- Autopilot POST rollback now restores only the affected site's config, preserving concurrent updates to other sites.
- Scheduler module access in POST handler now uses `.get()` (same as GET), avoiding `KeyError` when the scheduler is not yet loaded.
- `get_job()` in POST path now degrades gracefully (returns `next_run_time: null`) without triggering store rollback.

### Changed

- **Codebase decoupling (Phase 1–3)**: 7 grandfathered high-CC functions decomposed below CC 30 backstop; `_generate_payload` (50→8), `_run_spray` (48→removed), `run_cycle` (45→18), `_build_links` (36→9), `save_config` (33→15), `_publish_one_row` (35→5), `_enhance_payload` (32→27). All CC budget entries removed. (Plan 2026-06-24-002)
- **`__all__` declarations**: 50+ subpackages now declare explicit `__all__`, making the public API surface auditable at a glance. Import-linter CI enforcement with 2 forbidden contracts (`domain → cli`, `_util → domain/cli`) — both KEPT. `CHANNELS` moved from `cli/_bind/channels/` to `_util/constants.py` to resolve a root layer violation. (Plans U6–U7)
- **CLI subdirectory reorganization**: 34 CLI entry points moved from flat `cli/` into 6 functional subdirectories (`plan/`, `publish/`, `spray/`, `admin/`, `reporting/`, `ops/`). Shim modules at original paths and updated `pyproject.toml` console_scripts ensure full backward compatibility. (Plan U8)
- **Bulk modernization**: ruff (F/E/W/UP/I rules) replaces CI `py_compile`+`ast.parse`; isort-style import reordering across 880+ files; pyupgrade (`datetime.now(UTC)` etc.); thread-safe `http_client` via `_ThreadLocalProxy`; Windows compat layer (`_compat/fcntl` shim, batch scripts, `docs/windows-setup.md`).
- **make lint-imports** target added; CI pipeline extended with `lint-imports` step.
- Legacy Settings Jinja page retired; SPA at `/app/settings` replaces it. Six Jinja template files, four route modules (`bind.py`, `channel_bind_save.py`, `medium_login.py`, `token_paste.py`), and five legacy JS/CSS assets deleted.
- `velog` login response replaces `log_path` filesystem path with `has_log` boolean (path never leaves the server).
- `pipeline.py` `_EXIT_STATUS`: exit code 1 (conflict/force-manifest abort) now maps to HTTP 422 instead of falling through to 502.
- Documentation convergence: 67 superseded plans/brainstorms archived into `docs/_archive/`, inbound references repointed, and the active doc surface collapsed to a single roster (`docs/active-docs.md`). The retired referral-302 plan carries a do-not-revive tombstone. (#41)

### Deferred

- **Indexability → equity-ledger bridge (R5)** deferred by data: the gate-G1 resume trigger (blocked links ≥5 OR a dofollow channel ≥10%) was not crossed on resample. The implementation path and resume trigger are preserved in the v0.5.0 convergence requirements doc for revival once a real production corpus crosses the threshold.
- **dofollow platform expansion (R1)** slips to v0.5.1: graduating ≥2 existing `uncertain` adapters to `dofollow=true` requires live operator canary runs not performed in this round. This release ships UI consistency, governance convergence, and the existing dofollow set unchanged.

## [0.4.0] - 2026-06-12

### Added

- Glass/Gradient dark theme foundation: CSS design token system (`tokens.css`), full-page dark background with animated gradient orbs, pipeline wizard in glass card style.
- Settings page tier-grouped channel UX: T1 (免綁定/anon) channels surfaced at top with green badge + 試發布 CTA button; T2 (credentials) sorted bound-first; T3 (browser) with coming-soon stubs. Sidebar gains T1/T2/T3 sub-groups with channel counts.
- Cold-start T1 overview banner: when only anon channels are bound, the overview panel shows a prominent "立即試發布" hint above the channel cards.
- Command Center UI refresh: glassmorphism health chips, subsystem cards, and friendlier error messages (Python path noise stripped from displayed errors).
- Equity status now derives from `OptimizationState` instead of the removed `ledger_store`.

### Changed

- History panel: glass-style rows, dark badge variants, filter chips, and empty-state illustration.
- Batch publish panel: glass cards, CTA shine animation, completion indicator.
- Settings sidebar: gradient active-bar indicator, dark badge and card polish.
- URL input group and config sections: glass background with token-based borders.
- Focus ring and form control polish applied across all WebUI pages.
- `schedule.css` wrapped in `@supports` guard for safe cross-browser loading.

## [0.3.1] - 2026-06-04

### Added

- Internal LITE edition with loopback-only binding, trimmed nav (keep-alive core), and FLASK_DEBUG=0 by default. LITE mode set via `BACKLINK_PUBLISHER_LITE=1`; launcher rewired to `scripts/launcher.command` as single source of truth (R9).
- Keep-alive recovery loop (R1): recheck → gap detection → republish → re-verify → treadmill, closing the operator-facing "push and prove" cycle. S1-S7 frontend with S3 gap-selection panel, S4 confirm overlay, S5 publish/recheck progress, S6 result, and S7 treadmill banner.
- Keep-alive recheck button (POST /ce:keep-alive/recheck) with async job registry, polling status endpoint, and cancel support.
- Keep-alive republish job with phase/reverify/restripped/confirmed_alive tracking; `issue_confirm_token` returns per-seed destinations.
- `plan-gap` CLI (engines/gap/): deficit-driven re-plan over dofollow platforms; stripped-aware variant using RUNTIME_STICKY_PLATFORMS.
- Validation test suite (plan 2026-06-04-004): full-stack coverage for validation pipeline.
- AI content engine pro mode wiring (plan 2026-06-04-003).

### Changed

- `hashnode` and `writeas` channels marked `visibility="retired"` in the adapter registry (plan 008 cleanup; deletion follow-up planned).
- `/sites/run` POST and `/sites/run/<id>/result` GET collapsed into keep-alive flow — both redirect to `/ce:keep-alive`. The old "运行（plan-backlinks）" button replaced with a link to the keep-alive panel (R2, Unit 8).
- 141 completed/shipped/parked plan docs archived from `docs/plans/` to `docs/_archive/plans/`; one active plan remains in place (R10, Unit 12).
- 5 WebUI stores migrated from JSON to SQLite (`webui.db`): Schedule, Profiles, Queue, Drafts, Campaign. WAL mode + 0o600 permissions. History store excluded per existing plan scope.

### Fixed

- Telegraph publishing now falls back to Chrome/CDP (`TelegraphCdpAdapter`) when the API path returns a dependency error. Chain order is API first, CDP second; environments without Chrome safely skip the fallback.
- LiveJournal adapter includes a configurable post-publish delay (`post_publish_delay_seconds`, default 30 s, overridable via `LIVEJOURNAL_PUBLISH_DELAY_S`) so the downstream verify step gets an extended window for page propagation. Fixes `published_unverified → InternalError` regressions on slow-propagating LJ pages.
- Version bump to 0.3.1 with full test suite at 9812+ passing.

## [0.3.0] - 2026-06-01

### Added

- `POST /copilot/ask` LLM-backed Q&A route (`routes/copilot.py`). Accepts natural-language questions, calls the configured LLM via `safe_post_json`, returns answers as JSON. Returns `400` when unconfigured, `502` on LLM failure. Plan U5.
- Q&A panel (`_copilot_panel.html`) — unlocked/locked state driven by server-side `llm_configured` context processor. Includes copilot.css (form, bubbles, loading/error states) and copilot.js (ESM module, CSRF-safe `postJson`). Plan U6.
- `llm_configured` context processor in `webui_app/__init__.py` — checks `llm-settings.json` existence and validity to drive UI state.
- `src/backlink_publisher/_util/ssl_ctx.py` — SSL context utility module.
- Full test suite: 14 route tests (`test_copilot_qna_route.py`), 8 panel render tests (`test_copilot_panel_render.py`), 3 Q&A render tests (`test_copilot_qa_render.py`), 3 asset version cache tests (`test_asset_version_cache.py`), 3 SSL context tests (`test_linkcheck_ssl_ctx.py`), route contract extension (`test_webui_route_contract.py`).

### Fixed

- `test_pipeline_inprocess_characterization.py` — expanded coverage for edge cases.
- `webui_app/helpers/cli_runner.py` — adjusted for API changes.

- URL verify throttle rollback now removes the caller's own session-window
  slot by value (`remove(now)`) instead of the last-appended entry (`pop()`).
  Under concurrent calls sharing the same session, `pop()` (LIFO) could remove
  a *peer's* slot instead of the failing caller's own, leaking the failing
  caller's timestamp in the window. This caused the session's rate-limit counter
  to over-count rejected requests: a session could be rate-limited for a 10s
  window even though its requests were turned away before being served. Both
  rollback paths (`upstream_overloaded` and `host_busy`) are fixed.

- `spawn_browser_login` now prepends the **absolute** path to `src/` in
  `PYTHONPATH` for the detached subprocess, matching the pattern established in
  `bind_job.py`. The previous relative `"src"` prefix only resolved when the
  WebUI was started from the repository root; starting from any other directory
  (e.g. a system-service working directory) would cause the subprocess to fail
  with an `ImportError` on `backlink_publisher`.

- G3 referer-audit evidence now correctly shows `preserving=none` when every
  render path strips `referer`. The previous `or "preserving=none"` fallback
  was unreachable: `"preserving=" + ""` (an empty join over a zero-length list)
  is truthy, so the `or` short-circuited and the evidence cell always read
  `"preserving="`. Operators reading the committed `gate-verdicts.md` ledger
  or the raw JSONL evidence when all paths strip referer would have seen a
  misleading empty `preserving=` token instead of the explicit `preserving=none`.

- SSRF blocklist now rejects `168.63.129.16` (Azure wireserver). This address
  is not RFC 1918, not link-local, and not covered by the existing
  `169.254.0.0/16` range, so it previously passed the IP guard. Azure wireserver
  exposes DHCP, platform key management, and health-probe endpoints that are
  reachable only from inside Azure VMs; an attacker-controlled redirect or a
  domain that resolves to it could exfiltrate instance metadata. The address is
  now blocked as a dedicated `/32` entry in `_BLOCKED_NETWORKS`.

- `upgrade_target_to_threeurl` (the `/sites` "upgrade legacy target → three-URL"
  path) now finds an existing `anchor_keywords` pool keyed by the bare domain or
  a scheme variant, via the canonical `get_anchor_keywords` accessor. Previously
  it tried only the scheme-exact key plus a trailing-slash variant that stored
  keys never carry (`_parse_target_anchor_keywords` rstrip's them), so a
  `[targets."legacy.com"]` pool was silently dropped and the target bootstrapped
  to just the domain label — losing the operator's curated keywords on upgrade.
- `[anchor_alarm]` override parsing now rejects unknown keys in an
  `[[anchor_alarm.override]]` row instead of silently ignoring them, mirroring
  the global-scope unknown-key guard. Previously a misspelled threshold field
  (e.g. `exact_ratio_ceil`) was dropped without error whenever the row also
  carried a valid field, so the operator's intended override silently never
  applied. The row now raises `InputValidationError` at config load.
- txt.fyi adapter now clears the site's anti-spam dwell-time gate before
  submitting. `edit.php` rejects POSTs that arrive too soon after the form was
  served (keyed off the hidden `form_time` field): a sub-second GET→POST — what
  the adapter did — is treated as a bot and silently tarpitted to a 200 "Thank
  you for your submission!" page with no redirect and no permalink, so every
  txt.fyi publish failed with `ExternalServiceError: did not redirect to a
  published URL after submit`. The adapter now waits a configurable dwell time
  (`BACKLINK_TXTFYI_SUBMIT_DELAY_SECONDS`, default 4s; the gate cleared by ~3s
  in 2026-05-29 probing) before the POST, and detects the tarpit page to raise
  an actionable error (raise the delay) instead of the generic no-redirect one.
- All three `urllib.request` fetch sites now normalize non-ASCII URLs before
  opening a connection, preventing `'ascii' codec can't encode characters`
  crashes across the full pipeline: `linkcheck.verify.verify_published`
  (post-publish verifier — the original crash site), `linkcheck.http.check_url`
  (pre-publish reachability), and `content.fetch.verify_url_has_content`
  (planning-phase URL gate). A shared `_util.url.normalize_url_for_fetch`
  helper IDNA-encodes the host and percent-encodes path/query; ASCII URLs
  pass through byte-identical and idempotent. Previously Velog Korean
  `@username` / CJK `url_slug` URLs demoted legitimately-published posts to
  `published_unverified`. Plan 2026-05-21-005.

### Added

- `medium-login` CLI: thin alias for `bind-channel --channel medium`, matching
  the `velog-login` pattern (Plan 2026-05-19-005 Unit 1).
- `ChannelRecipe.post_persist` hook (optional): driver invokes after
  `_persist_storage_state` succeeds and before `mark_bound`, letting recipes
  derive secondary credential files. Used by the medium recipe to convert
  Playwright `storage_state.json` into a cookies-only `medium-cookies.json`
  + a `medium-meta.json` (UA + chromium version, captured live by the
  predicate). velog / blogger recipes leave `post_persist` `None` — no
  behavior change.

### Changed (**Breaking** for existing Medium operators)

- `MediumBrowserAdapter` now reads its credential from
  `<config_dir>/medium-cookies.json` via `context.add_cookies([...])`. The
  pre-Plan-005 path that read `medium-storage-state.json` via
  `new_context(storage_state=...)` is removed; no double-write window, no
  fallback. Operators upgrading across this release must run `medium-login`
  (or `bind-channel --channel medium`) once to populate the new file. The
  adapter's friendly `DependencyError` on first invocation spells out the
  exact command.
- `bind-channel medium` now writes `medium-cookies.json` (the new canonical
  bound credential) and unlinks `medium-storage-state.json` in the same
  bind cycle. The `channel_status_store["medium"]["storage_state_path"]`
  field now points at `medium-cookies.json` (the field name remains
  historical; the value reflects current canonical state).

### Notes

- Hard-cut chosen over a 60-day double-write window: this is a
  single-operator tool per AGENTS.md, so the 2-minute cost of running
  `medium-login` once is lower than the cost of maintaining a dual-format
  compatibility layer with a calendar-driven sunset PR.
- Future `MediumGraphQLAdapter` (Plan 2026-05-19-005 Unit 2, Phase 2,
  gated by spike) will consume the same `medium-cookies.json` +
  `medium-meta.json` for headless GraphQL publishing.

[Unreleased]: https://github.com/redredchen02-rgb/backlink-publisher/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/redredchen02-rgb/backlink-publisher/releases/tag/v0.5.0
[0.3.0]: https://github.com/redredchen02-rgb/backlink-publisher/releases/tag/v0.3.0
