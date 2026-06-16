---
date: 2026-06-16
topic: gsc-indexation-ranking-loop
---

# GSC 雙面接入：Indexation 確認 + Ranking Feedback Loop

## Problem Frame

backlink-publisher Q3 路線圖（R1-R12）的驗收鏈是：

```
publish → URL alive → citation (Perplexity) → referral (GA4)
```

這條鏈有兩個盲點：
1. **Indexation Gap**：驗活了的頁面不代表 Google 已收錄。未被索引的頁面上的外鏈對排名零貢獻，但系統無法區分。
2. **Ranking Blind**：無法量化「建了這些鏈之後，目標關鍵字的排名移動了多少」——排名是否真的在動，現在完全不知道。

Google Search Console（GSC）API 可以同時解決這兩個問題，且你已有 GSC 認證設定（`gsc-activate` 技能）。

## Requirements

**Indexation 確認**
- R1. 新增 `probe-index` CLI：給定一組外鏈 URL（從 events.db 取已發布 & 未 confirmed-indexed 的），透過 GSC Search Analytics API（`page` 維度查詢，service account 支援）間接推斷索引狀態——出現在 Search Analytics 即視為已索引；結果回寫 events.db（`indexation.checked` event kind）。**不使用 URL Inspection API**（需 OAuth user token，與現有 service account 認證不相容）。
- R2. `events.db` 新增 `indexation.checked` event kind，欄位：`target_url`、`backlink_url`、`indexed`（bool）、`coverage_state`（GSC 原始狀態字串）、`checked_at`。
- R3. `/ce:health` 新增「索引狀態」分組：顯示已建鏈總數 / 已確認索引數 / 未索引數；未索引項可展開清單。
- R4. 未索引的外鏈頁面自動觸發 IndexNow ping（`indexnow.org` 標準 API，POST 給 Bing/Yandex，免費無配額）作為加速索引的旁路手段。

**Ranking Feedback Loop**
- R5. 新增 `probe-ranking` CLI：給定 target URL + 關鍵字清單，透過 GSC Search Analytics API 取最近 90d 的 `clicks / impressions / position`，存入 `events.db`（`ranking.snapshot` event kind）。
- R6. `ranking.snapshot` event 欄位：`target_url`、`keyword`、`avg_position`、`impressions`、`clicks`、`date_range_start`、`date_range_end`、`snapshot_at`。
- R7. plan-backlinks 建鏈前自動呼叫 `probe-ranking` 建立 baseline 快照（若 GSC 認證已設定）；建鏈後 30d 觸發 follow-up 快照。
- R8. `/ce:health` 新增「排名趨勢」面板：per-target 顯示 baseline vs. latest position，以 delta（↑↓）形式呈現；無資料時顯示「尚無排名快照」而非隱藏面板。

**排程整合**
- R9. `probe-index` 加入每日 launchd plist，在現有 probe-citations 排程之後執行（避免 GSC 配額競爭）。
- R10. `probe-ranking` 加入每週 launchd plist（每週快照頻率已夠，避免超出 GSC API 每日 50 req 限制）。

## Success Criteria

- 看到「哪些外鏈頁面尚未被 Google 收錄」的清單，並能一鍵觸發 IndexNow ping
- 看到「我在 [target] 建了鏈，目標關鍵字排名從第 N 位 → 第 M 位」的 before/after 比較
- 這兩個指標都出現在 `/ce:health` 面板，不需要開 GSC 後台

## Scope Boundaries

- 不做趨勢折線圖（R13 stretch goal，前端選型未解）
- DR 信號（競品 backlink gap）不在本輪範圍
- `probe-ranking` 的關鍵字清單由 operator 手動設定（seed URL 設定時填入），不自動發現
- IndexNow ping 只做「送出 ping」，不做「確認 ping 是否被接受」的回寫
- GSC URL Inspection API 每日 2,000 req 配額：probe-index 需分批執行（每批 ≤200 URL），不逾越

## Key Decisions

- **GSC 認證複用 + 不用 URL Inspection API**：service account 無法呼叫 URL Inspection API；改用 Search Analytics `page` 維度間接推斷索引狀態，service account 支援，認證流程不變
- **IndexNow 作為旁路而非替代**：不能保證 IndexNow 加速索引，但成本為零，值得加
- **events.db 而非獨立 DB**：ranking 和 indexation 事件和其他 reliability event 同構，用現有 `events/kinds.py` 擴充

## Dependencies / Assumptions

- GSC Search Console 已為目標站點設定（`gsc-activate` 已跑過），否則 R5-R8 降級為「顯示未認證提示」
- GSC URL Inspection API 需要 OAuth scope `webmasters.readonly`（需確認現有 service account 是否有此 scope）

## Outstanding Questions

### Resolve Before Planning
_（已全部解決）_

### Deferred to Planning
- [Affects R7][Technical] plan-backlinks 呼叫 probe-ranking baseline 的觸發點：pre-hook 還是 CLI 參數？需看 plan-backlinks/core.py 的 entrypoint 結構
- [Affects R9, R10][Technical] probe-index 與 probe-citations 的 GSC 配額是否共享 quota pool？需確認 Search Console API vs. Webmasters API 配額分區
- [Affects R4][Needs research] IndexNow 對已知平台（Mastodon / Blogger / WriteFreely 等）的索引加速效果是否有數據支持？

## Next Steps

→ `/ce:plan` 進行結構化實作規劃
