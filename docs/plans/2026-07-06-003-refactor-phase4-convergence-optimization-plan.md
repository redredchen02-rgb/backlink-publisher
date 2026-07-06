---
title: "refactor: Phase 4 Convergence Optimization (Convergence → Hotspots)"
type: refactor
status: completed
date: 2026-07-06
claims: {}
---

# refactor: Phase 4 Convergence Optimization (Convergence → Hotspots)

## Overview

Phase 4 收斂優化——從 reconciliation 到熱點治理。涵蓋 8 個單元,其中 U3/U4/U5 由 006 Master Convergence Optimization Plan 吸收重定義。PRs #55、#56、#62、#63、#64 已全部落地。

## Implementation Units

- [x] **U1: reconcile GitHub/GitLab main 分歧** — 完成 `origin/main` 與 `gitlab/main` history 收斂。PR #55、#56 落地。

- [x] **U2: GitLab 退出 scope** — 確認 GitLab 無獨佔內容;operator 決策 GitLab 退出 scope。落地於 PR #55。

- [x] **U3: 在途分支處置(137 項髒樹→3 項)** — 大部分已在 fleet preview 中吸收;剩餘 3 項由 006 Unit 3 重定義後執行。

- [x] **U4: 分支/worktree 全面清理** — 合併後 main 上的分支與 worktree 處置;由 006 Unit 3 吸收重定義。

- [x] **U5: 計畫文件帳實收斂** — 計畫狀態與現實一致;由 006 Unit 1 吸收。

- [x] **U6: spray-core 模組拆分** — `spray_backlinks/` core 模組依功能拆分。PR #62 落地。

- [x] **U7: 文件漂移修正** — API retirement audit 文件與 AGENTS.md 同步。PR #63 落地。

- [x] **U8: API 稽核與 legacy endpoint 盤點** — 5 retire / 5 migrate / 8 keep 稽核清單產出。PR #64 落地。

## 備註

U3/U4/U5 的實際執行內容已在 `docs/plans/2026-07-06-006-opt-master-convergence-optimization-plan.md` 中重定義並收斂。本計畫作為 Phase 4 的結案節點。
