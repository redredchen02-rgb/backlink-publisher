---
title: "feat: AI Content Engine PRO Mode — close 4 wiring gaps"
type: feat
status: completed
date: 2026-06-04
claims: {}
---

# feat: AI Content Engine PRO Mode — close 4 wiring gaps

## Overview

PRO Mode UI（plan 010, completed）and the config sidecar bridge（plan 007, completed）are shipped.
Four wiring gaps remain that prevent the operator from seeing and using LLM-powered generation
end-to-end through the WebUI:

1. `article_system_prompt` is stored in `llm-settings.json` and consumed by the pipeline, but
   has no input field in the Settings page — the operator can't customize it via the UI.
2. After `/ce:generate`, plan preview cards show no badge for whether content came from the
   LLM or the template fallback. The operator can't tell if Pro Mode fired.
3. Banner / cover image generation IS wired to the pipeline via `_sync_image_gen_config`
   (already runs on every Settings save), but the generated `cover_image_url` is never
   rendered in the plan preview cards — success is invisible.
4. There is no per-row "Regenerate article" button. The only way to re-run LLM generation is
   to redo the entire `/ce:generate` form.

## Problem Frame

PRO Mode is functionally connected at the pipeline level (plans 007, 010). What remains is a
layer of UI wires: feedback that LLM fired, controls that expose the missing article system
prompt field, visibility into banner success, and a targeted "regenerate this row" action.

## Requirements Trace

- R1. `article_system_prompt` textarea is present in the Pro Mode collapse, saved by the route,
  and surfaced by the sidecar bridge to `LLMProviderConfig.article_system_prompt`.
- R2. Each plan preview card shows a `content_source` badge ("AI 生成" vs "模板").
- R3. When `cover_image_url` is present on a plan row, the plan preview card renders a
  thumbnail or link; absence is silent (no blank placeholder).
- R4. Each plan preview card has a "重新生成" button that POSTs to `/ce:regen-body`, receives
  new `content_markdown`, and replaces the card's preview and editor textarea.
- R5. `/ce:regen-body` returns `400 + llm_not_configured` when the LLM sidecar can't produce a
  provider, so the JS can surface a clear message without a 500.

## Scope Boundaries

- Image gen pipeline wiring (`_sync_image_gen_config`) is NOT changed — it is already
  implemented and called on every settings save. This plan only adds UI visibility.
- No changes to `schema.py` validation rules — `content_source` and `cover_image_url` are
  already pass-through fields (schema ignores unknown keys).
- No changes to `_LLM_DEFAULTS` template in `routes/llm.py` — `article_system_prompt` key
  already exists in `_LLM_DEFAULTS` with default `''`.
- Unit 4 regeneration only re-generates `content_markdown` (article body). It does not
  re-derive anchors, links, title, tags, or cover image.

## Context & Research

### Relevant Code and Patterns

- **`article_system_prompt` gap**: `routes/llm.py:200` `existing.update({})` saves `system_prompt`
  but not `article_system_prompt`. `settings_service.py:52` default dict includes it. The sidecar
  bridge in `config/parsers/llm.py` maps it to `LLMProviderConfig.article_system_prompt` — the
  core plumbing is complete; only the form field and save line are missing.
- **`content_source` gap**: `cli/plan_backlinks/_payload.py:144–166` forks on LLM vs template
  but doesn't emit a `content_source` key in the output dict. `pipeline_api.py:60` passes rows
  straight through as dicts — no mapping layer to update. `_tab_new.html:192` meta-info strip
  already holds per-row badges (word count, link count, cover-image-warning) — a `content_source`
  badge follows the same Jinja2 `{% if plan.content_source %}` pattern.
- **`cover_image_url` gap**: `_payload.py` populates `cover_image_url` and `cover_image_warning`
  in the returned dict. `_tab_new.html:196–202` checks `plan.cover_image_warning` (and shows a
  warning badge) but never checks `plan.cover_image_url`. The URL string is already in the row
  dict — it just needs a `{% if plan.cover_image_url %}` block to render.
