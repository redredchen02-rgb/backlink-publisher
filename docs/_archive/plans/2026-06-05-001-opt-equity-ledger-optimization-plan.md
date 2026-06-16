---
title: "opt: Backlink Equity Ledger — comprehension, action, and gap-closure optimization"
type: feat
status: completed
date: 2026-06-05
claims: {}  # opt-out — branch not yet on origin/main
---

# opt: Backlink Equity Ledger — comprehension, action, and gap-closure optimization

## Summary

Optimize the existing `/ce:equity-ledger` page (in production, built by `2026-05-25-004`) across three tracks: (1) **Chinese UI + summary statistics** so the operator instantly grasps portfolio health at a glance; (2) **gap visualization + preset filters** making weak targets scannable and highly actionable; (3) **Fill Gaps action + batch recheck** that closes the loop from "diagnose" to "fix" without leaving the WebUI. All three tracks extend the existing read-only aggregation — the ledger engine is untouched.

---

## Problem Frame

The `/ce:equity-ledger` page already aggregates per-target backlink health — live/total links, dofollow breakdown, liveness freshness, platforms, recheck — but three gaps limit its operational value every day:

1. **All English.** The operator works in Chinese; column headers (`Live / Total`, `Dofollow mix`, `Liveness`), filter labels, and status text (`stale`, `unverified`) require mental translation at every glance.
2. **No aggregate health signal.** 30 rows with mixed statuses load with no summary: how many targets are weak? What's the total live-dofollow count? The operator must scan the whole table to build a mental picture.
3. **Diagnosis doesn't lead to action.** A target shows 0 live dofollow — so what? The operator must leave the page, run `equity-ledger | plan-gap | plan-backlinks` in a terminal, and manually copy the results. There's no way to recheck all stale targets at once, no way to see *which specific platforms* are missing per target, and no way to trigger remediation from the WebUI.

The page is trustworthy but not yet *useful* — this plan fixes that.

---

## Requirements

- R1. All visible UI text on the ledger page renders in Chinese (column headers, filter labels, status badges, button text, empty states). *(comprehension)*
- R2. A summary statistics bar at the top shows: total targets, total live dofollow, count of weak targets (live_dofollow=0), and healthy percentage. *(comprehension)*
- R3. Each target's detail row shows per-platform health: color-coded platform badges (green=live, amber=stale, red=failed/absent, gray=unverified/untried). *(comprehension, action)*
- R4. Each target row explicitly lists the active dofollow platforms it lacks a live link on — the "gap" — with a visual prompt. *(action)*
- R5. Preset filter buttons ("需關注", "全部弱", "健康") let the operator jump to the most important views with one click, supplementing the existing dropdown. *(operation)*
- R6. A "Fill gaps" button on each weak target generates the gap analysis and presents a ready-to-use CLI command (or in-process plan-backlinks seeds) for the operator to trigger remediation. *(action, live-dofollow)*
- R7. A batch recheck action re-verifies multiple stale/failed targets at once, removing the single-at-a-time limit. *(operation)*

---

## Scope Boundaries

