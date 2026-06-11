---
title: "feat: Add Hatena token-fields binding button to WebUI settings"
type: feat
status: completed
date: 2026-06-05
---

# feat: Add Hatena token-fields binding button to WebUI settings

## Overview

Hatena 的後端 adapter（`hatena_atompub.py`）已完整存在並已 `register()`，但 WebUI 設定頁目前渲染「字段配置尚未定义」警告框，因為三個地方缺少 Hatena 條目：token save 函數、credential dispatch、template 字段定義。本計畫補齊這三個純加法條目，讓用戶在設定頁展開 Hatena 手風琴卡片後，能直接填入 `hatena_id`/`blog_id`/`api_key` 並保存憑證完成綁定。

## Problem Frame

Hatena 使用 `auth_type="token_fields"`（AtomPub + WSSE，讀取 `hatena-credentials.json`），走的是 HTML form POST 路徑，**不走** Playwright browser-login 流程。設定頁 `_settings_cardless_channels.html` 已透過 `auth_type == 'token_fields'` 自動路由到 `_settings_binding_token_fields.html`，但後者的 `_FIELD_DEFS` dict 沒有 `"hatena"` key，導致 fallback 到警告框。保存路由 `save_token_fields()` 在 `_TOKEN_FIELDS_DISPATCH` 中也找不到 `"hatena"`，整條綁定流程均斷裂。

## Requirements Trace

- R1. 在設定頁展開 Hatena 卡片後，渲染三個輸入框：`hatena_id`、`blog_id`、`api_key`，附帶指向 Hatena AtomPub 設定頁的說明連結。
- R2. 表單 POST 到 `/settings/save-channel-credential` 後，憑證以 `hatena-credentials.json`（0600）寫入 config dir，欄位留空則保留舊值（leave-as-is 語意）。
- R3. `config/tokens.py` 的 `_TOKEN_FILES` 包含 Hatena 條目，使 token rev drift-check 能追蹤此文件。
- R4. `save_hatena_token` 和 `_TOKEN_FIELDS_DISPATCH["hatena"]` 的欄位名清單與 `hatena_atompub.py` 的 `_load_credentials()` 期望的 key 完全對齊（`hatena_id`、`blog_id`、`api_key`）。
- R5. 設定頁顯示的憑證文件路徑提示為 `hatena-credentials.json`（非 `hatena-token.json`），與實際 credential basename 一致。

## Scope Boundaries

- 不改動 `cli/*.py`、`schema.py`、`publishing/adapters/__init__.py`（adapter 已 register）。
- 不實作 browser-login / OAuth 流程——Hatena 是 token_fields，不是 live_browser。
- 不改動 `_settings_cardless_channels.html`（路由已正確）。
- 不執行 dofollow canary 探測（屬 plan 008 範疇，維持 `dofollow="uncertain"`）。

## Context & Research

### Relevant Code and Patterns

- **template**: `webui_app/templates/_settings_binding_token_fields.html` — `_FIELD_DEFS` Jinja dict，參考 `"wordpresscom"` 條目格式（password/text/url type，`name`/`label`/`placeholder`/`help`）
- **credential dispatch**: `webui_app/services/credential_service.py:56` — `_TOKEN_FIELDS_DISPATCH` dict，格式 `"channel": (save_fn, "filename.json", ["field1", ...])`
- **token save**: `src/backlink_publisher/config/tokens.py` — `_save_token(data, path, basename)` pattern；`save_wordpresscom_token` / `save_hashnode_token` 可直接對照
- **_TOKEN_FILES**: `tokens.py:19` — drift-check 清單，每個 `save_*_token` 函數必須在此有對應條目
- **adapter 憑證格式**: `src/backlink_publisher/publishing/adapters/hatena_atompub.py` — `_CRED_FILENAME = "hatena-credentials.json"`，`_load_credentials()` 讀取 `hatena_id`、`blog_id`、`api_key`
- **測試模式**: `tests/test_config_tokens_notion_devto.py`（save/load round-trip + 0600 + env sandbox）；`tests/test_channel_bind_save.py`（POST route + CSRF + dispatch round-trip）