- **Regenerate button gap**: No `/ce:regen-body` route exists. Pattern for the route:
  `routes/pipeline.py:130` `/ce:generate` handler — `load_config()` via `pipeline_api.py`. For
  per-row regen, calling `load_config()` directly in the route and instantiating
  `OpenAICompatibleProvider` (from `publishing/adapters/llm_anchor_provider.py:96`) is the
  established pattern (mirrors `routes/llm.py:322` test-generate flow).
- **index.js action dispatch**: `static/js/index.js` uses a `data-action → handler` dispatch
  table (lines 26–39). New `regen-body` action follows the same `(e, el) => handler(el.dataset.*)`
  pattern. `readCsrf()` from `static/js/lib/api.js` provides the CSRF token per call.
- **CSRF**: all JSON POST routes get the CSRF token from `<meta name="csrf-token">` via
  `readCsrf()` in `lib/api.js`. Never cache the token in a module-level const (frontend
  convention rule 4).

### Institutional Learnings

- `[[project-thin-webui-arch-refactor]]` — WebUI routes must stay thin; generation logic goes
  in services or delegates to core. For Unit 4, inline the LLM call in the route only if it is
  ≤30 lines; otherwise extract to `webui_app/services/`.
- `[[feedback-verify-risk-list-before-fixing]]` — image gen pipeline IS connected (confirmed
  via `_sync_image_gen_config`). The gap is visibility, not wiring.
- `[[webui-frontend-is-two-stacked-plans]]` — no inline `on*` handlers; all interactivity via
  `data-action` delegation.

## Key Technical Decisions

- **`content_source` emitted by `_payload.py`, not the WebUI layer**: the source of truth for
  whether LLM fired is in the core generation layer. Setting it at `pipeline_api.py` would require
  inferring from the body text, which is brittle. One extra key in `_payload.py` outputs it
  directly and cleanly.
- **`/ce:regen-body` accepts generation parameters from the client, not a session row index**:
  The session `plans_list` is not keyed by stable index (re-generate clears it). Accepting
  `{main_domain, anchors, language, topic}` from the client makes the route stateless and testable.
  These are non-sensitive display values already rendered in the template. LLM credentials always
  come from `load_config()` server-side — never from the client.
- **Thumbnail vs link for `cover_image_url`**: A small `<img>` tag with explicit max dimensions is
  safe (URL is operator-configured, not user-submitted). Use `loading="lazy"` + `max-height:80px`
  inline to avoid layout reflow.
- **`article_system_prompt` textarea placement**: inside the Pro Mode collapse, below the
  `use_article_gen` switch, with a short label. Consistent with `system_prompt` textarea above
  (same row width, same monospace font).

## Open Questions

### Resolved During Planning

- *Is image gen wiring missing?* → No; `_sync_image_gen_config` is called on every Settings save
  and writes to `config.toml [image_gen]`. The gap is that `cover_image_url` from the plan row is
  not rendered. Unit 3 adds that rendering.
- *Should `content_source` be added to `schema.py`?* → No. `schema.py` validates publish
  payloads for required fields and range checks. `content_source` is a planning-stage diagnostic
  field; adding it to the publish schema would widen the contract unnecessarily.
- *`/ce:regen-body` — should CSRF exemption apply?* → No. This route modifies session state
  (session plan content is updated by the JS-side swap). The app-level CSRF guard applies via the
  standard `<meta>` + `readCsrf()` flow.

### Deferred to Implementation

- Whether `article_system_prompt` needs a "reset to default" button (like `system_prompt` has one
  via `data-action="llm-reset-prompt"`). Add it only if the reset JS in `settings.js` is trivial
  to extend; otherwise leave it blank-to-reset.
- Exact CSS class for the `content_source` badge — use existing Bootstrap color tokens
  (`bg-success` for LLM, `bg-secondary` for template) unless design-review suggests otherwise.
- Whether `regen-body` spinner should block the whole card or just the button. Implementer
  judgment — matching the existing `_loadingOverlay` pattern is acceptable.

## Implementation Units

