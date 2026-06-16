---
title: "fix: Validate blog_id domain format at bind time to prevent publish-time SSRF"
type: fix
status: completed
date: 2026-06-05
origin: docs/plans/2026-06-05-012-feat-hatena-token-fields-binding-plan.md
---

# fix: Validate blog_id domain format at bind time

## Overview

Hatena adapter 在 publish 時構建 `https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry`，`blog_id` 直接內插進 URL path。但 `_URL_FIELDS` SSRF gate 只覆蓋 `{site, site_url}`（完整 URL 驗證），不覆蓋 `blog_id`（domain fragment）。惡意路徑（如 `../../evil.example.com/x`）或 IP 地址可在 **publish 時** 將 HTTP POST 重定向到非 Hatena host。本計畫在 bind 時（credential 保存路由）加 `blog_id` 格式驗證閘，拒絕非 hostname 格式的值。

## Problem Frame

`channel_bind_save.py` 在 `_validate_url_field` 前先用 `_URL_FIELDS` frozenset 過濾——只有在 `_URL_FIELDS` 中的欄位才觸發驗證。`blog_id` 是 hostname fragment（如 `yourid.hatenablog.com`）而非完整 URL，現有的 `_validate_url_field` 不適用（它做 `urlparse` + `scheme` 檢查）。需要一個獨立的 `_validate_blog_id_field` 驗證器，並在路由層 per-channel 識別 `blog_id` 須走此路徑。

## Requirements Trace

- R1. `blog_id` 欄位在 credential save 時通過格式驗證：接受合法 hostname（字母/數字/連字符，至少含一個點），拒絕含 `/`、`..`、`@`、`://`、IP 地址格式的值。
- R2. 驗證錯誤以 flash redirect 回傳（與現有 `_URL_FIELDS` 驗證行為一致），HTTP 狀態碼 400（或 flash danger + redirect，依現有模式）。
- R3. 合法的 Hatena blog_id 格式（`yourid.hatenablog.com`、自定義域名）均可通過驗證。
- R4. 驗證邏輯可被其他使用 domain-fragment 欄位的 channel 複用（不硬寫成 hatena-only）。

## Scope Boundaries

- 不修改 `hatena_atompub.py` adapter 本身（publish 路徑不做 URL 驗證——publish 失敗會有 HTTP error，bind 時已攔截）。
- 不實作 DNS 解析驗證（只做格式驗證，不做連通性檢查）。
- 不修改 `_URL_FIELDS` 的 `_validate_url_field` 函數（用途不同）。

## Context & Research

### Relevant Code and Patterns

- **SSRF gate**: `webui_app/routes/channel_bind_save.py:49` — `_URL_FIELDS: frozenset[str] = frozenset({"site", "site_url"})`；驗證觸發 `channel_bind_save.py:212`
- **url validator**: `channel_bind_save.py:383` — `_validate_url_field(channel, field_name, val)` — 做 `urlparse` + scheme allowlist，不適用純 hostname
- **error flash**: `_safe_flash_redirect(...)` with `flash_type='danger'`（現有模式）
- **per-channel field dispatch**: 現有 `_URL_FIELDS` 是全 channel 共用，但 `blog_id` 驗證應 per-channel（只有 hatena 的 `blog_id` 需要此驗證）——最簡方式：`_BLOG_ID_FIELDS: dict[str, frozenset] = {"hatena": frozenset({"blog_id"})}`

### Institutional Learnings

- `_URL_FIELDS` 的設計是 field name → validator 的全 channel 映射（若多個 channel 同名欄位，共用驗證）。`blog_id` 只在 hatena 存在，per-channel dict 更安全。
- 錯誤回傳用 `_safe_flash_redirect` + flash danger（不暴露 `exc` 細節到 URL，見 plan 012 review S2）。

## Key Technical Decisions

