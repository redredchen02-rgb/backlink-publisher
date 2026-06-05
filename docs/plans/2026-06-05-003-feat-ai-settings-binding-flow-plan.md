---
title: "feat: Fix AI settings binding UX flow (AI 全文生成 / AI 封面图)"
type: feat
status: active
date: 2026-06-05
---

# feat: Fix AI settings binding UX flow (AI 全文生成 / AI 封面图)

## Overview

`_settings_llm_status.html` 顯示 `○ AI 全文生成` 和 `○ AI 封面图` 為待啟用狀態，但用戶無法從這裡直接進行綁定操作。實際控制項藏在預設折疊的「Pro Mode AI 生成」collapse 裡；AI 封面圖的開關又排在必填欄位之後；驗證失敗後重導回頁面時 collapse 再次關閉，用戶完全無法看到失敗原因。本計畫在不改動後端路由邏輯的前提下，修復三個 UI 層面的缺口，讓這兩個設定可以被順利啟用。

## Problem Frame

用戶在設定頁看到：

```
○ AI 全文生成   ← 未啟用，但沒有任何引導動作
○ AI 封面图     ← 未啟用，但沒有任何引導動作
```

要啟用這兩項，必須：
1. 找到並手動點擊折疊觸發器「Pro Mode AI 生成」
2. 對封面圖：先填 API Key / Endpoint / Model，再向下捲動找到 checkbox

這三個摩擦點加在一起，讓用戶認為「這個功能沒辦法綁定」。

## Requirements Trace

- R1. 點擊 `○ AI 全文生成` 應自動展開 Pro Mode collapse 並滾動到對應控制項
- R2. 點擊 `○ AI 封面图` 應自動展開 Pro Mode collapse 並滾動到封面圖欄位
- R3. 當 LLM 基礎已配置（endpoint + api_key 非空）且 Pro Mode 項目尚未啟用時，collapse 應自動展開
- R4. `use_image_gen` checkbox 應排在封面圖欄位最前面（主開關在前，細節在後）
- R5. 驗證失敗後重導回頁面時，Pro Mode collapse 應維持展開狀態

## Scope Boundaries

- 不改動 `webui_app/routes/llm.py` 後端路由邏輯（保存、驗證、`_sync_image_gen_config` 不變）
- 不改動 `webui_app/services/settings_service.py`
- 不新增 JS 模組；所有 JS 直接寫在 template 的 `<script>` 區塊（符合 zero-build 前端慣例）
- 不改動 `_settings_banner.html`（image_gen 的 pipeline 側狀態顯示不在本計畫範圍）

## Context & Research

### Relevant Code and Patterns

- `webui_app/templates/_settings_llm_status.html` — 狀態卡，`○` items 的定義點
- `webui_app/templates/_settings_llm_integration.html:89-140` — Pro Mode collapse + 兩個 checkbox + 封面圖欄位
- `webui_app/routes/llm.py:191-200` — 封面圖驗證：`use_image_gen=True` 時 endpoint + model 必填且 https://
- `webui_app/routes/llm.py:219` — `_safe_flash_redirect(..., fragment='sect-ai')` — 驗證失敗後跳回 `#sect-ai`
- `webui_app/services/settings_service.py:85-120` — `pro_status_summary()` 返回 `ps.configured`、`ps.article_gen`、`ps.image_gen`
- 現有 collapse 展開模式：`_settings_llm_integration.html:97` — `class="collapse{% if llm_settings.use_article_gen or llm_settings.use_image_gen %} show{% endif %}"`
- 前端慣例：no inline `on*` handlers，用 `data-action` 或 delegated `addEventListener`；JS 在 template script 區塊（已有先例：`settings.html` 底部多個 inline `<script>`）

### Institutional Learnings

- 前端 zero-build 原則：不引入 bundler，不用 `window.*` globals，用 DOM CustomEvent 跨元件通訊
- `readCsrf()` 每次從 `<meta>` 讀取，不 cache（本計畫無 CSRF 需求，可忽略）
- Bootstrap 的 collapse API：`bootstrap.Collapse.getOrCreateInstance(el).show()` 可程式化展開

## Key Technical Decisions

- **CTA 用 `<button type="button">` 而非 `<a href>`**：避免觸發頁面跳轉或 anchor 滾動造成雙重動作；由 JS 控制 collapse 展開 + `scrollIntoView()`。理由：`<a href="#sect-ai">` 會觸發原生 anchor 跳轉，無法同步展開 collapse。
- **R3 自動展開條件在 Jinja 層判斷**：`llm_settings.endpoint and llm_settings.api_key` 已在 template context 中，不需要額外 route 支援。直接在 collapse class 的 Jinja 判斷中加入此條件，保持邏輯一致。
- **R4 `use_image_gen` 移到頂端 + 欄位 conditional display**：用 JS `change` 事件 + CSS `display:none/block` 控制欄位可見性（不用 Bootstrap collapse 包裝欄位，避免額外嵌套 collapse 引入的 aria 複雜度）。
- **R5 flash error 時自動展開**：在 template 中判斷 `get_flashed_messages()` 是否有 danger 訊息且包含 image/LLM 關鍵字；或更簡單地：只要 `sect-ai` anchor 出現在 URL hash（無法從 Jinja 讀）就用 JS 判斷 `location.hash === '#sect-ai'` 在 DOMContentLoaded 時展開 collapse。這不需要改動 route。