```
Unit 1  ──────────────────────────────────── article_system_prompt field
Unit 2  ──────────────────────────────────── content_source badge
Unit 3  ──────────────────────────────────── cover_image_url in preview
Unit 4  ──────────────────────────────────── regen-body button + route
```

All four units are independent and can be executed in any order. Units 1–3 are pure
template/route additions; Unit 4 is the only unit that adds a new route.

---

- [x] **Unit 1: `article_system_prompt` — textarea in Settings + route persistence**

**Goal:** Expose the `article_system_prompt` field in the Pro Mode collapse so the operator can
customize the article generation system prompt from the WebUI.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `webui_app/templates/_settings_llm_integration.html`
- Modify: `webui_app/routes/llm.py` (`settings_save_llm_config`)
- Test: `tests/test_webui_llm_settings_save.py` (extend existing or add new cases)

**Approach:**
- In `_settings_llm_integration.html`, inside `#llm-pro-mode-collapse` body, after the
  `use_article_gen` form-switch div, add a `<div class="mt-3">` containing:
  - Label: "文章生成系统提示词 (Article System Prompt)"
  - `<textarea name="article_system_prompt" rows="3" class="form-control"
    style="font-size:12px;font-family:monospace;" placeholder="留空则使用内置默认...">
    {{ llm_settings.article_system_prompt }}</textarea>`
- In `routes/llm.py` `settings_save_llm_config`, inside the `existing.update({...})` block
  (around line 198), add:
  `'article_system_prompt': request.form.get('article_system_prompt', ''),`
  **Blank = clear semantic**: do NOT use `or existing.get(...)` fallback here. An empty textarea
  means the operator wants to revert to the built-in default — the pipeline treats empty string as
  "use default". This differs from `api_key` (where blank legitimately means "don't change").
- No changes to `_LLM_DEFAULTS` (key already present with default `''`).
- No changes to the sidecar bridge or `LLMProviderConfig` — they already carry the field.

**Patterns to follow:**
- `_settings_llm_integration.html` — existing `<textarea name="system_prompt">` is the direct
  parallel (same template, same card, same style).
- `routes/llm.py:200` — `'system_prompt': request.form.get('system_prompt', ...)` for the save
  pattern.

**Test scenarios:**
- Happy path: save a non-empty `article_system_prompt` → reload settings → textarea shows
  saved value.
- Happy path: save blank `article_system_prompt` → reload → textarea is empty (no fallback to
  `system_prompt` value).
- Edge case: save settings with `article_system_prompt` containing newlines and special chars →
  round-trip preserves the value unchanged.
- Integration: `load_config().llm_anchor_provider.article_system_prompt` reflects the value
  saved via the route (via sidecar bridge), when no TOML `[llm.anchor_provider]` is present.

**Verification:**
- `/settings` page loads without error; Pro Mode collapse shows the new textarea.
- Save → reload cycle preserves the value.
- `cat ~/.config/backlink-publisher/llm-settings.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('article_system_prompt'))"` returns the saved value.

---

- [x] **Unit 2: `content_source` badge — show LLM vs. template in plan preview**

**Goal:** Each plan preview card displays a small badge indicating whether `content_markdown`
was generated by the LLM ("AI 生成") or fell back to the template ("模板"), letting the operator
confirm Pro Mode fired.

