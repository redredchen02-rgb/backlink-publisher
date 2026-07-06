---
title: "feat: Add clickable published-URL column to History page"
type: feat
status: completed
date: 2026-06-23
claims: {}  # UI column addition, shipped pre-claims-discipline; behavior verified by the History page tests, no machine-checkable assertions to track
---

# feat: Add clickable published-URL column to History page

## Overview

The History page (`/app/history`) currently shows the **target URL** (the site receiving the backlink) but not the **published placement URL** (where the backlink actually lives). Users need to click through to the published article to cross-check whether the link is still live. The `article_urls` field is already returned by the API — this plan surfaces it as a clickable link in the table.

## Problem Frame

After a publish run, users want a quick way to verify each backlink is still in place. Without a direct link to the published article, they must manually search or re-run reconcile. Adding `article_urls[0]` (and any additional URLs) as a clickable table column gives one-click access to the placement page.

## Requirements Trace

- R1. Each history row with `article_urls.length > 0` shows a clickable `<a>` opening in a new tab.
- R2. Rows with empty or missing `article_urls` show a muted em-dash placeholder.
- R3. If a row has multiple `article_urls`, each renders as a separate link (stacked vertically).
- R4. No backend change — the API already returns `article_urls` in every history item.

## Scope Boundaries

- Does not add link-validity checking (green/red alive badge) — that is recheck's job.
- Does not change `target_url` rendering.
- Does not touch the backend or tests outside the Vue component.

## Context & Research

### Relevant Code and Patterns

- **Template to modify:** `frontend/src/pages/History/HistoryPage.vue`
  - Current `目标` cell (line ~116): `<td class="col-url target" :title="row.target_url">{{ row.target_url }}</td>`
  - No `article_urls` column exists today.
- **Canonical external-link pattern** (`frontend/src/pages/Schedule/SchedulePage.vue` line 51):
  ```
  <a v-if="row.target_url" :href="row.target_url" target="_blank" rel="noopener" :title="row.target_url">{{ row.target_url }}</a>
  <span v-else>—</span>
  ```
- **CSS:** `.data-table td.col-url` in `frontend/src/styles/app.css` already applies `max-width: 20rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap`. No new styles needed for a single URL per cell.
- **HistoryItem interface** (`frontend/src/api/history.ts` line 14): `article_urls?: string[]`
- **Backend guarantee** (`webui_app/api/history_api.py` `_normalize_item()` lines 58-65): `article_urls` is always a list (may be empty `[]`), backfilled from legacy `published_url`/`draft_url` fields.

### Institutional Learnings

- No prior solutions doc directly covers this; the link-rendering pattern is stable across `SchedulePage`, `KeepAlivePage`, and `EquityLedgerPage`.

## Key Technical Decisions

- **New column, not replacing `target_url`:** Both URLs serve different purposes — `target_url` is the SEO destination, `article_urls` is the placement. They stay separate.
- **`v-for` over `article_urls`:** Most rows have exactly one URL, but the model supports multiples. `v-for` with `:key="url"` handles both cases without branching logic.
- **`white-space: normal` override for multi-URL cells:** The inherited `.col-url` style uses `white-space: nowrap`. A multi-URL cell needs `white-space: normal` so stacked links don't overflow. Add a scoped `<style>` override only for the new column class (`.col-placement`) to avoid touching the shared `.col-url` rule.
- **No icon component:** Consistent with the rest of the SPA — plain `<a>` with `target="_blank" rel="noopener"`, no external-link icon.

## Open Questions

### Resolved During Planning

- *Where is `article_urls` populated?* Backend `_normalize_item()` guarantees the field is always a list; never undefined at runtime. Safe to call `.length` directly.
- *Do we need backend changes?* No — `article_urls` is already in every `GET /api/v1/history` response.

### Deferred to Implementation

- *Column header label (Chinese/English):* Implementer chooses; `已发布链接` or `文章链接` both fit.
- *Max URLs to display per cell:* If a row ever has 5+ URLs, the cell becomes very tall. Implementer may cap at 3 with a "+N more" label — but only if the data shows this in practice.

## Implementation Units

- [ ] **Unit 1: Add `article_urls` column to HistoryPage.vue**

**Goal:** Render each `article_urls` entry as a clickable `<a target="_blank">` link in the history table, with an em-dash fallback for empty rows.

**Requirements:** R1, R2, R3

**Dependencies:** None (backend already returns the data)

**Files:**
- Modify: `frontend/src/pages/History/HistoryPage.vue`

**Approach:**
- Add `<th>` header cell after the existing `平台` column (or after `目标` — implementer's judgment on visual order).
- Add `<td class="col-placement">` with a `<template v-if="row.article_urls?.length">` block containing `<a v-for="url in row.article_urls" :key="url" :href="url" target="_blank" rel="noopener" :title="url">{{ url }}</a>`, and a `<span v-else class="muted">—</span>` fallback.
- Add scoped style `.col-placement a { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 20rem; }` to allow stacked links while preserving truncation.

**Patterns to follow:**
- `frontend/src/pages/Schedule/SchedulePage.vue` line 51 — the `v-if` + `<a target="_blank" rel="noopener">` + `<span v-else>` pattern.
- `frontend/src/styles/app.css` `.col-url` rule — replicate the truncation properties in a scoped style block rather than touching the shared stylesheet.

**Test scenarios:**
- Happy path: row with `article_urls: ["https://example.com/post"]` → one `<a>` rendered with correct `href`, opens in new tab.
- Happy path (multiple): row with `article_urls: ["https://a.com", "https://b.com"]` → two `<a>` elements stacked, each with correct `href`.
- Edge case (empty): row with `article_urls: []` or `article_urls: undefined` → `<span>—</span>` shown, no `<a>` rendered.
- Edge case (legacy backfill): old row originally stored as `published_url` string → backend normalises to `article_urls: ["..."]` before reaching frontend, displays normally.
- Visual: URL longer than `20rem` is truncated with ellipsis; full URL visible on hover via `title` attribute.

**Verification:**
- `http://localhost:8888/app/history` shows the new column.
- Clicking a link on a published row opens the placement page in a new browser tab.
- Rows with no published URLs show `—` without errors in the browser console.

## System-Wide Impact

- **Interaction graph:** Change is confined to one Vue SFC; no stores, API endpoints, or other routes touched.
- **Error propagation:** `article_urls?.length` guards against undefined; no error paths introduced.
- **Unchanged invariants:** `GET /api/v1/history` contract, `HistoryItem` TypeScript interface, all existing columns — none modified.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Old rows lack `article_urls` (legacy JSON store) | `_normalize_item()` already backfills from `published_url`/`draft_url`; `?.length` guard handles residual empties |
| Cell height explosion if many URLs per row | Rare in practice; implementer may cap display at 3 with "+N more" label |

## Sources & References

- Related code: `frontend/src/pages/History/HistoryPage.vue`, `frontend/src/api/history.ts`, `webui_app/api/history_api.py`
- Pattern reference: `frontend/src/pages/Schedule/SchedulePage.vue` line 51