## Open Questions

### Resolved During Planning

- **Q: 需要新增 JS 模組嗎？** A: 否。行為簡單（展開 collapse + scrollIntoView），直接在 template `<script>` 區塊撰寫，符合現有前端慣例。
- **Q: R4 的 checkbox 移位會影響 POST form 的欄位順序嗎？** A: 不影響。`name="use_image_gen"` 的語義由 `routes/llm.py` 用 `'use_image_gen' in request.form` 判斷，與 DOM 位置無關。

### Deferred to Implementation

- 如果 `_settings_llm_integration.html` 的 `use_image_gen` checkbox 移位後在行動裝置版型有對齊問題，修正 Bootstrap col class 留給實作時調整。

## Implementation Units

- [ ] **Unit 1: 狀態卡 `○` items 改為可點擊 CTA**

**Goal:** `○ AI 全文生成` 和 `○ AI 封面图` 從靜態文字變成可點擊按鈕，點擊後展開 Pro Mode collapse 並滾動到對應位置，滿足 R1、R2。

**Requirements:** R1, R2

**Dependencies:** 無

**Files:**
- Modify: `webui_app/templates/_settings_llm_status.html`

**Approach:**
- 將 `li` 內的純文字改為 `<button type="button" class="btn btn-link p-0 text-decoration-none …" data-expand-pro-mode data-target-id="useArticleGen">` 形式
- 對應 `data-target-id` 為 `useArticleGen`（全文生成）和 `useImageGen`（封面圖）
- 只對 `○`（未啟用）狀態的 item 加按鈕；`✓` 狀態保持純文字（已啟用無需引導）
- 在 template 底部 `<script>` 中：`document.querySelectorAll('[data-expand-pro-mode]')` delegated 監聽；點擊時：① `bootstrap.Collapse.getOrCreateInstance(document.getElementById('llm-pro-mode-collapse')).show()` ② `document.getElementById(targetId).scrollIntoView({behavior: 'smooth', block: 'center'})`

**Patterns to follow:**
- `_settings_llm_integration.html:89` 的 Pro Mode toggle 按鈕樣式
- 現有 settings.html 底部 inline `<script>` 模式

**Test scenarios:**
- Happy path: 點擊 `○ AI 全文生成` → Pro Mode collapse 展開 → 頁面滾動到 `#useArticleGen` checkbox 可見
- Happy path: 點擊 `○ AI 封面图` → Pro Mode collapse 展開 → 頁面滾動到 `#useImageGen` checkbox 可見
- Edge case: Pro Mode collapse 已展開時點擊 CTA → 不應再次收合，只滾動
- Edge case: `✓ AI 全文生成`（已啟用）的 item 不應渲染為按鈕

**Verification:**
- 在 `ps.configured = True, ps.article_gen = False` 狀態下，`○ AI 全文生成` 為可點擊元素
- 點擊後 `#llm-pro-mode-collapse` 有 `show` class
- 已啟用項保持 `✓` 純文字

---

- [ ] **Unit 2: Pro Mode collapse 智能預設展開**

**Goal:** 當 LLM 基礎配置完成（endpoint + api_key 非空）但 Pro Mode 項目尚未啟用時，collapse 預設為展開狀態，降低發現成本；驗證失敗後 hash 跳回 `#sect-ai` 時也自動展開，滿足 R3、R5。

**Requirements:** R3, R5

**Dependencies:** Unit 1（UI 一致性，不強依賴）

**Files:**
- Modify: `webui_app/templates/_settings_llm_integration.html`

**Approach:**
- Jinja collapse class 邏輯從：
  `"collapse{% if llm_settings.use_article_gen or llm_settings.use_image_gen %} show{% endif %}"`
  改為：
  `"collapse{% if llm_settings.use_article_gen or llm_settings.use_image_gen or (llm_settings.endpoint and llm_settings.api_key) %} show{% endif %}"`
- 這讓「LLM 已配置但 Pro Mode 未啟用」的用戶看到 collapse 預設打開
- R5（flash error 時）：在 template 底部 `<script>` 加：`if (location.hash === '#sect-ai') { bootstrap.Collapse.getOrCreateInstance(document.getElementById('llm-pro-mode-collapse')).show() }`，在 `DOMContentLoaded` 時執行

**Patterns to follow:**
- `_settings_llm_integration.html:90` 的 `aria-expanded` Jinja 判斷（同步更新 aria attribute）

**Test scenarios:**
- Happy path: `endpoint` 非空、`api_key` 非空、`use_article_gen = False`、`use_image_gen = False` → collapse 預設 `show`
- Happy path: 驗證失敗，redirect 到 `/settings#sect-ai` → JS 偵測到 hash，展開 collapse
- Edge case: `endpoint` 為空（LLM 未配置）→ collapse 維持折疊（現有行為不變）
- Edge case: `use_article_gen = True` → collapse 展開（已有行為，不應回歸）