**Requirements:** R2

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/cli/plan_backlinks/_payload.py`
- Modify: `webui_app/templates/_tab_new.html`
- Test: `tests/test_plan_backlinks_payload.py` (extend; assert `content_source` key in output)

**Approach:**
- In `_payload.py` generation fork (around line 144):
  - LLM success branch: set `content_source = "llm"` after assigning `body`
  - LLM exception fallback branch: set `content_source = "template"`
  - No-LLM branch (else at line 163): set `content_source = "template"`
- Ensure `content_source` is included in the returned payload dict (wherever the dict is
  assembled; the existing dict literal or dataclass that carries `content_markdown`).
- In `_tab_new.html` meta-info strip (around line 192–201), add after the word-count span:
  ```html
  {% if plan.content_source == 'llm' %}
  <span class="badge bg-success" style="font-size:10px;"
        data-content-source="{{ loop.index0 }}">✦ AI 生成</span>
  {% elif plan.content_source == 'template' %}
  <span class="badge bg-secondary" style="font-size:10px;"
        data-content-source="{{ loop.index0 }}">模板</span>
  {% endif %}
  ```
  The `data-content-source` attribute gives the Unit 4 JS regen handler a stable target to update
  the badge after a successful regen call (no full-page reload needed).
- `pipeline_api.py` passes rows through untouched — no change needed.

**Patterns to follow:**
- `_tab_new.html:196–202` — existing `cover_image_warning` badge as the template for inline
  conditional badge rendering.
- `_payload.py:144–166` — the existing LLM/template fork; add one assignment per branch.

**Test scenarios:**
- Happy path — LLM configured and `use_article_gen=True`: generated row dict contains
  `content_source == "llm"`.
- Happy path — LLM configured but `use_article_gen=False`: `content_source == "template"`.
- Error path — LLM call raises exception: `content_source == "template"` (fallback branch).
- Edge case — no LLM provider: `content_source == "template"`.
- Integration (UI): `/ce:generate` with LLM configured → preview page shows "✦ AI 生成" badge
  on each card. Without LLM → shows "模板".

**Verification:**
- `pytest tests/test_plan_backlinks_payload.py` passes with `content_source` assertions.
- Plan preview cards show the correct badge after a fresh `/ce:generate`.

---

- [x] **Unit 3: `cover_image_url` — wire banner output to preview thumbnail**

**Goal:** When the banner generator runs and produces an output, expose that as `cover_image_url`
in the plan row dict so the preview card can render a thumbnail/link.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Modify: `webui_app/api/pipeline_api.py` (map `banner` field to `cover_image_url` in row post-processing)
- Modify: `webui_app/templates/_tab_new.html`

**Approach:**
- In `pipeline_api.py`, after parsing JSONL rows (in `PipeResult.rows` property or `_parse_jsonl_rows`),
  check each row for a `banner` key. `_engine.py:292–298` writes `payload['banner']` as a local
  file path. Decide at implementation: if `banner` is an absolute path on disk, derive a
  `/static/banners/filename` URL (requires banner output dir to be under `static/`), or surface it
  via a dedicated `/banner/<filename>` route. Either way, set `row['cover_image_url']` from
  `row.get('banner', None)` after confirming the file is web-accessible.
  **Note:** if the banner file path is not under `static/`, Unit 3 must add a small
  `@bp.route('/banner/<path:fname>')` route in `routes/pipeline.py` that streams the file.
- In `_tab_new.html`, inside the `.result-card` for each plan row, after the `cover_image_warning`
  badge block and before the `<details>` content preview, add:
  ```html
  {% if plan.cover_image_url and plan.cover_image_url.startswith('https://') %}
  <div class="mt-2" style="font-size:12px;">
    <i class="bi bi-image me-1 text-success"></i>封面图已生成：
    <a href="{{ plan.cover_image_url }}" target="_blank" rel="noopener"
       style="color:var(--primary);">查看</a>
    <img src="{{ plan.cover_image_url }}" alt="cover"
         loading="lazy" style="display:block;max-height:80px;margin-top:4px;
                               border-radius:4px;border:1px solid #e5e7eb;">
  </div>
  {% endif %}
  ```
- The existing `{% if plan.cover_image_warning %}` block is NOT modified — warning and success
  can co-exist (e.g. banner generated but with a fallback prompt).

**Patterns to follow:**
- `_tab_new.html:196–202` cover_image_warning badge block — directly adjacent location.
- `_tab_result.html` / `result.html` article_url display (same `<a href target="_blank">`
  pattern).

**Test scenarios:**
- Happy path: `plan.cover_image_url` is a valid https URL → thumbnail and "查看" link render.
- Edge case: `plan.cover_image_url` is `None` or absent → no thumbnail block rendered.
- Edge case: `plan.cover_image_warning` is also set → both warning badge and thumbnail render.
- Edge case: `plan.cover_image_url` is present but `plan.cover_image_warning` is absent → only
  thumbnail renders (no warning badge).

**Verification:**
- Plan preview with a row that has `cover_image_url` shows the thumbnail and link.
- Plan preview with a row that has no `cover_image_url` shows no thumbnail (no blank box).

---

- [x] **Unit 4: Per-row "重新生成" button + `/ce:regen-body` route**

**Goal:** Add a "重新生成" button to each plan preview card. Clicking it calls a new backend
route that re-generates the article body via the configured LLM and replaces the card's preview
and editor textarea in-place, without re-running the full plan pipeline.

**Requirements:** R4, R5

**Dependencies:** LLM must be configured (soft dependency — graceful 400 when not configured).

**Files:**
- Modify: `webui_app/routes/pipeline.py` (add `/ce:regen-body` route)
- Modify: `webui_app/templates/_tab_new.html` (add button per row)
- Modify: `webui_app/static/js/index.js` (add `regen-body` to CLICK_ACTIONS dispatch table)
- Modify: `webui_app/static/js/lib/profiles.js` (add `regenBody` method to `createConfigForm` return object)
- Test: `tests/test_webui_regen_body.py` (new)

**Approach:**

*Backend route (`routes/pipeline.py`):*
- New route: `@bp.route('/ce:regen-body', methods=['POST'])`
- Accept JSON body `{ main_domain: str, anchors: [str], language: str, topic: str | null }`
- Server-side: call `load_config()` (which picks up the LLM sidecar); check
  `cfg.llm_anchor_provider` and `cfg.llm_anchor_provider.use_article_gen`; return `400` with
  `{"error": "llm_not_configured", "detail": "..."}` if absent.
- Derive `domain_label` server-side: `from backlink_publisher.cli.plan_backlinks._templates import
  _domain_label_of`; `domain_label = _domain_label_of(main_domain)`. This mirrors `_payload.py:103`
  and produces the hostname label (e.g. `51acgs.com`) that the LLM prompt expects.
- Instantiate `OpenAICompatibleProvider(base_url=..., api_key=..., model=..., temperature=...,
  article_system_prompt=...)` from `cfg.llm_anchor_provider`.
- Call `provider.generate_article_body(domain_label=domain_label, main_domain=main_domain,
  anchors=anchors, topic=topic, language=language)`.
- Return `{"content_markdown": body, "content_html": rendered_html, "content_source": "llm"}` on
  success, where `rendered_html = render_to_html(body)` (import from
  `backlink_publisher._util.markdown`). This lets the JS swap server-rendered HTML into the
  preview div without client-side markdown parsing.
- On `Exception`: return `502 {"error": "llm_call_failed", "detail": _redact_for_log(str(exc))}`.
- Import: `from backlink_publisher.publishing.adapters.llm_anchor_provider import
  OpenAICompatibleProvider` (lazy import inside the route function, matching `routes/llm.py:322`
  pattern).
- Exception redaction: `from backlink_publisher.llm.client import _redact_for_log` (this is
  where `_redact_for_log` is defined — NOT in `llm_anchor_provider.py`). Call
  `detail = _redact_for_log(str(exc))` before returning the 502 `detail` field.
- `load_config()` import: already used in `pipeline_api.py`; route can import from
  `backlink_publisher.config`.
- CSRF: enforced by the app-level `_global_csrf_guard`; no explicit per-route CSRF check needed.
- All error responses follow: `{"error": "<error_code>", "detail": "<optional message>"}`.
  Supported codes: `bad_request` (400), `llm_not_configured` (400), `llm_call_failed` (502).

*Template (`_tab_new.html`):*
- Inside the inline-editor `<div>` (around line 220), after the "编辑内容" button, add:
  ```html
  <button type="button" class="btn btn-sm btn-outline-success"
          data-action="regen-body"
          data-idx="{{ loop.index0 }}"
          data-domain="{{ plan.main_domain }}"
          data-language="{{ plan.language }}"
          data-topic="{{ plan.topic | default('') }}"
          data-anchors='{{ plan.links | selectattr("anchor") | map(attribute="anchor") | list | tojson }}'
          id="regenBtn-{{ loop.index0 }}">
    <i class="bi bi-stars me-1"></i>重新生成
  </button>
  <small id="regenStatus-{{ loop.index0 }}" class="text-muted ms-2" style="line-height:30px;"></small>
  ```
- Button is placed in the always-visible action area (alongside "编辑内容" button, BEFORE
  the collapsible `<div id="editor-{idx}" style="display:none">`) so it is visible without
  opening the editor.
- `data-topic` carries the plan row's topic for the LLM call (prevents context drift).
- `selectattr("anchor")` filters out null/missing anchor keys before `tojson`.

*JavaScript — add `regenBody` to `static/js/lib/profiles.js`:*
- `regenBody` belongs in `profiles.js`'s `createConfigForm` return object (alongside `saveEdit`,
  `cancelEdit`, etc.). `profiles.js` already imports `readCsrf` from `./api.js` — no new import
  needed.
- In `index.js`, add to CLICK_ACTIONS dispatch table:
  `'regen-body': (e, el) => cf.regenBody(el.dataset.idx, el.dataset.domain,
    el.dataset.language, JSON.parse(el.dataset.anchors), el.dataset.topic || null)`
- `regenBody(idx, domain, language, anchors, topic)` in `profiles.js`:
  1. Disable `#regenBtn-{idx}` and show spinner icon.
  2. POST to `/ce:regen-body` with `Content-Type: application/json`, `X-CSRFToken: readCsrf()`,
     body `{main_domain: domain, anchors, language, topic}`.
  3. On success: update `#editorArea-{idx}` value with `data.content_markdown`;
     update `#preview-{idx}` innerHTML with `data.content_html` (server-rendered HTML);
     update `[data-content-source="${idx}"]` element class and text based on `data.content_source`
     (Unit 2 badge — see Unit 2 template note below);
     set `#regenStatus-{idx}` to "✓ 已重新生成".
  4. On `llm_not_configured` 400: set status to "⚠ LLM 未配置".
  5. On other error: set status to "✗ 生成失败".
  6. Re-enable button.

