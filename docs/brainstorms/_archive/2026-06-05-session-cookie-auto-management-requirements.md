---
date: 2026-06-05
topic: session-cookie-auto-management
status: brainstorm
---

# Session Cookie 自動管理 — Requirements

## Summary

一個共用的 `SessionManager` 元件，為所有 publisher adapter 提供統一的 credential 生命週期管理。Adapter 透過 `get_session(channel)` 取得有效 `requests.Session`；SessionManager 負責載入 credential、lazily probe 有效性、過期時自動 refresh、refresh 失敗時拋 `AuthExpiredError` 並標記 channel expired。平台差異（credential 類型、probe endpoint、refresh 方式）透過 declarative metadata 描述，不須 per-platform strategy code。

---

## Problem Frame

目前三個主要 adapter（Velog、Medium、Blogger）各自處理 credential 生命週期，pattern 差異極大：

- **Velog**：從 Playwright storage-state.json 載入 cookies，自己寫了 `_load_cookies()` 和 `_probe_session_alive()`。refresh 依賴 `requests.Session` 自動 capture `Set-Cookie`，但沒有統一框架 — 每個新 cookie-based 平台都要重寫一套。
- **Medium**：OAuth token / Integration token 透過 config 層載入，adapter 在 publish 時才發現 401 後拋 `AuthExpiredError`，沒有 proactive probe。
- **Blogger**：走 `google-auth` 函式庫自帶 refresh，有自己的一套 token lock 機制防止 race。完全不與其他 adapter 共享 credential 基礎設施。

這種 ad-hoc 架構導致：

1. 新增 cookie-based 平台時必須從頭實作 credential 載入、probe、refresh、錯誤處理 — 重複勞動
2. `AuthExpiredError` 的拋出時機不一致（有的 publish 前發現，有的 publish 時才發現）
3. 沒有統一的 credential 儲存抽象，新平台得決定自己的 credential file 格式
4. 跨平台的生命週期行為（refresh 策略、重試、降級）無法一致配置

---

## Actors

- A1. **Adapter (Publisher)**：呼叫 `get_session(channel)` 獲取有效 HTTP session，不關心 credential 管理細節
- A2. **SessionManager**：管理 credential 生命週期的核心元件，負責 load → probe → refresh → 失效處理
- A3. **CredentialProvider**：從 storage 載入/儲存 credential 的介面，各平台可實作自己的 provider
- A4. **Operator**：當 `AuthExpiredError` 發生時，透過 WebUI 或 CLI 手動 re-bind channel

---

## Key Flows

- F1. **Session 獲取流程**
  - **Trigger:** Adapter 呼叫 `session_manager.get_session("velog")`
  - **Actors:** A1, A2, A3
  - **Steps:**
    1. SessionManager 透過 CredentialProvider 載入 channel 的原始 credential
    2. SessionManager 建立一個 `requests.Session` 並套用 credential（cookies 或 bearer token）
    3. SessionManager 發送輕量級 probe 請求驗證 session 有效
    4. Probe 成功 → 回傳 session
  - **Outcome:** Adapter 拿到一個已驗證有效的 `requests.Session`
  - **Covered by:** R1, R2, R3, R7, R12

- F2. **Credential Refresh 流程**
  - **Trigger:** Probe 失敗（session 已過期）
  - **Actors:** A2, A3, A4
  - **Steps:**
    1. SessionManager 檢測 probe 失敗
    2. SessionManager 檢查 platform metadata 中是否有 refresh 配置
    3. 有 refresh 配置 → 嘗試 refresh credential（如 refresh_token → new access_token）
    4. Refresh 成功 → 更新 session + 透過 CredentialProvider 持久化新 credential → 回傳 session
    5. Refresh 失敗（refresh_token 也過期）→ 拋 `AuthExpiredError` + 標記 channel expired
  - **Outcome:** Session 成功 refresh 或 channel 被標記 expired
  - **Covered by:** R4, R5, R19, R20

- F3. **到期後重綁定流程**
  - **Trigger:** Operator 看到 expired badge，手動 re-bind
  - **Actors:** A4, A3
  - **Steps:**
    1. Operator 透過 WebUI 或 CLI 跑 bind-channel
    2. Binding 完成 → 新的 credential file 寫入
    3. CredentialProvider 下次 load 時讀到新 credential
    4. SessionManager 下次 `get_session` 使用新 credential，probe 成功
  - **Outcome:** Channel 恢復正常
  - **Note:** 此流程使用現有 bind-channel 機制，SessionManager 不介入 binding

