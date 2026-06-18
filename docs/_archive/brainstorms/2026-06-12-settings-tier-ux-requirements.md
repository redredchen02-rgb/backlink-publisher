---
date: 2026-06-12
topic: settings-tier-ux
---

# Settings 頁面 Tier 分組 UX 全頁重構

## Problem Frame

設置頁有 20 個渠道，目前：左側導航按字母序混排；下方配置卡片按「硬編碼6個 + 字母序其餘」排列。4 個免綁定渠道（T1）混在中間，用戶需要滾動才能找到最容易上手的切入點，延誤了首次發布測試。

目標：讓用戶打開設置頁後 5 秒內就能點到一個「試發布」，同時讓有意願綁定帳號的用戶清楚知道每個 Tier 代表什麼門檻。

## 渠道 Tier 分類

| Tier | 特徵 | 渠道 |
|------|------|------|
| T1 免綁定 | `auth_type == 'anon'` | notesio, rentry, telegraph, txtfyi |
| T2 填憑證 | `auth_type in ('token', 'token_fields', 'paste_blob', 'userpass', 'oauth')`；`status.bound` 為 True/False 指示是否已完成綁定 | blogger, ghpages, devto, hackmd, livejournal, mataroa, notion, qiita, gitlabpages, hatena, tumblr, wordpresscom, zenn, substack |
| T3 瀏覽器 | `auth_type == 'live_browser'`；mastodon 標記為「即將支持」 | medium, velog, mastodon |

## Requirements

**左側導航 (Sidebar)**

- R1. 「发布渠道」sidebar group 拆分為 3 個帶標籤的 sub-group：
  - 「T1 · 免綁定」—— 列出 anon 渠道
  - 「T2 · 填憑證」—— 列出 token/oauth 渠道（已綁定的先，未綁定後）
  - 「T3 · 瀏覽器」—— 列出 live_browser 渠道
- R2. 每個 sub-group label 旁顯示渠道數量（例：`T1 · 免綁定 (4)`）
- R3. T1 渠道項目加綠色圓點或「就緒」視覺標記，讓用戶一眼識別無門檻渠道

**配置區渠道卡片排序 (settings.html + _settings_cardless_channels.html)**

- R4. pane-channels 配置區按 Tier 分組顯示，順序：T1 → T2 → T3
- R5. 每個 Tier 前加 section 小標題：標題文字 + 副說明 + 渠道數量
  - T1：「開箱即用」「無需任何帳號，點下方任一渠道即可試發布」
  - T2：「填入憑證即自動」「一次設置，後續全自動」
  - T3：「瀏覽器登入」「需完成一次手動登入，之後自動發布」
- R6. T2 內部再按綁定狀態排序：已綁定（已授權 / 已綁定）在前，未綁定在後

**T1 渠道卡片視覺優化**

- R7. T1 渠道卡片加左側綠色 accent border（視覺區分「就緒」狀態）
- R8. T1 卡片展開後，「試發布」按鈕提升為主要 CTA（`btn-primary` 樣式），「測試連通」降為次要
- R9. T1 卡片 header 徽章改為「⚡ 免綁定 · 就緒」綠色標籤，字號略大於現有 10px

**綁定總覽 panel（本次 MVP 範圍內）**

- R10. Cold start 狀態（無真實綁定）時，T1 渠道卡片在總覽中加「⚡ 立即試發布」行動標籤，直接觸發試發布 flow（此為 MVP 範圍，不延至 Phase 2）
- R11. 總覽 panel 的 Tier 分組子標題與配置區文案保持一致（同 R5）

## Success Criteria

- 打開頁面後，T1 免綁定渠道在左側導航和配置區都明顯在最上方
- 全新用戶（cold start）無需滾動即可找到至少一個「試發布」入口
- 左側導航可以通過 Tier 子標籤快速定位目標渠道類別

## Scope Boundaries

- 不改變綁定邏輯、後端 API、路由結構
- 不重構 `dashboard_channels` 後端數據結構（僅在模板層重新組織渲染）
- mastodon「即將支持」stub 歸入 T3 group，視覺上灰色半透明 + disabled 狀態，無法點擊「試發布」，卡片 header 顯示「即將支持」標籤
- 全局設置（關鍵詞 / AI 引擎）不在本次範圍內

## Key Decisions

- **按 Tier 分組而非按 dofollow/nofollow**：Tier 代表「用戶需要做什麼」，是最直接的操作門檻視圖；dofollow 在卡片徽章已顯示
- **T2 內部按綁定狀態排序**：已綁定的渠道是用戶「已投入的」，放前面減少滾動

## Dependencies / Assumptions

- `status.auth_type` 已存在於所有渠道的 status 對象（從 `dashboard_channels` 讀取）
- sidebar 的渠道數據沿用 `dashboard_channels` 變量，無需新的後端 endpoint
- Bootstrap collapse 組件保持不變，accordion 行為無需改動

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Technical] sidebar 目前用 `{% for name, status in dashboard_channels %}` 單次迭代，需要確認 Jinja2 groupby 或多次迭代是否有性能問題
- [Affects R4][Technical] `_settings_cardless_channels.html` 目前單次 for loop 渲染所有非 carded 渠道；重構為按 tier 分 3 段渲染，需要確認模板拆分方式（新 partial 或條件過濾同一個 loop）
- [Affects R6][Technical] T2 bound/unbound 排序需要在 Jinja2 層做，確認 `status.bound` 在所有 T2 渠道中都有效

## Next Steps

→ `/ce:plan` for structured implementation planning
