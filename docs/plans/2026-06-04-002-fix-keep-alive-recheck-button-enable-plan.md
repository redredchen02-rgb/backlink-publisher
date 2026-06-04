---
title: "fix: Enable keep-alive recheck button"
type: fix
status: completed
date: 2026-06-04
origin: docs/plans/2026-06-04-001-feat-internal-edition-lite-keepalive-plan.md
---

# fix: Enable keep-alive recheck button

## Overview

The "立即巡检" button on `/ce:keep-alive` is permanently `disabled`. Its title says "Unit 5 接入异步任务后启用", but all needed infrastructure already exists: `recheck_many()` is fully implemented and tested, `HistoryAPI.bulk_recheck()` is proven in the history screen. This plan wires the button to that existing service via a new POST route and a thin JS handler — no new async machinery needed.

## Problem Frame

`webui_app/templates/keep_alive.html:20` sets `disabled` with no code path to remove it. The plan that gated it (plan 2026-06-04-001 Unit 4) was intentionally read-only, deferring action states to "Units 5-7". The minimal fix: add a synchronous backend route, enable the button, add a fetch-based handler.

## Requirements Trace

- R1. Clicking "立即巡检" triggers recheck of all published history items and refreshes the scorecard.
- R2. Button shows a loading state while the request is in-flight.
- R3. On completion, the user sees an updated scorecard (stale banner disappears if publish→recheck gap closes).
- R4. No new async/queue infrastructure introduced — reuse `HistoryAPI.bulk_recheck`.

## Scope Boundaries

- No S1 progress animation (streaming / websocket). Synchronous POST → redirect is sufficient.
- No partial-select UI (recheck all items, not a subset).
- No changes to the async queue (APScheduler, queue_store) — that is future Unit 6+ scope. This synchronous route is designed to be **replaced** by the Unit 6+ async handler when it lands; the two are not intended to coexist.
- No republish states (S3-S7) — those remain deferred per original plan.

## Context & Research

### Relevant Code and Patterns

- Disabled button: `webui_app/templates/keep_alive.html:20-23`
- Existing bulk recheck route pattern: `webui_app/routes/history.py:100-106` (`ce_history_bulk_recheck`) — exact model to follow
- Recheck service: `webui_app/services/recheck.py` — `recheck_many()` / `recheck_one()`, fully tested
- `HistoryAPI.bulk_recheck(ids)`: `webui_app/api/history_api.py:174-203` — receives list of item IDs, calls `recheck_many`, updates store, writes `link.rechecked` events to events.db, returns `{ok, flash_msg}`
- Flash URL param pattern: `webui_app/routes/main.py:16-17` and `webui_app/routes/sites.py:78-79` — read `flash_type` / `flash_msg` from `request.args`, pass to `_render`
- JS fetch+CSRF pattern: `webui_app/static/js/lib/api.js` — `postForm(url, data)` appends `csrf_token` field; `equity.js:11` uses `readCsrf()` directly; `lib/dom.js` exports `delegate()`
- `keep_alive.js` state controller comment (line 140-141): "U5-U7 add cases (s1-rechecking, …) as new cases on this same switch"
- History store access: the route loads all item IDs from `history_store.load()` and passes them to `_history.bulk_recheck(ids)` — no new HistoryAPI helper needed

### Institutional Learnings