- **per-channel `_BLOG_ID_FIELDS` dict**（非全局 frozenset）：rationale — `blog_id` 語義是 channel-specific（Hatena 的 blog_id 是 hostname，未來其他 channel 的 `blog_id` 含義可能不同），per-channel dict 避免跨 channel 污染。
- **hostname regex 格式驗證**（非 DNS 查詢）：rationale — bind 是本機操作，DNS 查詢帶網路依賴，違反 `real_ssrf_check` marker 隔離原則；格式驗證足以阻擋路徑遍歷。
- **validator 放在 `channel_bind_save.py`**（非 `credential_service.py`）：rationale — 驗證屬於 HTTP 入口層（輸入清洗），與業務層分離，與 `_validate_url_field` 位置一致。

## Open Questions

### Resolved During Planning

- Q: 用 `_URL_FIELDS` 全局 frozenset 還是 per-channel dict？A: per-channel `_BLOG_ID_FIELDS`，避免跨 channel 污染。
- Q: 合法的 hostname 格式為何？A: `^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(\.[A-Za-z]{2,})+$`，拒絕 `/`、`://`、`@`、純 IP 地址。

### Deferred to Implementation

- 自定義域名（如 `myblog.example.com`）的 Hatena 說明文件是否有額外格式限制：實作時若發現需調整 regex，在計畫注釋中記錄。

## Implementation Units

```
Unit 1 ─── channel_bind_save.py
              _BLOG_ID_FIELDS dict + _validate_blog_id_field()
Unit 2 ─── channel_bind_save.py
              在 token_fields save 路徑插入 blog_id 驗證
              (depends on Unit 1)
Unit 3 ─── tests/test_channel_bind_save.py
              blog_id 驗證測試
              (depends on Unit 2)
```

---

- [ ] **Unit 1: `_BLOG_ID_FIELDS` + `_validate_blog_id_field()`**

**Goal:** 在 `channel_bind_save.py` 新增 per-channel blog_id 欄位配置和驗證函數。

**Requirements:** R1, R4

**Dependencies:** 無

**Files:**
- Modify: `webui_app/routes/channel_bind_save.py`
- Test: `tests/test_channel_bind_save.py`

**Approach:**
- 在 `_URL_FIELDS` 附近定義：`_BLOG_ID_FIELDS: dict[str, frozenset[str]] = {"hatena": frozenset({"blog_id"})}`
- `_validate_blog_id_field(channel, field_name, val) -> str | None`：
  - 接受：符合 hostname regex 的值（至少一個點，無 `/`、`://`、`@`、`..`）
  - 拒絕：IP 地址（純數字 + 點）、含路徑字符的值、空字串（但空字串已在路由層過濾，視為 leave-as-is）
  - 返回 None 表示通過，返回 str 表示錯誤訊息

**Patterns to follow:**
- `_validate_url_field(channel, field_name, val)` 的函數簽名和返回約定
- 錯誤訊息風格與現有 `_URL_FIELDS` 驗證一致

**Test scenarios:**
- Happy path：`yourid.hatenablog.com` → None（通過）
- Happy path：`myblog.custom-domain.jp` → None（通過）
- Edge case：`yourid` （無點）→ 錯誤訊息（拒絕）
- Error path：`../../evil.example.com` → 拒絕
- Error path：`192.168.1.1` → 拒絕（IP 地址）
- Error path：`https://evil.example.com` → 拒絕（含 `://`）
- Error path：`hatena.ne.jp/attack` → 拒絕（含 `/`）

**Verification:** 函數單元測試全綠。

---

- [ ] **Unit 2: 在 token_fields save 路徑插入驗證**

**Goal:** 在 `channel_bind_save._save_token_fields()` 內，對 `_BLOG_ID_FIELDS` 中的欄位呼叫 `_validate_blog_id_field()`，驗證失敗則 flash redirect。

**Requirements:** R1, R2

**Dependencies:** Unit 1

**Files:**
- Modify: `webui_app/routes/channel_bind_save.py`
- Test: `tests/test_channel_bind_save.py`

