---
title: "opt: WebUI 全面 UI/UX 優化(fleet 合併後新一輪)"
type: optimization
status: active
date: 2026-07-06
priority: high
claims: {}
---

# opt: WebUI 全面 UI/UX 優化(fleet 合併後新一輪)

## Overview

fleet preview 合併後的 WebUI 全面 UI/UX 優化。涵蓋 16 個 workstream:刷新行為地基、Settings 編輯保護、破壞性操作安全(ConfirmDialog + soft-delete + undo)、共享表單體系、視覺統一(自托管圖示 + SPA shell 升級)、導航與命令面板增量、a11y/響應式、錯誤誠實性收尾與首跑體驗、以及工程品質殘項。

**硬前置:** `integration/fleet-preview-2026-07-06` 必須先合入 main(P0),否則除 W3/W7 外所有 unit 凍結。

## Implementation Units

- [ ] **W1: 刷新行為顯式化** — QueryClient defaultOptions + 全站刷新來源盤點。
- [ ] **W2: Settings 編輯保護** — hydration 覆蓋修復 + per-card dirty + route-leave guard。
- [ ] **W3: ConfirmDialog 共享元件** — 取代三種 ad-hoc 確認;破壞性操作分級成文。
- [ ] **W4: soft-delete 資料層** — `deleted_at` + 讀路徑 filter + 延遲 purge。
- [ ] **W5: History/Drafts undo UX + per-row busy 互斥** — undo toast + 行內狀態 + busy 矩陣。
- [ ] **W6: 共享表單體系** — useChannelCard 擴充為全 Settings 統一慣例。
- [ ] **W7: 自托管圖示系統** — inline SVG 元件取代 CDN icon font + TopBar emoji。
- [ ] **W8: SPA shell 升級** — SideNav icon + anomaly badge + nav 分組對齊。
- [ ] **W9: 命令面板增量** — registry 擴充(頁內動作) + focus 歸還規格。
- [ ] **W10: 跨頁上下文 deep-link 系統化** — History 失敗行 ↔ error-report 彼此 deep-link。
- [ ] **W11: 表格 a11y** — caption/scope/select-all 三態/鍵盤導航,以 DataTable prop 交付。
- [ ] **W12: 分屏寬度可用性** — 700–960px 桌面分屏 Settings 與 Monitor 優先。
- [ ] **W13: mutation 錯誤上報覆蓋** — useMutation 遷移,修復發現 #4 root cause。
- [ ] **W14: 誠實性 blueprint 落地審計** — silent-exception + false-success 兩份 blueprint 逐項對帳。
- [ ] **W15: 首跑體驗** — never_run 引導式空狀態 + B2 修復。
- [ ] **W16: Prettier/stylelint lane** — 條件觸發(無 in-flight frontend 分支)。

## Dependencies

- **P0: fleet preview 合入 main** — `integration/fleet-preview-2026-07-06` 合併完成;在此之前 W3/W7 可預研,其餘 unit 不開工。
- v0.6.0 U5(DataTable)落地 → W11/W12 凍結解除。
- v0.6.0 U8(CDN 移除)落地 → W9 凍結解除;W7 與 U8 同捆或先行。
