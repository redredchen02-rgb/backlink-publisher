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

### 2026-06-17 重審修正 — 「建好」≠「能工作」

原始前提假設「006/007 代碼完成 → 只需激活+排程，不需重新實作」。**這個前提已被證偽**：2026-06-17（PR #24）發現 `optimize-weights` —— 正是 R4 要週排程的子系統 —— 因 v2 schema 遷移未收尾而**靜默 no-op**（規則從不觸發，權重恆 1.0），而它的 integration 測試**一直是紅的（11 個失敗）卻被容忍**，掩蓋了這個生產 bug。

教訓：在排程激活任何「建好但未動」的子系統前，必須**端到端驗證它真的產出非空、非 no-op 的結果**，否則會排程一堆 no-op、並讓信任層 dashboard 顯示假數據（weights 快照恆 1.0、citation 面板恆空）。為此**新增 Phase 0「激活前驗證」門**（見下）作為 Phase 1 排程的前置。

> 同期完成：WebUI 控台改版（PR #20–#29）。Phase 2/3 的所有 `/ce:health`、autopilot、dashboard 面板需求（R6/R8/R9/R11/R13）現有控台主題 + monitor-hub 聚合器可直接掛載，樣式與聚合成本降低。

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

**Phase 0 — 激活前驗證門（M0，前置於 Phase 1）** *(2026-06-17 新增)*

在排程/激活任何「建好但未動」子系統前，先確認它真的工作。由 #24 的教訓驅動：「代碼完成 + Unit `[x]`」不等於「會產出真實結果」。

- R0.1. **激活前端到端驗證**：對 Phase 1 要排程/激活的每個子系統，跑一次真實（或代表性）端到端執行，斷言其產出**非空、非 no-op**，再排程：
  - `weights optimize`（R4 前置）：#24 已修；補一條 integration 迴歸測試斷言「v2 state 下規則確實觸發、權重被調整」，鎖死不再回退到 no-op
  - `probe-citations`（R3 前置）：對一個真實 target 跑一次，確認 `citation.observed` 列真的進 events.db（非空）
  - `mastodon enforce`（R1 前置）：對一個已知劣質 publish dry-run enforce gate，確認它**真的會 skip**（gate 邏輯實際觸發），再翻轉 allowlist
  - `recheck/liveness`（007）：確認鏈路真死時 recheck 真的寫出 alarm（非靜默 no-op）
- R0.2. **修「紅 integration 被容忍」的流程缺口**：#24 的根因是 11 個 integration 測試長期紅卻被忽略。確立規則——**任一子系統的 tier 測試為紅時，不得排程激活該子系統**；main 的 integration job 必須綠（本次已達成，需保持）。
- R0.3. **#24-class 系統性排查**：#24 是「half-migrated reader 消費未命名空間化的 v2 dict」。掃描 optimization/state 及相關子系統，找出其他同類「雙慣例 / 半遷移 reader」隱患（#24 一個 bug 牽出 5 處；確認是否還有未覆蓋的 v2 遷移點）。

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

- **Phase 0 結束**：每個待激活子系統都有一次端到端「真實產出」證據（weights 調整 / citation 列 / enforce skip / liveness alarm 各至少一筆非 no-op）；optimize 有迴歸測試鎖死；無「紅 integration 被忽略」的子系統進入排程
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

- **～~006/007 代碼完成，Phase 1 = 啟動+排程，不需重新實作~~（2026-06-17 修正）**：#24 證明「代碼完成」可能靜默壞掉。改為：**Phase 0 激活前驗證門先確認每個子系統真的產出結果，再進 Phase 1 排程**。激活不再假設「建好即能用」
- **新增 Phase 0「激活前驗證」門**：排程 no-op 子系統 + dashboard 顯示假數據的風險，遠高於 Phase 0 的一次性驗證成本（由 #24 實證）
- **紅 integration 不得激活**：子系統 tier 測試為紅時不排程激活；main integration 須保持綠
- **mastodon enforce 在 Phase 1 啟用**：代碼已就緒（Unit 9），啟用成本低，應儘快取得首次真實攔截數據（但須先過 R0.1 的 dry-run 驗證）
- **自治閉環保留人工確認**：補鏈操作失控風險高，Phase 3 只做「推薦 + 確認」，不做「全自動 publish」
- **Phase 0 優先，v0.5.0 主線延後決（2026-06-17）**：本路線圖與 `v050 plan` 已分叉（都 active、0 執行）。決議——先把 **Phase 0「激活前驗證」門當作 v0.5.0 第一個 milestone 獨立交付**（兩條線的共同前置），**throughput 主線（本路線圖的 enforce/citation/plan-gap vs v050 plan 的 GSC/catalog/console）延到 Phase 0 完成後再選**。理由：Phase 0 是無爭議的共同前置且直接接 #24；主線之爭在驗證完「哪些子系統真能用」後會更好判斷

## Dependencies / Assumptions

- R3（citation probe 排程）前置：Perplexity v1 API 日配額確認，決定 `--max-batch` 大小
- R12（citation share gate）gated on R3 配額確認
- R10（plan-gap 排程）腳本位置在 planning 階段確認，避免 monolith_budget.toml 衝突
- launchd plist 安裝仍為 operator 手動動作（committed 但不自動 activate）

## Outstanding Questions

### Resolve Before Planning

（已解決——見 Key Decisions「Phase 0 優先，主線延後決」）

### Deferred to Planning

- [Affects R0.3][Technical] #24-class 排查範圍：除 optimization rules/state，還有哪些子系統做過 schema 遷移、可能藏半遷移 reader？plan 階段 grep `version == 1`/`_upgrade_`/`.get(language` 等模式列清單

- [Affects R3, R12][Needs research] Perplexity v1 API 日配額：在 Phase 1 kick-off 前確認，作為 plist `StartCalendarInterval` 和 `--max-batch` 的設定依據
- [Affects R7][Technical] HTTP client 統一：radon 掃描 27 個 src 檔案，列出超 ceiling 者；plan 階段確認工作量是否符合 Phase 2 4 週預算
- [Affects R10][Technical] plan-gap 排程腳本放 `scripts/`（shell wrapper）或新 CLI entrypoint？`scripts/` 較安全（不觸 monolith budget），但邏輯難測試

## Next Steps

→ `/ce:plan docs/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md` —— **範圍鎖定 Phase 0「激活前驗證」門（R0.1–R0.3）作為 v0.5.0 第一個 milestone**。Phase 1+ 與 throughput 主線之爭待 Phase 0 完成後再規劃。