---

## Requirements

**SessionManager 核心介面**

- R1. SessionManager 提供 `get_session(channel: str) -> requests.Session` 介面
- R2. `get_session` 回傳的 session 已載入有效 credential（cookie 或 bearer token）
- R3. `get_session` 在回傳前 lazily probe session 有效性（一次輕量級 HTTP 請求）
- R4. Probe 失敗時，SessionManager 自動嘗試 credential refresh
- R5. Refresh 失敗時，SessionManager 拋出 `AuthExpiredError(channel=..., reason=...)` 並呼叫現有 `mark_expired()` 標記 channel expired
- R6. SessionManager 提供 `invalidate_session(channel: str)` 強制下次 `get_session` 重新載入 credential

**CredentialProvider 介面**

- R7. CredentialProvider 提供 `load(channel: str) -> Credential` 統一載入介面
- R8. CredentialProvider 提供 `save(channel: str, credential: Credential)` 統一儲存介面
- R9. `Credential` 是 typed dict，支援以下類型：
  - `cookie`：從 storage-state.json 或其他 cookie file 載入的 cookies
  - `bearer_token`：API token / OAuth access token
  - `oauth`：完整 OAuth credential（含 refresh_token / client_id / client_secret / token_uri）
- R10. Cookie 類型的 CredentialProvider 可直接讀取現有 bind-channel 產生的 storage-state.json 檔案
- R11. Token 類型的 CredentialProvider 讀取現有 OAuth token file / integration token file / TOML config

**Declarative Metadata 擴展**

- R12. 平台 credential 相關的 declarative metadata 融入現有 `register()` 系統，擴展現有 `_manifest_types.py` 模式
- R13. Metadata 包含：credential_type（cookie / bearer_token / oauth）、probe 相關配置（endpoint / method / expected status）、refresh 相關配置（endpoint / credential fields）、credential file 路徑模板
- R14. 新增 `session` 或 `credential` metadata kwarg 到 `register()`，與現有 `ui=` / `bind=` / `policy=` 等並列

**各平台行為**

- R15. Velog（cookie 型）：CredentialProvider 從 `velog-storage-state.json` 載入 cookies；SessionManager 設定 cookies 到 `requests.Session`；refresh 依賴 `Set-Cookie` 隱式 capture；probe 使用可配置的 probe endpoint
- R16. Medium（bearer_token 型）：CredentialProvider 依 `load_medium_token()` 優先級（OAuth → Integration Token → TOML）；bearer token 設為 `Authorization` header；integration token 不需 refresh（永不失效）；OAuth token 若有 refresh_token 則嘗試 refresh
- R17. Blogger（oauth 型，待設計確認）：CredentialProvider 從 blogger-token.json 載入完整 OAuth credential；SessionManager 通用 refresh 透過 `token_uri` + `refresh_token` + `client_id` / `client_secret` 發 POST；取代目前 `google-auth` 函式庫的直接呼叫

**錯誤處理**

- R18. 不支援 refresh 的平台（如 Medium integration token）在 probe 失敗時直接拋 `AuthExpiredError`，不做 refresh
- R19. `AuthExpiredError` 統一攜帶 `channel` 和 `reason` 欄位
- R20. Channel expired 標記透過現有 `webui_store.channel_status.mark_expired()` 機制，WebUI 自動顯示已過期 badge

---

## Acceptance Examples

- AE1. **Covers R1, R2, R3, R15.** Given Velog cookies 有效，when `get_session("velog")`，probe 成功（200 + expected body），回傳的 requests.Session 可以成功 publish
- AE2. **Covers R1, R3, R4, R15.** Given Velog access_token 已過期但 refresh_token 有效，when `get_session("velog")`，probe 失敗 → session 自動 refresh（capture Set-Cookie）→ 回傳有效 session
- AE3. **Covers R5, R19, R20.** Given Velog refresh_token 也過期，when `get_session("velog")`，refresh 失敗 → 拋 `AuthExpiredError(channel="velog", reason=...)` → channel 在 WebUI 顯示已過期 badge
- AE4. **Covers R1, R2, R16.** Given Medium integration token 有效，when `get_session("medium")`，回傳的 session 帶有正確的 `Authorization: Bearer <token>` header
- AE5. **Covers R5, R18.** Given Medium integration token 被撤銷，when `get_session("medium")`，probe 失敗 → 沒有 refresh 機制 → 直接拋 `AuthExpiredError`

