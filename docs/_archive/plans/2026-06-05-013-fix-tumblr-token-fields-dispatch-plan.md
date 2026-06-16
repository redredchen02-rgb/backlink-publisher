---
title: "fix: Complete Tumblr token-fields dispatch (save_tumblr_token + dispatch entry)"
type: fix
status: completed
date: 2026-06-05
origin: docs/plans/2026-06-05-012-feat-hatena-token-fields-binding-plan.md
---

# fix: Complete Tumblr token-fields dispatch

## Overview

Tumblr 的 `_FIELD_DEFS`（5 個欄位）、`_TOKEN_FILES` 條目、`_CRED_FILENAMES` 條目全部已存在，settings 頁會正確渲染表單——但 `save_tumblr_token` 函數不存在，`_TOKEN_FIELDS_DISPATCH["tumblr"]` 缺席，導致用戶填表後 POST 回傳「保存未實現」flash，靜默失敗。與 Hatena plan 012 對稱，需補齊同樣的兩個加法。

## Problem Frame

`credential_service.save_token_fields("tumblr", ...)` 呼叫 `_TOKEN_FIELDS_DISPATCH.get("tumblr")`，返回 `None`，觸發 `"channel 不在 token_fields 支援清單"` flash redirect。`test_cardless_channel_inline_form_rendered` parametrize 列表也沒有 `tumblr`，所以這個渲染→存儲的斷裂沒有 CI 保護。

## Requirements Trace

- R1. `save_tumblr_token(data, path=None)` 函數存在，寫入 `tumblr-credentials.json`（0600），欄位：`consumer_key`、`consumer_secret`、`oauth_token`、`oauth_token_secret`、`blog_identifier`。
- R2. `_TOKEN_FIELDS_DISPATCH["tumblr"]` 存在，dispatch 到 `save_tumblr_token`，field list 與 template `_FIELD_DEFS["tumblr"]` 對齊。
- R3. `("tumblr", "token_fields")` 加入 `test_cardless_channel_inline_form_rendered` parametrize，確保渲染有 CI 保護。

## Scope Boundaries

- 不改動 tumblr adapter（若存在）本身的發布邏輯。
- 不實作 tumblr OAuth 授權流程——只補存憑證的 token_fields 路徑。
- `_TOKEN_FILES` 已有 `("tumblr", "tumblr-credentials.json")`，不需要改動。

## Context & Research

### Relevant Code and Patterns

- **_TOKEN_FILES**: `tokens.py:28` — `("tumblr", "tumblr-credentials.json")` 已存在，save 函數補上後 drift-check 自動生效。
- **template 字段**: `_settings_binding_token_fields.html:36–70` — 5 個欄位（`consumer_key`、`consumer_secret`、`oauth_token`、`oauth_token_secret`、`blog_identifier`）；`_CRED_FILENAMES["tumblr"]` 也已存在（line 123）。
- **dispatch 格式**: `credential_service.py:56` — `"channel": (save_fn, "filename.json", ["field1", ...])` 三元組。
- **save 函數模式**: `save_hatena_token`（tokens.py:181）— 5 行模板，直接對照。
- **測試**: `test_channel_bind_save.py` — `_seed_csrf` + `_origin_headers` + `_post()` 組合；`test_config_tokens_hatena.py` — save/0600/round-trip 模板。

### Institutional Learnings

- `_TOKEN_FILES` 已有 tumblr 條目，新增 `save_tumblr_token` 後 drift-check 自動追蹤，無需再改。
- `test_cardless_channel_inline_form_rendered` parametrize 條目必須與 `_FIELD_DEFS` 加入同一 commit 原子落地——但 tumblr `_FIELD_DEFS` 已存在，所以 parametrize 可以直接加。

## Key Technical Decisions

- **直接仿照 `save_hatena_token` 加 `save_tumblr_token`**：rationale — 機制完全相同（`_save_token` + basename），無需引入新抽象。
- **field list 以 template `_FIELD_DEFS["tumblr"]` 為準**：5 個欄位，含 4 個 password 型 + 1 個 text 型 `blog_identifier`。

## Implementation Units

```
Unit 1 ─── tokens.py
              save_tumblr_token
Unit 2 ─── credential_service.py
              _TOKEN_FIELDS_DISPATCH["tumblr"]
              (depends on Unit 1)
Unit 3 ─── test_channel_bind_save.py
              parametrize + hatena-style test scenarios
              (depends on Unit 2)
```

---

- [ ] **Unit 1: `save_tumblr_token` 函數**

**Goal:** 在 `config/tokens.py` 新增 `save_tumblr_token` 函數。

