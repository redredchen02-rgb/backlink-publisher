---
title: "opt: 總體收斂優化計畫(解凍 fleet → 帳實一致 → 閘門與藍圖債務)"
type: optimization
status: completed
date: 2026-07-06
claims: {}
---

# opt: 總體收斂優化計畫(解凍 fleet → 帳實一致 → 閘門與藍圖債務)

## Overview

收斂傘計畫。以 2026-07-06 三路現況調查為基礎,做四件事:

1. **帳實一致**:已完成的計畫(reconcile 001、Phase 3、Phase 4)翻 `completed`;勾選框補記。
2. **解凍 fleet**:合併 `integration/fleet-preview-2026-07-06`(44 ahead/6 behind),解除 005 全部 16 單元與 v0.6.0 的凍結。
3. **分支與 worktree 全面處置**:14+ 條在途分支逐一決定合併/刪除/rebase;22 個 worktree 精簡。
4. **閘門與藍圖債務**:strict-markers 實效驗證、CC/SLOC 覆蓋完整性、`spec.py` ceiling 協調調升;兩份 blueprint 逐項對照現碼收尾。

本計畫不展開 v0.6.0、005、004 的功能單元,只負責解除所有前置閘門並排定接續順序。

## Implementation Units

- [x] **U1: 計畫文件帳實收斂(合併前段)** — 翻轉已完成計畫狀態、補記勾選框;裁決主檢出 127 行不明修改。不碰 fleet preview 已改動的文件。

- [x] **U2: fleet preview 刷新與合併** — 回合 main 最新 6 commits、全套閘門驗證後合併進 main。全局解凍,解除 005 P0 與 v0.6.0 驗證阻塞。

- [x] **U3: 在途分支與 worktree 全面處置** — 吸收 Phase 4 U3/U4 重定義。14+ 分支逐條結局(git cherry/range-diff 等價比對→刪除或摘取)。22 worktree 精簡。

- [x] **U4: 合併後單一權威測試量測** — 全套件 pytest 跑一次,按 Phase 3 D2 方法學分類殘餘失敗。v0.6.0 U1 結案裁決;取代 hidden-debt E1 工件。

- [x] **U5: 閘門實效審計 + spec.py ceiling 調升** — 吸收 hidden-debt B1/B2。逐項實測閘門生效性;`spec.py` ceiling 一次協調調升涵蓋 004/005/v0.6.0 全部已知需求。

- [x] **U6: 藍圖債務驗證掃描** — 吸收 hidden-debt D2/D3 具名 bug。兩份 blueprint 逐項 grep/讀碼三分類(已修/需修/入債);具名 bug test-first 修復。

- [x] **U7: 收斂收尾與接續裁決** — 產出收斂後 active 計畫組合(004/005/v0.6.0 + 002 若 un-park);裁決 hidden-debt 002 un-park 範圍。本計畫結案。

## 接續順序建議

收斂完成後 active 計畫執行順序:attention-dashboard 004 U1(無依賴)可先行 → 005 在 P0 成立後按 W 序 → v0.6.0 剩餘 U6-U9/U11/U13-U15 與 005 重疊單元協調排程。