**Verification:**
- 有 LLM config 但 Pro Mode 未啟用的頁面載入：`#llm-pro-mode-collapse` 有 `show` class
- 無 LLM config 時：collapse 為折疊狀態

---

- [ ] **Unit 3: 重排 AI 封面圖欄位，checkbox 提前**

**Goal:** 把 `use_image_gen` checkbox（主開關）移到封面圖區塊最上方；當 checkbox 未勾選時，endpoint / model / api_key / size 欄位隱藏，引導用戶先決策「是否啟用」再填細節，滿足 R4。

**Requirements:** R4

**Dependencies:** Unit 2（collapse 展開後才能看到 checkbox）

**Files:**
- Modify: `webui_app/templates/_settings_llm_integration.html`

**Approach:**
- 將 `_settings_llm_integration.html:136-138` 的 `use_image_gen` form-check 移到 `<label>AI Cover Image Generation...</label>` 之後、`input-group mb-2`（API Key 行）之前
- 在 API Key / Endpoint / Model / Size 欄位的外包 `<div>` 加 `id="image-gen-fields"` + inline style `display:{% if llm_settings.use_image_gen %}block{% else %}none{% endif %}`
- 在 template 底部 `<script>`：
  ```
  const cb = document.getElementById('useImageGen');
  const fields = document.getElementById('image-gen-fields');
  cb.addEventListener('change', () => { fields.style.display = cb.checked ? 'block' : 'none'; });
  ```
- 勾選 checkbox 後欄位出現，用戶填完後一起 POST —— 順序與 `routes/llm.py` 讀取 `request.form` 完全相容（只要 `name` attribute 不變）

**Patterns to follow:**
- 現有 `id="useArticleGen"` checkbox 的 form-switch 樣式，保持視覺一致
- inline `display:none/block` 控制（不用 Bootstrap collapse，避免額外嵌套）

**Test scenarios:**
- Happy path: 頁面載入，`use_image_gen = False` → checkbox 未勾，欄位隱藏
- Happy path: 勾選 checkbox → 欄位立即顯示（JS，不需重載）
- Happy path: 頁面載入，`use_image_gen = True` → checkbox 已勾，欄位可見
- Happy path: 填入 endpoint / model / api_key 後勾選 checkbox，POST → 保存成功
- Edge case: 勾選 checkbox 後不填 endpoint/model → POST → 後端回傳 400，collapse 重新展開（R5 已保障）
- Error path: 取消勾選 checkbox → 欄位消失 → POST → `use_image_gen = False` 保存，後端不做驗證

**Verification:**
- `use_image_gen = False` 時，`image-gen-fields` div 的 `display` 為 `none`
- checkbox `change` 事件觸發後欄位可見性立即切換
- 勾選並填入合法 endpoint（`https://...`）+ model 後保存 → 200 redirect，`ps.image_gen = True`

## System-Wide Impact

- **Template-only changes:** 所有改動限於三個 template 檔案的 HTML + inline `<script>`；無路由、服務、或 store 變更。
- **Bootstrap API 依賴:** `bootstrap.Collapse.getOrCreateInstance()` 是 Bootstrap 5 的穩定 API（codebase 已引入 Bootstrap 5），無版本風險。
- **Unchanged invariants:** `routes/llm.py` 的 POST 處理、驗證邏輯、`_sync_image_gen_config()`、`_write_llm_settings()` 完全不動；`pro_status_summary()` 不動；`_settings_banner.html` 不動。
- **狀態一致性:** `ps.image_gen` 仍由 `llm-settings.json` 的 `use_image_gen` 驅動（非 `config.toml`）；若用戶想確認 pipeline 側生效，仍需看 `_settings_banner.html` 中的 image_gen_status — 本計畫不改變此設計。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 3 的欄位隱藏造成 POST 時缺欄位 | `name` attribute 在隱藏狀態仍會送出（hidden 欄位仍在 DOM 中），只是 `display:none`；`request.form` 仍能讀到所有欄位 |
| Bootstrap collapse 在某些狀態下 `.show()` 二次呼叫導致動畫問題 | 使用 `getOrCreateInstance` 而非 `new Collapse()`；`location.hash` 判斷只在頁面載入時執行一次 |
| Jinja 條件修改讓未設 endpoint 但已選 `use_article_gen` 的狀態出現雙重展開 | 雙重展開無害；條件只影響 `show` class 是否加入，結果相同 |

## Sources & References

- Related code: `webui_app/templates/_settings_llm_status.html`
- Related code: `webui_app/templates/_settings_llm_integration.html:89-140`
- Related code: `webui_app/routes/llm.py:191-219`
- Related code: `webui_app/services/settings_service.py:85-120`
- Bootstrap 5 Collapse API: `bootstrap.Collapse.getOrCreateInstance()`