- Backend ledger aggregation (`src/backlink_publisher/ledger/`, `cli/equity_ledger.py`) is **untouched** — pure frontend + new lightweight WebUI-only actions, no recomputation of the aggregation.
- `plan-gap` CLI is **untouched** — the Fill Gaps action either calls the CLI as a subprocess or invokes the `gap` engine in-process (implementation choice, but `plan-gap`'s contract is stable).
- The existing recheck service (`webui_app/services/recheck.py`) is **extended** for batch operation, not rewritten.
- No new persistent store (no campaign, no gap snapshot, no trend history). The page remains read-only with on-demand mutations.
- No dashboard page, no composite equity index, no background scheduler, no publish-time capture.

### Deferred to Follow-Up Work

- Trend/snapshot history (comparing ledger state across time) — deferred; needs a design for snapshot storage that doesn't bloat the existing stores.
- Auto-trigger Fill Gaps (e.g., "auto-run plan-gap after recheck reveals a deficit") — deferred to a future reliability plan.
- Fill Gaps as a campaign (batch fill across all targets) — deferred; this plan focuses on per-target action first.

---

## Context & Research

### Relevant Code and Patterns

**Template + JS (current page):**
- `webui_app/templates/equity_ledger.html` — Jinja template, extends `base.html`, ES module architecture. Bootstrap 5 classes throughout. Inline `<style>` for page-specific CSS. Data fed via `window.__equityLedgerBootstrap` seam. Plan `2026-06-01-007` Unit 5 established this pattern.
- `webui_app/static/js/equity.js` — Native ES module (188 lines). Client-side sorting, filtering (liveness dropdown + URL text), expandable detail rows, per-target recheck on POST `/ce:equity-ledger/recheck`. Uses shared `lib/dom.js` (`esc`, `on`, `qsa`) and `lib/api.js` (`readCsrf`). Single-at-a-time recheck via `recheckBusy` flag.

**Backend (recheck):**
- `webui_app/services/recheck.py` — `recheck_one()` / `recheck_many()`. Parameterised `verify_fn` defaults to `probe_liveness` from the shared engine (`backlink_publisher.recheck.probe`). Returns mutation dicts consumed by `history_store.update_item`.
- Recheck route in `webui_app/routes/` (POST `/ce:equity-ledger/recheck`) — dispatches `recheck_many` on the target's history items, renders the updated row.

**plan-gap pipeline (integration target):**
- `cli/plan_gap.py` + `gap/engine.py` — reads equity-ledger JSONL on stdin, emits plan-backlinks seed JSONL. Already supports `live_dofollow_platforms` (the field added by the plan-gap plan R8). The engine can be imported and called in-process from WebUI if we choose that path, or the CLI can be invoked as a subprocess.

**Ledger data model:**
- `LedgerRow` (from `backlink_publisher/ledger/`) carries: `target_url`, `live_links`, `total_links`, `live_dofollow`, `dofollow_breakdown` (`dofollow`/`uncertain`/`nofollow`/`unknown`), `exact_match_pct`, `platforms`, `liveness`, `liveness_verified_at`, `history_item_ids`, `platform_count`, `has_anchor_data`, `live_dofollow_platforms`.

**Design system:**
- `webui_app/static/css/tokens.css` — CSS custom properties for brand colors, status colors, elevation, spacing.
- `webui_app/static/css/index.css` — shared styles (cards, buttons, badges, filter chips, tables).
- Bootstrap 5 via CDN (classic non-defer head script).
- Existing patterns: `.status-badge` (success/error/pending), `.filter-chip` (pill toggle), `.badge` (Bootstrap).

**Tests:**
- `tests/test_webui_equity_ledger_route.py` (5 tests) — GET route, empty state, base layout, query params, CLI parity.
- `tests/test_webui_equity_ledger_recheck.py` (5 tests) — POST recheck confirm/downgrade/missing/unknown/both-rows.
- `tests/test_gap_engine.py`, `tests/test_gap_engine_stripped_aware.py` — plan-gap engine tests.
- `tests/test_ledger_aggregate.py`, `tests/test_ledger_model.py`, `tests/test_ledger_platform_alias.py`, `tests/test_ledger_sources.py` — ledger module tests.

### Institutional Learnings

- `ui-bugs/webui-blocking-subprocess-and-missing-progress-feedback-2026-05-12.md` — batch operations that block the UI are confusing; batch recheck must run asynchronously with progress feedback.
- `best-practices/no-runtime-llm-2026-05-15.md` — no LLM calls in this plan; Fill Gaps is a CLI-pipeline call, not an AI feature.
- `best-practices/publish-history-helper-invariant-2026-05-20.md` — all write-back goes through canonical helpers, never direct `update/append`.
- `best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md` — this plan retrofits the existing page rather than building a new one, which is the correct pattern for improvement work.

---

## Key Technical Decisions

- **Chinese localisation via template + JS string constants** (not a full i18n framework). The page is a single-purpose diagnostic tool with ~30 visible strings — a dictionary object is sufficient. No i18n library, no backend locale switching. Strings live as a `LOCALE` const in `equity.js` for JS-rendered text, and as Jinja `{% trans %}` blocks replaced inline for template-rendered text. Decision: the operator works in Chinese, the rest of the WebUI is English — this page alone is localised.
- **Fill Gaps via in-process engine call** (not CLI subprocess). The `gap.engine` already lives in the same Python process as the WebUI. Importing it directly avoids subprocess overhead, JSONL serialisation, and exit-code error handling. The endpoint returns structured gap data + optionally a CLI command string for the operator to copy (transparent, auditable).
- **Batch recheck via async worker** (not sequential inline loop). The existing single-at-a-time recheck is gated by a JS `recheckBusy` flag. Batch recheck will POST to a new endpoint that spawns a background thread for the target list, returning a job ID that the client polls. This mirrors the existing pattern from `webui_app/services/keep_alive.py` / `keepalive_job.py`.
- **Per-platform health badges derived from existing data** (no new field). The `platforms` list + `live_dofollow_platforms` list + dofollow registry give us everything needed to color-code each platform badge: present in live_dofollow_platforms → green; present in platforms but not in live_dofollow_platforms → amber (published but not live-dofollow); absent from both → gray (unpublished). No schema change.

---

## Implementation Units

### U1. Chinese UI + Summary Stats Bar

**Goal:** Localize all visible text to Chinese and add an aggregate statistics bar at the top of the page so the operator grasps overall health at a glance.

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- Modify: `webui_app/templates/equity_ledger.html`
- Modify: `webui_app/static/js/equity.js`
- Test: `tests/test_webui_equity_ledger_route.py` (extend)

**Approach:**
- Template: Replace English strings in the navbar title, filter labels, column headers, empty states, stale badge, and the "sorted by" label with Chinese equivalents.
- JS: Replace all literal English strings (`"No target pages yet..."`, `"Rechecking..."`, `"recheck failed"`, etc.) with references to a local `L10N` object constant defined at the module top.
- Summary bar: Insert a new `<div id="statsBar">` above the filter bar, rendered by a new `renderStats(rows)` JS function. Computes: total targets, total live dofollow across all targets, weak count (live_dofollow === 0), healthy %. The bar is compact and uses existing CSS classes (`.d-flex`, `.gap-3`, `.small`, `.text-muted`, `.fw-semibold`).
- Re-checking existing pattern: the `window.__equityLedgerBootstrap` seam already carries the full rows array — `renderStats` computes from the same data.

**Patterns to follow:**
- `equity.js` existing `boot()` → `render()` flow; `renderStats` is called synchronously in `render()` before the table render.
- `tokens.css` — reuse `--success`, `--warning`, `--danger`, `--primary` for stat colors.

**Test scenarios:**
- **Happy path:** Page with 3 rows (1 weak, 1 healthy, 1 stale) renders Chinese column headers and shows summary stats: "3 个目标 · 5 live dofollow · 1 弱 · 67% 健康".
- **Empty state:** Zero rows → stats bar is hidden / shows "暂无数据".
- **All weak:** 2 rows both with live_dofollow=0 → stats show "0 live dofollow · 2 弱 · 0% 健康".
- **CSV parity:** Summary values match manual computation from `rows` array in the bootstrap data.

**Verification:**
- Page renders with Chinese labels in all visible text positions.
- Summary bar shows correct aggregate numbers matching a manual count of the rows array.
- All existing tests pass.

---

### U2. Per-Target Gap Visualization + Platform Health Badges

**Goal:** Make each target's platform-level health visible at a glance. The existing detail row shows a comma-separated platform list; this unit replaces it with color-coded per-platform badges and explicitly names which dofollow platforms are missing live links — the "gap".

**Requirements:** R3, R4

**Dependencies:** U1 (the detail row template is modified in the same area)

**Files:**
- Modify: `webui_app/static/js/equity.js`
- Test: `tests/test_webui_equity_ledger_route.py` (extend — verify gap data in bootstrap)

**Approach:**
- Extend the detail row HTML template in `equity.js` to render a platform grid instead of the current bare comma-separated list.
- Each platform badge derives its color from: present in `live_dofollow_platforms` → green (`text-bg-success`); in `platforms` but not `live_dofollow_platforms` → amber (`text-bg-warning`); not in `platforms` at all → gray (`text-bg-secondary`).
- Under the platform grid, render a "Gaps" line: "缺失: platformA, platformB" — the active dofollow platforms (from the registry) that the target has never published to, or has no live-dofollow link on.
- The gap computation uses the existing `live_dofollow_platforms` field plus the registry's `dofollow_status()` to determine which *all possible* dofollow platforms the target lacks. Since `registered_platforms()` is server-side, this computation happens in the Flask route and is embedded in the bootstrap data — not computed client-side. Add a `missing_dofollow_platforms: list[str]` entry to the per-row bootstrap data.
- Update the route handler to compute `missing_dofollow_platforms` per row by subtracting `live_dofollow_platforms` from the set of registered dofollow platforms (filtered to active ones).

**Patterns to follow:**
- Existing badge styles: `.status-badge`, `.badge.text-bg-*`, `.badge.bg-*`.
- The `platforms` list in the existing bootstrap data: it already includes all relevant platforms.

**Test scenarios:**
- **Gap computation:** A target with 2 live dofollow platforms out of 5 active dofollow platforms → `missing_dofollow_platforms` lists the 3 missing ones.
- **Fully covered:** A target with live-dofollow on all active dofollow platforms → `missing_dofollow_platforms` is empty; gap section says "无明显缺口".
- **No platforms:** A target with an empty `platforms` list → all active dofollow platforms appear as missing.
- **Registry edge case:** A platform with `dofollow=False` or `dofollow="uncertain"` is correctly excluded from the gap set (gap only names *dofollow* platforms).
- **Live rendering:** The detail row HTML renders each platform badge in the correct color.

**Verification:**
- Detail rows show color-coded platform badges and a named gap section.
- Gap data is consistent with the ledger's own `live_dofollow_platforms` data.
- Existing recheck + expand/collapse tests still pass.

---

### U3. Preset Filter Buttons

**Goal:** Replace the existing single liveness dropdown with named preset filter chips that let the operator instantly switch between "全部" (all), "需關注" (needs attention — weak + stale/failed), "全部弱" (live_dofollow=0), "健康" (healthy — all good).

**Requirements:** R5

**Dependencies:** U1 (filter bar area)

**Files:**
- Modify: `webui_app/templates/equity_ledger.html`
- Modify: `webui_app/static/js/equity.js`
- Test: `tests/test_webui_equity_ledger_route.py` (extend)

**Approach:**
- Keep the existing liveness dropdown (it's still useful for specific liveness-based filtering) but supplement it with a row of `.filter-chip` preset buttons above the dropdown.
- Four presets: "全部" (reset), "需關注" (liveness=failed OR stale, AND live_dofollow=0), "全部弱" (live_dofollow=0), "健康" (live_dofollow>0 AND liveness=live).
- Active preset chip gets the `.active` class (existing `filter-chip` pattern from `index.css`).
- The liveness dropdown and URL text filter still work independently — presets are a convenience, not a replacement.
- Preset logic is an additional filter pass applied after the existing liveness/URL filters (or replacing them when active).

**Patterns to follow:**
- `.filter-chip` / `.filter-chip.active` classes from `index.css` — same visual style as the history filter bar.
- Existing `passesFilter()` function in `equity.js` — extend with a `preset` parameter.

**Test scenarios:**
- **"需關注" preset:** Shows only rows with live_dofollow=0 AND (liveness=failed OR liveness=stale). Rows with live_dofollow=0 but liveness=live are excluded.
- **"全部弱" preset:** Shows all rows with live_dofollow=0, regardless of liveness.
- **"健康" preset:** Shows only rows with live_dofollow>0 AND liveness=live.
- **Preset + URL filter:** "全部弱" preset + URL text filter narrows further.
- **Reset:** Clicking "全部" removes all preset filtering, shows all rows.
- **Preset count badge:** Each preset chip shows the matching row count (like existing `.chip-count`).

**Verification:**
- Preset filter buttons render and function correctly.
- Each preset shows the expected subset of rows.
- Existing dropdown + URL filters still work independently.
- Count badges on preset chips match manual verification.

---

### U4. Fill Gaps Action — Per-Target Remediation from WebUI

**Goal:** On any weak target (live_dofollow=0 or below desired threshold), a "Fill gaps" button triggers gap analysis and presents the operator with a ready-to-use CLI command (and optionally, in-process plan-backlinks seeds) to close the gap — without leaving the WebUI.

**Requirements:** R6

**Dependencies:** U2 (gap computation is a prerequisite)

**Files:**
- Create: `webui_app/routes/equity_gap.py` (new route module for fill-gaps endpoint)
- Modify: `webui_app/static/js/equity.js` (add Fill Gaps button + handler)
- Test: `tests/test_webui_fill_gaps.py` (new test file)

**Approach:**
- Add a new POST endpoint `/ce:equity-ledger/fill-gaps` that accepts `{target_url}` and optional `{desired: N}`.
- The route handler:
  1. Validates the target exists in the current ledger data.
  2. Computes the gap (same logic as U2, using `live_dofollow_platforms` vs active dofollow platforms).
  3. Returns structured gap info: `{target_url, missing_platforms: [...], deficiency: N, cli_command: "equity-ledger | plan-gap ...", plan_backlinks_seed: [...]}`.
  4. The `cli_command` string is the exact `equity-ledger | plan-gap --desired N --language LANG | plan-backlinks` pipeline the operator would run in a terminal.
  5. Optionally (if chosen during implementation), invoke `gap.engine` in-process and return the plan-backlinks seeds as a downloadable JSONL or inline preview.
- In the WebUI: each row with `live_dofollow === 0` (or below threshold) gets a "Fill gaps" button next to the existing Recheck button.
- Clicking "Fill gaps" POSTs to the new endpoint, receives the gap data, and renders a modal/panel showing: (a) which platforms are missing, (b) the CLI command as a copyable code block, (c) optionally the plan-backlinks seeds as a preview table.
- The modal includes a clipboard-copy button for the CLI command (using `navigator.clipboard.writeText`).
- Register the new blueprint in `webui_app/routes/__init__.py`.

**Patterns to follow:**
- Existing route patterns: `webui_app/routes/seo_viz.py` blueprint registration. POST route returns JSON.
- `readCsrf()` pattern for CSRF token in POST requests.
- Modal pattern from `_copilot_panel.html` if a large preview is needed, or inline expandable section for a lighter experience.

**Test scenarios:**
- **Gap found:** Target with 0 live dofollow, 5 active dofollow platforms, only 1 platform in `platforms` → returns 4 missing platforms + valid CLI command.
- **Fully covered:** Target with live_dofollow on all active dofollow platforms → returns `{gaps: [], deficiency: 0}`.
- **Missing target:** Unknown target URL → 404 response.
- **Invalid input:** Missing `target_url` → 400 response.
- **CLI command correctness:** The returned CLI string parses correctly and contains the target as a filter argument.
- **CSRF protection:** POST without CSRF token → 403 response.

**Verification:**
- POST endpoint returns correct gap data for all scenarios.
- WebUI shows the "Fill gaps" button only on eligible rows (live_dofollow === 0).
- Clicking "Fill gaps" opens the gap panel with correct data.
- Copy-to-clipboard button works.
- Existing recheck functionality is unaffected.

---

### U5. Batch Recheck — Multi-Target Verification

**Goal:** Enable rechecking multiple stale/failed targets in one action, with progress feedback, removing the single-at-a-time restriction of the current UI.

**Requirements:** R7

**Dependencies:** U1 (JS module area)

**Files:**
- Modify: `webui_app/templates/equity_ledger.html` (add batch action bar)
- Modify: `webui_app/static/js/equity.js` (add batch selection + handler)
- Create: `webui_app/routes/equity_batch_recheck.py` or extend existing recheck route
- Test: `tests/test_webui_batch_recheck.py` (new test file)

**Approach:**
- Add a batch action bar above the table (visible when the filter produces matching targets) with: "Recheck all weak", "Recheck all stale/failed", "Recheck all filtered" buttons.
- Each button POSTs to a new endpoint `/ce:equity-ledger/batch-recheck` with `{filter: "weak" | "stale" | "all"}` or `{target_urls: [...]}` for explicit selection.
- The batch recheck endpoint runs in a background thread (mirroring the `keep_alive.py` / `keepalive_job.py` pattern) and returns a job ID.
- The client polls `GET /ce:equity-ledger/batch-recheck/<job_id>/status` every 2 seconds until complete.
- Progress: `{"checked": 5, "confirmed": 3, "failed": 1, "skipped": 1, "done": false}`.
- On completion, the page re-renders affected rows in-place (reusing existing `rerenderRowInPlace` logic) and shows a summary toast/banner: "批处理完成：5 条已核实，3 已确认，1 已降级".
- A single spinner/progress indicator replaces the current `#recheckStatus` area during batch processing.

**Patterns to follow:**
- `webui_app/services/keep_alive.py` + `keepalive_job.py` — background job ID + polling pattern.
- `rerenderRowInPlace()` in `equity.js` — update a single row after recheck.
- `.bulk-action-bar` class in `index.css` — visual style for the action bar.

**Test scenarios:**
- **Batch recheck weak:** 3 weak targets → all 3 rechecked, rows updated in-place, summary shows correct counts.
- **Batch recheck stale:** 2 stale targets + 1 failed target → `filter=stale` rechecks only the 2 stale ones.
- **Partial results:** 1 confirmed, 1 downgraded, 1 skipped → summary correctly reflects all outcomes.
- **Polling contract:** Status endpoint returns correct `{done: false}` during processing, `{done: true}` after completion.
- **No valid targets:** All targets already live → summary says "无需处理".
- **Cancel during progress:** (Deferred — not in scope for this unit; no cancel button in v1.)

**Verification:**
- Batch recheck processes multiple targets correctly.
- Progress polls update the UI in real-time.
- Final summary shows correct aggregate counts.
- Rows are updated in-place with new liveness data.
- Existing single-target recheck still works.

---

## System-Wide Impact

- **Interaction graph:** Two new POST routes (`/ce:equity-ledger/fill-gaps`, `/ce:equity-ledger/batch-recheck`) plus one GET route (`/ce:equity-ledger/batch-recheck/<id>/status`). All follow the global CSRF guard pattern. No changes to existing recheck route.
- **Error propagation:** Fill Gaps endpoint returns JSON error payloads with `{error: string}`. Batch recheck returns errors per-target (individual failures don't abort the batch). The polling endpoint returns a 404 for unknown job IDs.
- **State lifecycle risks:** Batch recheck uses in-memory job tracking (no persistent store). If the server restarts mid-batch, the job is lost — this is acceptable for a manual action (operator can retry).
- **API surface parity:** CLI `equity-ledger`, `plan-gap`, `plan-backlinks` unchanged. The Fill Gaps endpoint is a WebUI convenience wrapper, not a new CLI contract.
- **Integration coverage:** Fill Gaps depends on U2's gap computation; batch recheck depends on the existing `recheck_many()` service.
- **Unchanged invariants:** The ledger aggregation engine, the recheck probe engine, the plan-gap CLI, and the history store are all unchanged. The WebUI remains a read-mostly view with on-demand actions.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Batch recheck on 50+ stale targets could take minutes (10s per URL × 2-3 URLs per target) | Run in background thread with polling. Progress indicator prevents UI freeze. Operator can navigate away and come back. |
| Fill Gaps CLI command may be too technical for some operators | The inline modal shows the exact CLI command as a copyable snippet; operators can also see the gap info directly and choose to proceed manually. The CLI is transparent and auditable. |
| Gap computation duplicates logic between U2 template and U4 endpoint | Both use the same `missing_dofollow_platforms` derivation. Extract into a shared helper function in the backend to keep them in sync. |
| Chinese strings in JS constant object drift from Chinese strings in Jinja template | Single source of truth: a shared dict or constant file. Since template strings and JS strings are different surfaces (template renders static text, JS renders dynamic status text), both reference their own `L10N` constant — but maintain the same string values. |

---

## Documentation / Operational Notes

- No new environment variables, no new config sections, no migration.
- The batch recheck job store is in-memory — non-persistent. Server restart = lost jobs. Acceptable for v1.
- The Fill Gaps endpoint is advisory (read + compute) — it does NOT publish or mutate stores. It returns a CLI command; the operator decides whether to run it.

---

## Sources & References

- **Origin ledger plan:** `docs/_archive/plans/2026-05-25-004-feat-backlink-equity-ledger-plan.md`
- **Origin plan-gap plan:** `docs/_archive/plans/2026-05-29-007-feat-plan-gap-deficit-replan-plan.md`
- **Origin batch optimization plan (deferred campaign pattern):** `docs/plans/2026-06-02-001-feat-batch-optimization-plan.md`
- **Background job polling pattern:** `webui_app/services/keep_alive.py` + `keepalive_job.py` (plan `2026-06-04-001`)
- **Existing recheck service:** `webui_app/services/recheck.py`
- **Existing tests:** `tests/test_webui_equity_ledger_route.py`, `tests/test_webui_equity_ledger_recheck.py`
- **Design tokens:** `webui_app/static/css/tokens.css`, `webui_app/static/css/index.css`