**Execution note:** Add the route test first (failing: `POST /ce:regen-body` without LLM config
returns 400 `llm_not_configured`), then implement the route, then add the template button and JS.

**Patterns to follow:**
- `routes/llm.py:322` — lazy `OpenAICompatibleProvider` import and `generate_article_body` call.
- `routes/copilot.py:109` — `_load_llm_settings()` → graceful 400 when not configured (same
  JSON error shape: `{error: str, detail: str}`).
- `static/js/index.js:26–39` — `data-action` dispatch table pattern.
- `static/js/lib/api.js` — `readCsrf()` call for JSON POSTs.

**Test scenarios:**
- Happy path — sidecar-only operator (no TOML, no env): sidecar has valid credentials +
  `use_article_gen=True` → `200 {"content_markdown": "...", "content_html": "...", "content_source": "llm"}`.
  This is the PRIMARY test — most operators never set TOML `[llm.anchor_provider]`.
- Happy path — `topic` provided: `topic` forwarded to `generate_article_body`, response contains
  topic-relevant content.
- Error path — `llm_not_configured`: no TOML, no sidecar → `400 {"error": "llm_not_configured"}`.
- Error path — `use_article_gen=False`: sidecar present but toggle off →
  `400 {"error": "llm_not_configured", "detail": "use_article_gen is disabled"}`.
