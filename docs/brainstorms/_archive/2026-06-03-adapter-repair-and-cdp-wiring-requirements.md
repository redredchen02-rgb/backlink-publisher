---
date: 2026-06-03
topic: adapter-repair-and-cdp-wiring
---

# 發布管道修復：TelegraphCdp 接線 + 三個故障 Adapter 修復

## Problem Frame

目前 24 個平台已接線，但經 live probe（2026-06-03）確認有 2 個真實問題：

1. **TelegraphCdpAdapter** — 程式碼完整（`instant_web.py`），卻未接入 `register()`，PR #141 懸置未合入。
2. **livejournal** — `InternalError: 1 payload(s) failed verification`：文章成功發布，但事後鏈接屬性驗證（`attach_link_verification`）回傳失敗，發布被標記為 `published_unverified` 並推升至 CLI 層 InternalError。

**已確認非問題（live probe 通過）：**
- **rentry**：2026-05-29 的 ExternalServiceError 屬暫時性平台故障；今日 live probe 正常（CSRF 機制未改變，`/api/new` 回傳 200）。
- **txtfyi**：同期故障同樣暫時性；today probe 正常（`edit.php` form + `nonce`/`form_time` 欄位未變）。

用戶日常主要仰賴 telegraph（51 篇）和 blogger（21 篇），TelegraphCdpAdapter 的缺席讓 telegraph 在 API 失敗時無後備；livejournal 驗證誤報則讓該平台的發布被錯誤計為失敗。

---

## Requirements

**TelegraphCdpAdapter 接線（R1）**

- R1. 將 `TelegraphCdpAdapter`（`instant_web.py`）加入 `register("telegraph", ...)` 呼叫的後備鏈，位置在 `TelegraphAPIAdapter` 之後。
  - **主要跳過機制**：`TelegraphCdpAdapter.available()` 偵測 Chrome binary / CDP port，若不可用則回傳 False，dispatch chain 靜默略過，無需捕捉例外。
  - **次要後備路徑**：`TelegraphAPIAdapter` 拋出 `DependencyError` 時，dispatch 嘗試下一個 adapter；`ExternalServiceError` 仍往上傳（不 fall-through）。
  - 更新現有 `TelegraphCdpAdapter` import 行的 `# noqa: F401  kept for test import, not yet wired` 注釋。
  - 新增單元測試確認 `TelegraphCdpAdapter` 出現在 telegraph 的 adapter 鏈中（可參照 `test_r9_extension_readiness.py` 模式）。

**livejournal 驗證修復（R2）**

- R2. 釐清 `InternalError: failed verification` 的真實原因（發布本身已成功，問題在事後驗證步驟）：
  - 路徑 A：livejournal 頁面確實不含目標鏈接 → 平台在發布後剝除了外部鏈接；更新 `dofollow=False` rationale，並評估是否還有 referral_value 讓此平台繼續值得使用。
  - 路徑 B：`attach_link_verification` 對 livejournal 的 HTML 頁面結構解析出錯（例如鏈接在 JS 渲染區塊），屬誤報 → 加 per-platform 驗證豁免或修正解析。
  - 路徑 C：credentials（`redredchen02`）過期或帳號被 livejournal 封鎖 → 重新執行 `livejournal-login` 並重試。
  - 無論哪條路徑，修復後需確保 `status` 正確反映發布結果（false-negative 不可被計為 `failed`）。

---

## Success Criteria

1. `dispatch("telegraph", ...)` 在 `TelegraphAPIAdapter` 無 Chrome 依賴失敗時，自動 fall-through 到 `TelegraphCdpAdapter`；測試確認 `TelegraphCdpAdapter` 出現在 telegraph 鏈中。
2. livejournal：連續發布的 `status` 正確反映實際結果（不再出現誤報的 InternalError）；若路徑 A 確認鏈接被平台剝除，則更新 `dofollow` 宣告及 rationale。

---

## Scope Boundaries

- **不擴展新平台**：範圍限於修復/接線上述 4 個，不新增 Medium、Velog、Dev.to 等尚未使用的平台。
- **不改 `TelegraphAPIAdapter` 的 dofollow/dispatch_weight 設定**：Plan 005（已完成）已設 `dispatch_weight=0.6`，不在本次範圍。R1 只是在同一個 `register()` 呼叫中追加 `TelegraphCdpAdapter`，不調整現有欄位。
- **不重寫驗證框架**：livejournal 的修復是最小 patch，不翻新 `attach_link_verification`。

---

## Key Decisions

- **TelegraphCdpAdapter 接在 API 之後（非取代）**：CDP 依賴 Chrome binary，並非在所有環境都可用；API adapter 無此依賴，優先嘗試。
- **rentry/txtfyi 不需修復**：2026-06-03 live probe 確認兩者均正常（CSRF 機制、表單欄位無變化）；2026-05-29 的失敗屬暫時性平台故障，不追修。
- **livejournal 故障根因三條路徑並列**：planning 應先跑 live probe 再決定修復路徑，不應盲目改驗證邏輯。

---

## Dependencies / Assumptions

- Chrome binary 可從 `chrome.discover_chrome_binary()` 找到（若不可用，CDP adapter 的 `available()` 返回 False，fall-through 不會被呼叫到）。
- livejournal 帳號 `redredchen02` 的 hpassword 仍有效（若帳號已鎖定，修復路徑走 C）。
- rentry.co 和 txt.fyi 在執行 live probe 時網路可達。

---

## Outstanding Questions

### Resolve Before Planning

_（無 — 三條故障的診斷路徑已在 R2–R4 明確列出，planning 階段直接執行 live probe 決定路徑。）_

### Deferred to Planning

- [Affects R2][Needs research] livejournal 頁面（已發布的文章）對外部鏈接是否統一套用 `rel="nofollow"` 或直接剝除？需 live probe 最近一篇發布的 URL 確認（若 URL 已失效則走路徑 C）。

---

## Next Steps

→ `/ce:plan` 進行實作規劃（R1 TelegraphCdp 接線最簡單可先執行；R2 livejournal 需先跑 live probe 確認路徑再修）
