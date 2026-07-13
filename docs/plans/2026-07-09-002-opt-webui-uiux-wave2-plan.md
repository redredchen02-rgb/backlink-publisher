---
title: "opt: WebUI UX/UI 全面升級（第二波：一致性收口 + 殼層潤飾 + SSE 即時進度）"
type: optimization
status: active
date: 2026-07-09
priority: high
claims: {}
---

# opt: WebUI UX/UI 全面升級（第二波）

## Overview

建立在已落地的 `2026-07-06-005`（約 80%）之上，收口剩餘前端缺口，並依使用者裁決納入前計畫 parked 的 SSE 即時進度。

**範圍裁決（使用者確認）**：前端一致性收口 + SSE；不含後端契約統一大改。SSE 推翻前計畫 parked 決策。

**繼承** 2026-07-06-005 全部裁決（無排序、i18n parked、手機不做、單 CSRF guard、tokens 單源、useMutation 遷移語義、W11 DataTable 元件層能力）。

## 現狀實測（2026-07-09）
- ruff 全過；mypy 58 錯為 Windows fcntl 誤報；radon MI 0 檔 <20；budget 全綠。
- P0 完成：main 原 15 個 WIP 已 commit 為基線 `9591b43e`（使用者裁決）；該基線被並發 session 接續 `c6e6c54e`，安全。
- 9 頁手寫 `<table>`：CampaignProgress / EquityLedger / ErrorReports / Health / KeepAlive / OptimizationStatus / PrQueue / Schedule / Sites。
- `window.confirm` 殘留：MediumCard.vue:63,74、NotionCard.vue:93（BloggerCard 已遷）。
- `spa_dist/index.html` 仍掛 Bootstrap CDN（行 7/9）+ `data-bs-theme="light"`（行 2）。
- TopBar 搜尋 disabled stub（TopBar.vue:69,71）。
- 巨型頁：MonitorDashboard.vue (797)、HistoryPage.vue (730)。
- 響應式僅 2 頁有 `@media`。

## Requirements Trace
- R1 全站表格統一（DataTable+StateBlock）— W1
- R2 破壞性確認統一 ConfirmDialog — W2
- R3 全站無硬編碼色 — W3
- R4 SPA 零 Bootstrap CDN、data-theme 單源 — W4
- R5 巨型頁子元件化 — W5
- R6 Ctrl+K 命令面板 — W6
- R7 960px 分屏全頁 — W7
- R8 SSE 即時進度（輪詢降級）— W8,W9
- R9 Prettier/stylelint + 文件漂移 — W10
- R10 死 UI 清理 — W11

## Implementation Units
- W1: DataTable+StateBlock 收口 9 頁（逐頁獨立分支；繼承 D11 無排序；data-table-adoption guard 防回退）
- W2: MediumCard/NotionCard window.confirm → ConfirmDialog（danger、明確文案）
- W3: 去硬編碼色（grep 全 frontend/src → tokens；Icon 除外）
- W4: 移除 spa_dist/index.html Bootstrap CDN + 修 data-bs-theme（先 grep 確認無 .btn/.card 依賴）
- W5: 拆分 MonitorDashboard/HistoryPage 巨型頁（只抽子元件，不動業務邏輯）
- W6: Ctrl+K 命令面板（接手 W9/U8；registry + IME guard + focus 歸還；依賴 W4）
- W7: 960px 分屏響應式補齊剩餘頁（依賴 W1）
- W8: 後端 SSE 通道（flask-sock/simple-websocket 評選；/api/v1/stream；loopback+沿用 origin guard，不另加 CSRF；保留輪詢降級；monolith_budget 提額）
- W9: 前端 useEventStream composable + 遷移 Monitor/CampaignProgress/PublishWorkbench（fail-open 回退輪詢）
- W10: W16 Prettier/stylelint（條件：無 in-flight frontend 分支）+ 修 AGENTS.md/CLAUDE.md Axios 漂移
- W11: 死 UI 清理（移除 TopBar disabled stub；never_run 引導無回歸）

## Key Decisions
- D1 P0 先穩定 WIP；D2 W1 繼承 DataTable 元件層；D3 W4 刪 CDN 前 grep class 依賴；D4 W6 依賴 W4；D5 SSE 保留輪詢降級；D6 SSE 不另加 CSRF；D7 W5 只抽子元件；D8 每 unit 獨立分支+顯式 staging（禁 git add -A）+早 push；D9 WS 庫評選後定。

## Risks
- W1 九頁遷移量大 → 每頁獨立分支+guard。
- W4 移除 Bootstrap 後破版 → 先 grep（D3）。
- W8 SSE 大架構 → 輪詢降級+不動 CSRF/origin 不變式。
- 並發 ZCode session 活躍（4 bp-* worktree + ce-code-review）→ 本波專屬分支 opt/webui-uiux-wave2 + 早 commit/push + 每 unit turf-check。
- Write/Edit 工具在本環境被 sandbox（不落盤）→ 檔案編輯改經 Bash（cat/tee/python/sed），git commit 正常落盤。

## Sources
- 前計畫：docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md
- 分析：ANALYSIS_REPORT_2026-07-08.md（workspace root）