---

## Success Criteria

- Operator 不需手動 re-bind 頻率降低：session 過期後若 refresh_token 有效，自動恢復；operator 只在 refresh_token 也過期時才需要介入
- Adapter 程式碼簡化：現有 adapter 中的 credential 載入 / probe / refresh 邏輯遷移到 SessionManager，adapter 只負責 `get_session()` → `session.post(platform_gql_endpoint)`
- 新增 cookie-based 平台時，不再需要重寫 credential 管理：只要在 metadata 中宣告 credential 類型、probe endpoint、refresh 配置

---

## Scope Boundaries

- **不包含背景週期性 probe** — 只做 publish 前 lazy probe
- **不包含 session pool / 多 session 切換** — 單一 channel 對應單一 session
- **不修改現有 bind-channel 流程** — SessionManager 只讀取 binding 產生的 credential，不介入綁定
- **不包含自動重試 refresh** — refresh 失敗一次就直接拋錯，不重試
- **不包含 credential rotation 或自動 re-binding** — refresh 失敗後 operator 必須手動處理
- **不統一現有 cookie / token file 格式** — CredentialProvider 可讀取既有格式，不強制遷移到統一格式
- **不包含 `_util/http_session.py` 的改造** — 那是給 content fetch / link check 用的通用 urllib pool，和 publish adapter 的 credential 管理無關

---

## Key Decisions

- **共用 SessionManager 元件**：而不是每個 adapter 各自實作 refresh 邏輯。所有 credential 管理集中在一個元件，降低重複。
- **Lazy probe**：publish 前才 probe session 有效性。比背景輪詢簡單，不需額外基礎設施，代價是每次 publish 多一次 HTTP call。
- **CredentialProvider 介面**：SessionManager 不直接讀取檔案，透過 CredentialProvider 抽象隔離儲存細節。binding 系統實作此介面。
- **Declarative metadata 描述差異**：平台間的 credential 行為差異透過 metadata（credential type / probe endpoint / refresh 配置）表達，不須 per-platform strategy class。沿用現有 `_manifest_types.py` 設計哲學。
- **Refresh 失敗不重試，直接拋錯**：最簡單的行為，避免 refresh race 或重複 refresh 導致 credential 狀態混亂。

---

## Dependencies / Assumptions

- 現有 bind-channel 產生的 storage-state.json（0600）可繼續作為 CredentialProvider 的 source of truth
- `requests.Session` 在 Velog 的隱式 refresh（capture Set-Cookie）行為持續有效
- Medium OAuth token 的 refresh 邏輯已在 config 層存在，SessionManager 的 CredentialProvider 可以接取

---

## Outstanding Questions

### Resolve Before Planning

- [Affects R17][User decision] **Blogger OAuth refresh 模型衝突**：目前 Blogger 使用 `google-auth` 函式庫的 `creds.refresh(Request())`，這是 google 自帶的 refresh 機制。SessionManager 的通用 refresh 模型（POST 到 token_uri 帶 refresh_token/client_id/client_secret）理論上能取代它。決定：
  - **方案 A**：SessionManager 通用 refresh 取代 google-auth — CredentialProvider 回傳完整 OAuth credential（含 token_uri/client_id/client_secret），SessionManager 發 POST refresh。完全統一。
  - **方案 B**：Blogger adapter 取回 session 後自行 wrap google-auth — `get_session()` 只處理 credential 載入和 probe，refresh 仍由 adapter 內部的 `_build_credentials()` 處理。犧牲一致性但風險低。

### Deferred to Planning

- [Affects R13][Technical] Probe endpoint 的 metadata 格式細節：對不同平台（GraphQL vs REST）的 probe URL 和 expected response 如何表達
- [Affects R9][Technical] Cookie credential 從 storage-state.json 提取的具體邏輯（現有 Velog 的 `_extract_tokens_from_origins()` 和 `_load_cookies()` 需要遷移到 CredentialProvider）
- [Affects R12][Needs research] 如何在現有 `_manifest_types.py` 中新增 `session` metadata 而不破壞現有 `register()` callers（所有現有 callers 傳 None，backward compatible）
- [Affects R10][Needs research] Storage-state.json 的 0600 權限檢查是否由 CredentialProvider 負責，或維持在 binding 層