**Approach:**
- 在現有 `_URL_FIELDS` 驗證段落後（或 merge 之前），加 blog_id 驗證：
  ```
  if field_name in _BLOG_ID_FIELDS.get(channel, frozenset()):
      err = _validate_blog_id_field(channel, field_name, val)
      if err: return _safe_flash_redirect(...)
  ```
- 驗證在路由層空字串過濾後、field-merge 前執行（與 `_URL_FIELDS` 驗證位置對齊）

**Test scenarios:**
- Integration：POST `{"channel": "hatena", "blog_id": "../../evil.com", ...}` → flash danger redirect，credential 文件未被寫入
- Integration：POST `{"channel": "hatena", "blog_id": "yourid.hatenablog.com", ...}` → 正常存儲
- Integration：POST `{"channel": "wordpresscom", "blog_id": "some-value", ...}` → blog_id 不在 `_BLOG_ID_FIELDS["wordpresscom"]` → 驗證不觸發（其他 channel 不受影響）
- Edge case：`blog_id` 留空（空字串）→ leave-as-is 路徑，不觸發 blog_id 驗證

**Verification:** `pytest tests/test_channel_bind_save.py -k "blog_id"` 全綠。

---

- [ ] **Unit 3: 完整測試覆蓋**

**Goal:** 確保所有 blog_id 驗證路徑有測試，包含繞過情境。

**Requirements:** R1, R3

**Dependencies:** Unit 2

**Files:**
- Modify: `tests/test_channel_bind_save.py`

**Test scenarios:**
- Happy path：合法 hostname 格式列表（`*.hatenablog.com`、`*.hatenadiary.jp`、自定義域名）均通過
- Error path：路徑遍歷（`../`、`./`）被拒絕，credential 文件不被寫入（斷言文件不存在）
- Error path：IP 地址 `192.168.1.1`、`127.0.0.1` 被拒絕
- Error path：帶 protocol 的值 `https://blog.example.com` 被拒絕
- Integration：`channel="tumblr"` 的 `blog_identifier` 欄位不觸發 blog_id 驗證（`_BLOG_ID_FIELDS` 只含 `"hatena"`）

**Verification:** `pytest tests/test_channel_bind_save.py -k "blog_id or hatena"` 全綠。

## System-Wide Impact

- **Interaction graph:** `POST /settings/save-channel-credential` → `_save_token_fields()` → blog_id 格式驗證閘（新） → `save_token_fields()` → credential 寫入。驗證失敗在閘前返回，不觸及 service 層。
- **Error propagation:** 驗證失敗 → `_safe_flash_redirect(flash_type='danger')`，不暴露內部路徑（遵循 S2 建議）。
- **Unchanged invariants:** `_URL_FIELDS` 驗證邏輯不動；其他 channel 的 `blog_id` 欄位（若有）不受影響（per-channel dict 隔離）。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Hostname regex 過嚴，拒絕合法自定義域名 | Unit 3 測試包含多種合法格式（`*.hatenablog.com`、`*.hatenadiary.jp`、普通 domain）；regex 以最小限制為原則（只拒絕明確惡意字符） |
| `_BLOG_ID_FIELDS` 插入位置影響空字串 leave-as-is 邏輯 | 驗證在路由層空字串過濾 **後** 執行，空字串已被過濾，不到達驗證器 |
| SLOC 增加觸發 monolith_budget | `channel_bind_save.py` 新增約 15–20 SLOC；視現有 ceiling 決定是否需要同 PR 更新 budget |

## Sources & References

- Origin plan: `docs/plans/2026-06-05-012-feat-hatena-token-fields-binding-plan.md` — S1 finding
- SSRF gate: `webui_app/routes/channel_bind_save.py:49` — `_URL_FIELDS`
- URL validator pattern: `channel_bind_save.py:383` — `_validate_url_field`
- Adapter endpoint: `src/backlink_publisher/publishing/adapters/hatena_atompub.py:208` — `f'https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry'`