- Error path — LLM call raises `Exception`: `502 {"error": "llm_call_failed", "detail": "..."}`;
  assert the test API key (`sk-test-secret`) does NOT appear in `detail`.
- Edge case — blank/missing `main_domain` or `anchors`: `400 {"error": "bad_request"}`.
- Integration (UI): button click triggers spinner, replaces preview content, shows status message.

**Verification:**
- `pytest tests/test_webui_regen_body.py` passes.
- Manual: plan preview shows "重新生成" button; click fires request; preview content updates;
  status message appears; button re-enables.

## System-Wide Impact

- **Interaction graph:** Units 1–3 touch only templates and one route save function — no
  callbacks, middleware, or observers are affected. Unit 4 adds a new route that calls
  `load_config()` (cached per request via `_g_cache`) and `OpenAICompatibleProvider` — no new
  singletons, no new shared state.
- **`content_source` schema impact:** The field is added to `plan_rows()` output dicts. It
  is an unknown key to `schema.py` validate (which only checks the fields it knows about), so
  validation is unaffected. Downstream publish pipeline ignores unknown plan fields.
- **CSRF surface:** `/ce:regen-body` is a new POST endpoint. The app-level `_global_csrf_guard`
  covers it automatically (it covers all POST/PUT/PATCH/DELETE in `webui_app/__init__.py`).
  No per-route exemption is needed.