**Requirements:** R1

**Dependencies:** 無

**Files:**
- Modify: `src/backlink_publisher/config/tokens.py`
- Test: `tests/test_config_tokens_hatena.py` 可作參照；新建 `tests/test_config_tokens_tumblr.py` 或加入現有 tokens 測試

**Approach:**
- `save_tumblr_token(data, path=None)` → `_save_token(data, path, "tumblr-credentials.json")`
- docstring 列出 expected keys：`consumer_key`、`consumer_secret`、`oauth_token`、`oauth_token_secret`、`blog_identifier`
- 放在其他 `save_*_token` 的字母序（t 系列）

**Patterns to follow:**
- `save_hatena_token`（tokens.py:181）的完整格式

**Test scenarios:**
- Happy path：`save_tumblr_token({...})` → `tumblr-credentials.json` 含 5 個欄位，0600 權限
- Edge case：4 個 password 欄位含特殊字符 → JSON round-trip 無損
- Integration：`_TOKEN_FILES` 清單已含 `("tumblr", "tumblr-credentials.json")` 條目（assert 驗證）

**Verification:** `pytest tests/test_config_tokens_tumblr.py` 全綠。

---

- [ ] **Unit 2: `_TOKEN_FIELDS_DISPATCH["tumblr"]`**

**Goal:** credential_service 加入 tumblr dispatch 條目，使 POST 路由能正確存儲憑證。

**Requirements:** R2

**Dependencies:** Unit 1（`save_tumblr_token` import）

**Files:**
- Modify: `webui_app/services/credential_service.py`
- Test: `tests/test_channel_bind_save.py`

**Approach:**
- import 區加 `save_tumblr_token` from `backlink_publisher.config.tokens`
- dispatch 條目：`"tumblr": (save_tumblr_token, "tumblr-credentials.json", ["consumer_key", "consumer_secret", "oauth_token", "oauth_token_secret", "blog_identifier"])`
- field list 順序與 `_FIELD_DEFS["tumblr"]` 一致

**Test scenarios:**
- Happy path：POST 5 個欄位 → 200，`tumblr-credentials.json` 寫入正確（0600）
- Edge case：`blog_identifier` 留空 → leave-as-is（路由層過濾空字串後 merge）
- Error path：缺 CSRF → 403；non-loopback Origin → 403

**Verification:** `pytest tests/test_channel_bind_save.py -k tumblr` 全綠。

---

- [ ] **Unit 3: parametrize + CI 渲染保護**

**Goal:** 在 `test_channel_bind_save.py` 的 `test_cardless_channel_inline_form_rendered` parametrize 加入 `("tumblr", "token_fields")`，確保 tumblr 渲染有 CI 防護。

**Requirements:** R3

**Dependencies:** Unit 2（dispatch 就緒後 end-to-end 才完整；但 parametrize 本身不依賴 dispatch，可提前加）

**Files:**
- Modify: `tests/test_channel_bind_save.py`

**Test scenarios:**
- Happy path：settings 頁渲染 tumblr 卡片 → 含 `name="consumer_key"` 等 5 個 input 元素
- Happy path：渲染不含「字段配置尚未定义」警告框

**Verification:** `pytest tests/test_channel_bind_save.py -k "tumblr and cardless"` 全綠；CI 通過。

## System-Wide Impact

- **Interaction graph:** `save_token_fields("tumblr", ...)` → `_TOKEN_FIELDS_DISPATCH` → `save_tumblr_token()` → `_save_token()` → `tumblr-credentials.json`。不觸及 publish pipeline。
- **Unchanged invariants:** `_TOKEN_FILES["tumblr"]` 已存在，drift-check 自動生效。template `_FIELD_DEFS["tumblr"]` 和 `_CRED_FILENAMES["tumblr"]` 不動。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `tumblr-credentials.json` 與 tumblr adapter 讀取格式不符 | 實作前 grep tumblr adapter 確認期望 key 名稱 |
| Unit 3 parametrize 在 Unit 2 就緒前跑 → 渲染測試仍會通過（無 dispatch 依賴），POST 測試才需要 Unit 2 | 分兩個 commit 可接受；CI 不會紅 |

## Sources & References

- Origin plan: `docs/plans/2026-06-05-012-feat-hatena-token-fields-binding-plan.md`
- Template fields: `webui_app/templates/_settings_binding_token_fields.html:36–70`
- Pattern to follow: `src/backlink_publisher/config/tokens.py` `save_hatena_token`
- Dispatch map: `webui_app/services/credential_service.py:56`
