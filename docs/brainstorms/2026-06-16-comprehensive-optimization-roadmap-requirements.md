---
date: 2026-06-16
topic: comprehensive-optimization-roadmap
---

# 全面優化迭代路線圖（2026 Q3）

## Problem Frame

backlink-publisher v0.4.0 已落地，功能完備、測試成熟（547 test files, 96% tier-marked）。
006（observe→enforce）和 007（signal freshness）的**代碼實作全部完成**（所有 Unit 均 `[x]`）。

真正的缺口不是「做什麼」，而是「啟動深度不夠」：
- **enforce 未啟用**：mastodon enforce 代碼建好（006 Unit 9），但 operator-gated，從未真正攔截過一次
- **排程缺口**：citation probe / weights optimize 有工具但沒有 launchd 排程
- **HTTP client 未統一**：27 個 src 檔案仍 `import requests` 直呼，SSL context 不一致
- **自動化閉環未完成**：plan-gap → plan-backlinks → weights 仍需人工觸發

這輪迭代核心主題：**從「建好但未動」到「排程化閉環」**。三個軸均衡推進：可靠性 / 產品價值 / 操作者體驗。

## User Flow（迭代後的目標狀態）

```
[Operator 設定目標 + seeds]
        ↓
plan-gap (週排程，自動偵測缺口)
        ↓
plan-backlinks → validate → publish  ← enforce gate 攔截劣質發布 ✓ (mastodon 已啟用)
        ↓
recheck (每日排程 ✓ 007 已建) → liveness alarm ✓ (007 已建)
        ↓
citation probe (每日排程 → Phase 1)  →  /health 面板 (→ Phase 1)
        ↓
weights optimize (週排程 → Phase 1)  →  下輪發布使用優化權重
        ↓
[Operator 只需看 dashboard 確認]
```

## Requirements

**Phase 1 — 激活 + 排程化（M1，4 週）**

從「代碼已建但未運行」到「每天/每週自動執行」。

- R1. 啟用 mastodon enforce（006 Unit 9 operator-gate 動作）：確認 accept 條件滿足後翻轉 enforce-allowlist，在 `/ce:health` 看到首次 `skipped_policy` 事件
- R2. 驗收 007 plists 已 committed 且安裝指引完整：daily recheck plist、selector-drift schedule plist 各有 install runbook
- R3. `probe-citations` 每日排程（launchd plist committed）：設定批量大小（**前置確認 Perplexity v1 API 日配額**），citation.observed 進 events.db
- R4. `weights optimize` 週排程（launchd plist committed），優化結果寫 events.db
- R5. `debt_registry.toml` 稽查：確認所有 `mitigated` 項是否可升為 `resolved`（現無 `open` 項，以 2026-06-15 audit 為基準逐條核實）

**Phase 2 — 信號延伸 + HTTP 統一（M2，4 週）**

讓工具產生的信號在 dashboard 可見，並收口底層一致性缺口。

- R6. `/ce:health` citation 面板：per-target 的 site_cited / article_cited / absent 分布 + 7d rolling 趨勢（純後端計算，靜態渲染）
- R7. HTTP client 統一：src 內 27 個 `import requests` 檔案收口為 `_util/http_client.py`，SSL context 統一。**前置門控**：先跑 `radon raw -s` 逐一確認 SLOC 預算；超限者同 PR 提 ceiling update + 80 char rationale
- R8. Decay alert：14d 內同目標掉 ≥2 條 dofollow 鏈時寫 events.db + `/ce:health` 告警 banner
- R9. `/ce:health` weights 快照：顯示最新 optimize 結果（時間戳 + top 3 channel 分數變化）

**Phase 3 — 自治閉環（M3，4 週）**

閉合 operator 仍需手動觸發的最後幾個循環。

- R10. plan-gap 週排程腳本：`equity-ledger | plan-gap --desired N | plan-backlinks` 組合，operator 確認後執行（**不自動 publish**）。腳本位置（`scripts/` vs CLI entrypoint）在 planning 階段確認 monolith budget 影響
- R11. autopilot 狀態頁擴展：顯示「上次 plan-gap 結果」—— 已補鏈數 / 仍缺鏈數 / 觸發時間
- R12. Citation share health gate：`probe-citations --fail-on-low-share` 接入 autopilot 通知，低 share 目標標記為 replanning 優先級（gated on R3 日配額確認；配額不足則降為 stretch goal）
- R13. Survival dashboard 趨勢折線圖（stretch goal）：per-target dofollow 30d 歷史折線。前端選型（SVG/Canvas/現有 Bootstrap）在 Phase 2 citation 面板完成後評估，確認不違反前端反退化規則再排期

## Success Criteria

- Phase 1 結束：events.db 有 mastodon `skipped_policy` 事件；citation probe 和 weights 均有排程且已執行一次
- Phase 2 結束：`/ce:health` 顯示 citation 分布；HTTP client 統一完成（src 無裸 `requests.` 直呼）；decay alert 可觸發
- Phase 3 結束：operator 每週只需確認 plan-gap 推薦，無需手動組裝 CLI 命令

## Scope Boundaries

- 不新增 publishing adapter（現有 37+ 已足夠）
- 不做 WebSocket/SSE 推播
- Phase 3 plan-gap 排程**不自動 publish**——補鏈執行仍需 operator 確認（失控風險 > 效率收益）
- `verify_health.py` 的 BaseSqliteStore 遷移（005 遺留項）列為後續 follow-up
- 趨勢折線圖（R13）為 stretch goal，前端選型未解前不強制排入 Phase 3

## Key Decisions

- **006/007 代碼完成，Phase 1 = 啟動+排程**：不需要重新實作，只需 operator activate + plist commit
- **mastodon enforce 在 Phase 1 啟用**：代碼已就緒（Unit 9），啟用成本低，應儘快取得首次真實攔截數據
- **自治閉環保留人工確認**：補鏈操作失控風險高，Phase 3 只做「推薦 + 確認」，不做「全自動 publish」

## Dependencies / Assumptions

- R3（citation probe 排程）前置：Perplexity v1 API 日配額確認，決定 `--max-batch` 大小
- R12（citation share gate）gated on R3 配額確認
- R10（plan-gap 排程）腳本位置在 planning 階段確認，避免 monolith_budget.toml 衝突
- launchd plist 安裝仍為 operator 手動動作（committed 但不自動 activate）

## Outstanding Questions

### Resolve Before Planning

（無阻塞規劃的問題）

### Deferred to Planning

- [Affects R3, R12][Needs research] Perplexity v1 API 日配額：在 Phase 1 kick-off 前確認，作為 plist `StartCalendarInterval` 和 `--max-batch` 的設定依據
- [Affects R7][Technical] HTTP client 統一：radon 掃描 27 個 src 檔案，列出超 ceiling 者；plan 階段確認工作量是否符合 Phase 2 4 週預算
- [Affects R10][Technical] plan-gap 排程腳本放 `scripts/`（shell wrapper）或新 CLI entrypoint？`scripts/` 較安全（不觸 monolith budget），但邏輯難測試

## Next Steps

→ `/ce:plan docs/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md` 開始 Phase 1 計畫