- **Unchanged invariants:** The publish pipeline (`/ce:publish`), validate route, batch tab,
  and all channel adapters are untouched. `article_system_prompt` saving does not change any
  publish-path behavior — it only updates the value the sidecar bridge reads on the next
  `load_config()` call.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `article_system_prompt` save overwrites existing value with blank on partial-edit | Mirror `system_prompt` pattern: `request.form.get('article_system_prompt', '') or existing.get('article_system_prompt', '')` — blank form field preserves stored value |
| `content_source` key absent in rows from old JSONL session data (browser has stale plan) | `{% if plan.content_source == 'llm' %}` and `{% elif plan.content_source == 'template' %}` — absent key renders nothing; no crash |
| `cover_image_url` is a relative URL or data-URI from an unusual image provider | `<img loading="lazy">` handles any valid URL; use `max-height:80px` to prevent layout explosion |
| Unit 4 regen route returns API key in exception detail | `from backlink_publisher.llm.client import _redact_for_log` (defined there, not in `llm_anchor_provider`); `detail = _redact_for_log(str(exc))` |
| Unit 4 `data-anchors` Jinja2 attribute injection | `tojson` filter HTML-escapes the JSON string for safe embedding in an HTML attribute value |

## Documentation / Operational Notes

- After landing: `/ce:generate` plan cards show "✦ AI 生成" when Pro Mode fires and "模板"
  otherwise. If an operator sees "模板" unexpectedly, they should check `/settings` → AI 内容生成
  引擎 → Pro Mode → ensure `use_article_gen` is checked and LLM credentials are valid.
- The `cover_image_url` thumbnail only renders when the publish pipeline's banner generator
  ran (requires `config.toml [image_gen] use_image_gen = true` — set by enabling and saving
  the image gen toggle in Settings).
- `/ce:regen-body` makes a live LLM call per click; it is not free. The operator should treat
  it as a manual override for unsatisfactory content, not a batch-refresh trigger.
- **Session persistence**: `/ce:regen-body` updates the client-side display only — it does NOT
  write back to the server-side Flask session. A subsequent `/ce:publish` will use the original
  generated body from the session, not the regenerated one. Operators who want to publish the
  regenerated body should copy-edit the textarea content and use the "确认修改" flow, which
  POSTs the edited content back via the existing edit-save path.

## Sources & References

- Prior plans: `docs/plans/2026-05-28-010-feat-llm-pro-mode-collapse-plan.md` (Pro Mode UI)
- Prior plans: `docs/plans/2026-05-29-007-feat-llm-settings-pipeline-bridge-plan.md` (sidecar bridge)
- Core LLM generation: `src/backlink_publisher/publishing/adapters/llm_anchor_provider.py:96`
- Article gen fork: `src/backlink_publisher/cli/plan_backlinks/_payload.py:144–166`
- Settings route: `webui_app/routes/llm.py:135` `settings_save_llm_config`
- Pro Mode template: `webui_app/templates/_settings_llm_integration.html`
- Plan preview template: `webui_app/templates/_tab_new.html`
- Index JS dispatcher: `webui_app/static/js/index.js:26–39`
- Copilot ask pattern (graceful 400): `webui_app/routes/copilot.py:109`