- CSRF guard is active on all POST routes (PR #143); `postForm` in api.js covers this via `csrf_token` form field.
- `readCsrf()` must be called per-request, never cached as a module const (CLAUDE.md).
- `delegate()` from dom.js is the approved pattern for `data-action` click handling; no inline `on*` handlers.
- `url_for('static', filename='...', v=asset_version)` required for cache-busting (CLAUDE.md).

## Key Technical Decisions

- **Synchronous POST over async queue**: `recheck_many()` already exists and is fast enough for the operator's scale (tens of items, not thousands). Introducing APScheduler job dispatch would add moving parts for no user-visible gain at this scale. If needed, async can be layered later as Unit 6.
- **`HistoryAPI.bulk_recheck(all_ids)` over calling `recheck_many` directly**: keeps the route thin (same as `ce_history_bulk_recheck`) and reuses the store-update + event-write path already proven in history screen tests.
- **Flash via URL params (not Flask `flash()`)**: consistent with the rest of the codebase; `_render` doesn't auto-inject flash, so the GET route reads `request.args` and passes `flash_type`/`flash_msg` to the template explicitly.
- **`window.location.href = resp.url` over `window.location.reload()`**: after the `fetch` follows the redirect, `resp.url` points to `/ce:keep-alive?flash_type=...&flash_msg=...`. Navigating there preserves the flash params; a plain reload would lose them.

## Open Questions

### Resolved During Planning

- *Does `HistoryAPI.bulk_recheck` accept an empty list safely?* — Likely yes (recheck_many short-circuits on empty input), but the route should guard `if not ids: redirect with info flash` to avoid a no-op network round-trip.
- *Does keep_alive template support flash display?* — Currently no. Unit 1 adds the flash alert block to the template and updates the GET route to read flash params.

### Deferred to Implementation

- *Maximum wait per URL* — `recheck_many` has a `max_wait_per_url` default; leave at default for this plan, tune in a later pass if timeouts surface.
- *What item statuses to include* — `HistoryAPI.bulk_recheck` filters internally; the route passes all IDs from `history_store.load()`.

## Implementation Units

- [ ] **Unit 1: Backend POST route + flash support**

**Goal:** Add `POST /ce:keep-alive/recheck` that triggers `HistoryAPI.bulk_recheck` for all items, redirects back to keep-alive with a flash summary. Also add flash display to the GET route + template.

**Requirements:** R1, R3, R4

**Dependencies:** None

**Files:**
- Modify: `webui_app/routes/keep_alive.py`
- Modify: `webui_app/templates/keep_alive.html`
- Test: `tests/test_webui_keep_alive_recheck.py`

**Approach:**
- In `keep_alive.py`, instantiate `HistoryAPI()` at module level (mirrors `history.py:18`).
- Add a `POST /ce:keep-alive/recheck` handler: load all item IDs from `history_store`, guard empty-list case, call `_history.bulk_recheck(ids)`, redirect to `/ce:keep-alive?flash_type=success&flash_msg=<result.flash_msg>`. The `flash_msg` comes from `RecheckSummary.as_flash()` which returns integer counters and enum strings only (e.g. "已核实 N 条：X 升为已发布，Y 标为失败，Z 跳过") — never echoes raw user input or stored URLs, so Jinja auto-escaping in the template is sufficient.
- Update the existing GET handler to read `flash_type` and `flash_msg` from `request.args` and pass them to `_render` (same pattern as `main.py:16-17`).
- In `keep_alive.html`, add a `{% if flash_msg %}` alert block in `{% block content %}` just below the `<nav>` — before `<main>`. Use `{{ flash_type }}` for the Bootstrap alert class (`alert-success`, `alert-warning`, etc.) and `{{ flash_msg }}` for the text. Escape via Jinja `{{ flash_msg }}` (auto-escaped in Jinja2).

**Patterns to follow:**
- Route pattern: `webui_app/routes/history.py:100-106` (bulk-recheck route)
- Flash params: `webui_app/routes/main.py:16-17`
- Flash template block: look at `index.html` or another template that already renders flash

**Test scenarios:**
- Happy path: POST with items in store → 302 redirect to `/ce:keep-alive?flash_type=success&...`
- Empty store: POST with no history items → 302 redirect with `flash_type=info` (no-op message)
- GET with flash params: `?flash_type=success&flash_msg=Checked+3` → flash alert visible in response HTML
- CSRF guard: POST without CSRF token → 400/403 (existing guard, just verify it applies)

**Verification:**
- `pytest tests/test_webui_keep_alive_recheck.py` passes
- The route appears in `flask routes` output
- Flash alert renders correctly on keep_alive page with flash params in URL

---

- [ ] **Unit 2: Enable button + wire JS handler**

**Goal:** Remove `disabled` from the recheck button; add a `data-action="recheck"` handler in `keep_alive.js` that shows a loading state, POSTs to the new route, and navigates to the redirect target URL.

**Requirements:** R1, R2

**Dependencies:** Unit 1 (route must exist before JS can POST to it)

**Files:**
- Modify: `webui_app/templates/keep_alive.html`
- Modify: `webui_app/static/js/keep_alive.js`

**Approach:**
- In `keep_alive.html`: remove `disabled` and update `title` to `"立即重新巡检所有外链"` on the `#recheckBtn` button.
- In `keep_alive.js`:
  - Add `delegate` to the import from `./lib/dom.js` (line 12 currently imports only `esc, qs`).
  - Add `import { readCsrf } from './lib/api.js';` — **do not** import `postForm`; `postForm` wraps `fetchJson` which throws on non-JSON (HTML redirect) responses, making `resp.url` unreachable.
  - Register a delegated click handler on `document.body` for `[data-action="recheck"]`:
    1. `evt.preventDefault()`
    2. Disable the button. Keep the `<i class="bi bi-arrow-repeat">` node visible; update only the trailing text node to `" 巡检中…"`. No spinner CSS needed.
    3. Build a `FormData`, append `csrf_token` via `readCsrf()` (called here, not cached).
    4. `const resp = await fetch('/ce:keep-alive/recheck', { method: 'POST', body: data, credentials: 'same-origin' })` — raw fetch returns the Response object with `.url` pointing to the final redirected URL.
    5. On resolved response (2xx/3xx after redirect): `window.location.href = resp.url` (preserves flash params in the final URL).
    6. On network rejection or non-OK response: re-enable the button, restore original text, navigate to `/ce:keep-alive?flash_type=danger&flash_msg=巡检失败，请重试` so the operator sees an explicit failure message.

**Patterns to follow:**
- Delegation: `lib/dom.js:33` — `delegate(root, type, selector, handler)`
- CSRF: `lib/api.js` — `readCsrf()` reads `<meta name="csrf-token">` at call time; append to `FormData` as `csrf_token` field (same transport as `postForm`, without the JSON-only guard)
- Raw fetch returning a redirect: use the `Response` object directly (not `fetchJson`/`postForm`) when the backend returns a redirect

**Test scenarios:**
- Button is not `disabled` in rendered template (HTML attribute absent)
- Button loading state: POST in-flight → button disabled, text shows "巡检中…" → on redirect completion, page navigates to flash URL
- Integration smoke: visiting `/ce:keep-alive`, clicking the button triggers a POST to `/ce:keep-alive/recheck` (covered by Unit 1 backend test + manual verification)

**Verification:**
- `#recheckBtn` has no `disabled` attribute in rendered HTML
- Button is clickable in the browser; during POST it shows "巡检中…" and disables; after redirect completes button state restores

## System-Wide Impact

- **New route added**: `POST /ce:keep-alive/recheck` — must be registered via the existing blueprint; no `__init__.py` changes needed since `keep_alive` blueprint already registers all routes in that module. Access is operator-only by design (WebUI defaults to loopback; off-loopback requires `BACKLINK_PUBLISHER_ALLOW_NETWORK=1`). No additional auth layer is added — consistent with all existing POST routes.
- **Interaction with events.db**: `bulk_recheck` writes `link.rechecked` events; these immediately affect `build_keepalive_view()` on the next GET, so the scorecard refreshes correctly after redirect.
- **Unchanged invariants**: `recheck_many` / `HistoryAPI.bulk_recheck` behavior is unchanged — this plan is purely a new call site.
- **CSRF**: same guard applies to the new POST route as to all existing POST routes (PR #143); no special wiring needed.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Slow recheck blocks HTTP thread | `max_wait_per_url` default is 10s/item; worst case ≈ N_items × 10s (e.g. 10 items → ~100s). Button shows "巡检中…" throughout. No Werkzeug server-side timeout, so request completes — it just takes time. Acceptable at operator scale (1–15 items). |
| `HistoryAPI.bulk_recheck` with empty list raises | Guard in route: if no IDs, redirect with `flash_type=info` and "无已发布条目可巡检" |
| Flash block absent from keep_alive.html shows nothing | Unit 1 adds it explicitly; test verifies presence |

## Sources & References

- **Origin document:** [docs/plans/2026-06-04-001-feat-internal-edition-lite-keepalive-plan.md](docs/plans/2026-06-04-001-feat-internal-edition-lite-keepalive-plan.md)
- Existing bulk recheck route: `webui_app/routes/history.py:100-106`
- Recheck service: `webui_app/services/recheck.py`
- HistoryAPI: `webui_app/api/history_api.py:174-203`
- JS lib: `webui_app/static/js/lib/api.js`, `webui_app/static/js/lib/dom.js`