### Institutional Learnings

- **憑證文件名**：Hatena 的 credential basename 是 `hatena-credentials.json`，非 `hatena-token.json`，必須與 adapter 對齊（見 `hatena_atompub.py`）。
- **CSRF 測試**：用 `_seed_csrf(client)` + `_origin_headers()`，不要在 blueprint 再加第二層 CSRF（全局 guard 已覆蓋）。
- **leave-as-is 語意**：`save_token_fields()` 用 `{**existing, **new_fields}` field-merge；空欄位留舊值，與 `_load_credentials()` 完全兼容。
- **`_TOKEN_FILES` 必須同步**：每個新 `save_*_token` 都要加 `_TOKEN_FILES` 條目，否則 drift-check 無法追蹤。

## Key Technical Decisions

- **使用 `token_fields` 路徑**，不引入新路由：rationale — Hatena AtomPub 是靜態 API key，三個字段完全符合現有 token_fields 架構，不需要 browser-login。
- **憑證 basename 用 `hatena-credentials.json`**（非 `hatena-token.json`）：rationale — 必須與 `hatena_atompub.py`、`_manifests.py` 的 `_CRED_FILENAME` 保持一致，否則 adapter 讀不到憑證。
- **`api_key` 欄位型別用 `password`**：rationale — AtomPub API key 屬於高敏感憑證，遵循 `wordpresscom` token 欄位的處理方式。

## Open Questions

### Resolved During Planning

- Q: Hatena 是否需要 browser-login 流程？A: 否，`auth_type="token_fields"`，只需靜態填入三個字段。
- Q: 憑證 basename 用 `hatena-token.json` 還是 `hatena-credentials.json`？A: 用 `hatena-credentials.json`，與 adapter 對齊。

### Deferred to Implementation

- `load_hatena_token` 是否要同步新增：理論上目前只有 `save` 路徑需要，但 adapter 直接讀文件，不走 `load_*_token`。可在實作時確認是否需要。

## Implementation Units

```
Unit 1 ─── tokens.py
              save_hatena_token + _TOKEN_FILES
Unit 2 ─── credential_service.py
              _TOKEN_FIELDS_DISPATCH["hatena"]
              (depends on Unit 1)
Unit 3 ─── _settings_binding_token_fields.html
              _FIELD_DEFS["hatena"]
              (depends on Unit 2 for end-to-end flow)
```

---

- [x] **Unit 1: `save_hatena_token` + `_TOKEN_FILES` 條目**

**Goal:** 在 `config/tokens.py` 新增 `save_hatena_token` 函數及 `_TOKEN_FILES` 條目，使 drift-check 能追蹤 `hatena-credentials.json`。

**Requirements:** R3, R4

**Dependencies:** 無

**Files:**
- Modify: `src/backlink_publisher/config/tokens.py`
- Test: `tests/test_config_tokens_hatena.py`（新建，仿 `test_config_tokens_notion_devto.py`）

**Approach:**
- 在 `_TOKEN_FILES` 清單末尾加 `("hatena", "hatena-credentials.json")`
- 新增 `save_hatena_token(data, path=None)` 函數，呼叫 `_save_token(data, path, "hatena-credentials.json")`
- docstring 列出 expected keys：`hatena_id`、`blog_id`、`api_key`
- 函數放在其他 `save_*_token` 的字母序附近（或末尾），保持風格一致

**Patterns to follow:**
- `save_wordpresscom_token` / `save_hashnode_token` 的 docstring + `_save_token` 呼叫格式
- `test_config_tokens_notion_devto.py` 的 `config_dir` fixture + `stat.S_IMODE` 0600 驗證

**Test scenarios:**
- Happy path：`save_hatena_token({"hatena_id": "foo", "blog_id": "bar", "api_key": "baz"})` → `hatena-credentials.json` 存在，內容 JSON 完整包含三個字段
- Edge case：`api_key` 有特殊字符 → JSON round-trip 無損
- Error path：config dir 不可寫 → `OSError` 不被吞（不加 `except`）
- Integration：`_TOKEN_FILES` 清單包含 `("hatena", "hatena-credentials.json")` 條目（斷言列表成員）

**Verification:** `pytest tests/test_config_tokens_hatena.py` 全綠；`grep "_TOKEN_FILES" src/backlink_publisher/config/tokens.py` 顯示 hatena 條目。

---

- [x] **Unit 2: `_TOKEN_FIELDS_DISPATCH["hatena"]` 加入 credential_service**

**Goal:** 在 `credential_service.py` 的 `_TOKEN_FIELDS_DISPATCH` 中加入 `"hatena"` 條目，使 `save_token_fields("hatena", ...)` 能正確 dispatch 到 `save_hatena_token`。

**Requirements:** R2, R4

**Dependencies:** Unit 1（`save_hatena_token` 必須先存在以便 import）

**Files:**
- Modify: `webui_app/services/credential_service.py`
- Test: `tests/test_channel_bind_save.py`（在現有檔案中新增 Hatena 相關 test class）

**Approach:**
- 在 `_TOKEN_FIELDS_DISPATCH` import 區加 `save_hatena_token` from `backlink_publisher.config.tokens`
- 加入條目：`"hatena": (save_hatena_token, "hatena-credentials.json", ["hatena_id", "blog_id", "api_key"])`
- 確認 field list 順序與 template 字段定義（Unit 3）一致

**Patterns to follow:**
- `_TOKEN_FIELDS_DISPATCH["wordpresscom"]` 的 tuple 格式
- `test_channel_bind_save.py` 中的 `_post()` + `_seed_csrf()` + `_origin_headers()` fixture 組合

**Test scenarios:**
- Happy path：POST `{"channel": "hatena", "hatena_id": "myid", "blog_id": "myid.hatenablog.com", "api_key": "secret", "csrf_token": token}` with loopback Origin → 200，`hatena-credentials.json` 寫入正確
- Edge case：部分欄位留空（`blog_id` 空字串）→ leave-as-is，原有值不被覆蓋
- Error path：缺少 CSRF token → 403
- Error path：non-loopback Origin → 403
- Error path：`channel="hatena"` 但 `api_key` 完全不傳（和空字串不同，key 不存在）→ 現有 leave-as-is 邏輯能正確處理（不寫入 null）

**Verification:** `pytest tests/test_channel_bind_save.py -k hatena` 全綠；手動 POST 到 `/settings/save-channel-credential` 返回 200 並寫入文件。

---

- [x] **Unit 3: `_FIELD_DEFS["hatena"]` 加入 token_fields 綁定 template**

**Goal:** 在 `_settings_binding_token_fields.html` 的 `_FIELD_DEFS` Jinja dict 新增 Hatena 條目，渲染三個輸入框，附帶 AtomPub 設定頁說明連結。

**Requirements:** R1

**Dependencies:** Unit 2（dispatch 就緒後 end-to-end 才完整；template 本身可獨立渲染）

**Files:**
- Modify: `webui_app/templates/_settings_binding_token_fields.html`
- Test: `tests/test_channel_bind_save.py`（新增 template render test）

**Approach:**
- 在 `_FIELD_DEFS` dict 內加 `"hatena"` 條目，三個字段按順序：
  1. `hatena_id`（text）— Hatena 帳號 ID（登入用的 username）
  2. `blog_id`（text）— 博客 ID（通常是 `yourid.hatenablog.com`）
  3. `api_key`（password）— AtomPub API Key
- `help` 欄位加說明，指向 Hatena Blog 設定 → 詳細設定 → AtomPub，說明在哪裡取得 API Key
- 說明文字使用中文（與現有 wordpresscom/tumblr 條目風格一致）
- **修正 line 81 顯示 bug**：`{{ channel }}-token.json` hardcode 後綴，對 Hatena 會顯示 `hatena-token.json`（錯誤）。在 `_FIELD_DEFS` 條目中加入 `"credential_file"` key（或用 Jinja variable dict），讓顯示路徑使用正確的 `hatena-credentials.json`。最簡單方式：在同一個 `_FIELD_DEFS` block 之外加一個 `_CRED_FILENAMES` dict，template 渲染時查這個 dict；tumblr 也有同樣問題，可一併修正（但若 scope 過大可限縮只修 hatena）。
- 不修改 template 的其他邏輯（`_fields` fallback / form POST 結構不動）

**Patterns to follow:**
- `_FIELD_DEFS["wordpresscom"]` — password 欄位格式、help 文字風格
- `_FIELD_DEFS["tumblr"]` — 多欄位的 dict list 格式

**Test scenarios:**
- Happy path：以 `channel="hatena"` 渲染 template → 頁面包含 `name="hatena_id"` / `name="blog_id"` / `name="api_key"` 三個 input 元素
- Happy path：渲染結果不包含「字段配置尚未定义」警告字串
- Happy path：顯示的憑證路徑提示包含 `hatena-credentials.json`（不含 `hatena-token.json`）
- Happy path：`test_cardless_channel_inline_form_rendered` parametrize 列表加入 `("hatena", "token_fields")` — 確保與 `wordpresscom` 同等的渲染保護
- Edge case：`channel="unknown_channel"` → 仍渲染 fallback 警告框（現有行為不回歸）
- Integration：渲染後的 `<form>` action 指向 `/settings/save-channel-credential`，且 `data-channel="hatena"` 正確

**Verification:** `pytest tests/test_channel_bind_save.py -k "hatena and template"` 全綠；在本機 WebUI 設定頁展開 Hatena 手風琴 → 看到三個有 placeholder 的輸入框而非警告框。

## System-Wide Impact

- **Interaction graph:** `save_token_fields()` → `_TOKEN_FIELDS_DISPATCH` → `save_hatena_token()` → `_save_token()` → atomic write（已有 flock 保護）。不觸及 publish pipeline。
- **Error propagation:** token write 失敗會 raise `OSError`，由 `channel_bind_save.py` 路由層 catch 並回傳 500 JSON（現有行為，不新增處理）。
- **State lifecycle risks:** `hatena-credentials.json` 若已存在，field-merge 語意保留舊值——與 adapter 的 `json.loads()` 全讀語意兼容，無破壞。
- **Unchanged invariants:** `hatena_atompub.py` adapter 本身不改動；`register("hatena", ...)` 的 `dofollow="uncertain"` 不變；publish pipeline 行為不受影響。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `hatena-credentials.json` basename 與 adapter 不同步 | Unit 1+2 測試斷言讀回的文件名與 `hatena_atompub._CRED_FILENAME` 相同 |
| `_TOKEN_FILES` 漏加導致 drift-check 無法追蹤 | Unit 1 測試直接 assert `_TOKEN_FILES` 成員 |
| Template 渲染後 `api_key` 以明文顯示 | `type="password"` 已在 `_FIELD_DEFS` 條目中指定 |
| Template line 81 `{{ channel }}-token.json` 顯示錯誤文件名 | Unit 3 引入 `_CRED_FILENAMES` dict，以 `hatena-credentials.json` 覆蓋預設後綴（R5） |
| `test_credential_save_dispatch_drift.py` 斷言 dispatch key 必須有 registry auth_type | registry.py:247 已有 `"hatena": "token_fields"`，加入 dispatch 後此測試自動通過，無需額外改動 |
| SLOC/CC budget 超限 | 三個改動均是純加法（新函數 ≈5 SLOC，dispatch 條目 2 行，template dict 條目 ≈18 行），大幅低於各自文件的 ceiling |

## Sources & References

- Existing adapter: `src/backlink_publisher/publishing/adapters/hatena_atompub.py`
- Template to modify: `webui_app/templates/_settings_binding_token_fields.html`
- Dispatch map: `webui_app/services/credential_service.py:56`
- Token patterns: `src/backlink_publisher/config/tokens.py`
- Test patterns: `tests/test_config_tokens_notion_devto.py`, `tests/test_channel_bind_save.py`
