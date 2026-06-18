---
date: 2026-06-16
topic: autopilot-status-visibility
---

# Autopilot 狀態可視性

## Problem Frame

操作員設定 autopilot（toggle + 間隔）後進入「確認盲區」：
- 不知道排程有沒有真的被掛上（APScheduler job 是否存在）
- 不知道下次執行是什麼時候
- 上次執行結果（成功/失敗）只能翻 history 頁面查

後端資料都已存在：`schedule_store.autopilot_targets[url]` 有 `last_run`、`alert_pending`；
APScheduler `get_job()` 有 `next_run_time`。缺的只是**把這些資料呈現到 `sites.html` autopilot 列上**。

## Requirements

**每列 Autopilot 狀態顯示（sites.html autopilot-sites-tbody）**

- R1. 每個 site 列的「狀態」欄位依優先級顯示：
  - **未啟用**（`enabled=false` 且非剛關閉）：空白（`—`），不顯示任何狀態
  - **已停止**（toggle 剛關閉，含 `alert_pending=true` 的情況）：`已停止`（灰色）— toggle 狀態優先於失敗警示
  - **失敗**（`enabled=true` 且 `alert_pending: true`）：`⚠ 上次失敗`（紅色）
  - **正常排程中**（`enabled=true`，`next_run_time` 有值）：`⏭ 下次：{相對時間}` —— 例如「下次：明天 14:23」
- R2. 上述狀態從伺服器端在 `GET /sites` 模板渲染時注入（`next_run_time` 從 APScheduler
  job 讀取；`alert_pending` 從 schedule_store 讀取），不需要額外 AJAX 輪詢。
- R3. Toggle 開啟後的即時回饋（JS 層）從「✓ 已儲存」改為「✓ 已排程，下次：{時間}」，
  時間從 POST /sites/autopilot 的回應 JSON 新增 `next_run_time` 欄位取得。
  若 `next_run_time` 為 null（排程剛完成但 job 尚未反映），回饋 fallback 為「✓ 已排程」（不顯示時間）。
- R4. `/ce:health` 頁（health.html）若有任一 site 的 `alert_pending: true`，在現有
  `autopilot-alert-banner` 區塊上顯示紅色計數徽章（例：`⚠ 1 個失敗`），點擊直跳 /sites。
  （`/ce:dashboard` 已 302 redirect 至 `/ce:health`；`autopilot_alerts` 已傳入 health.html 模板。）

**POST /sites/autopilot 回應擴充**

- R5. POST /sites/autopilot 回應 JSON 新增 `next_run_time`（ISO 格式，可為 null）
  和 `last_run`（ISO 格式，可為 null），讓前端在 toggle 後即時更新顯示。

**Scope Boundaries**

- 🚫 不做即時 WebSocket/SSE 推播（unsolicited server-push）——靜態注入 + POST 回應 JSON 注入（toggle 時取得 `next_run_time`）已足夠
- 🚫 不改 history 頁面結構（已有 `source: autopilot` 篩選）
- 🚫 不改 APScheduler 的 job 執行邏輯
- 不新增獨立「autopilot 監控頁面」——sites 頁內聯即可

## Success Criteria

- 操作員開啟 autopilot toggle 後，同一列立即顯示「下次執行時間」，不需跳頁確認。
- 若上次 autopilot 執行失敗，進入 sites 頁面一眼可見警示，不需翻 history。
- 操作員無需巡視 /sites 頁面，即可從 /ce:health 一眼判斷是否有 autopilot 執行失敗，並直接點擊徽章跳轉至 /sites 確認細節。

## Key Decisions

- **靜態注入優先**：`next_run_time` 由後端在模板渲染時填入，降低前端複雜度。
  toggle 後的即時更新靠 POST 回應 JSON，不需輪詢端點。
- **alert_pending 已有**：`scheduler.py:324-325` 已在每次 autopilot cycle 結束後
  寫入 `last_run` + `alert_pending`，直接消費即可。
- **alert_pending 清除策略**：下次 autopilot cycle 執行成功時，scheduler 自動將
  `alert_pending` 設回 `false`（無需操作員手動 dismiss）。
- **狀態優先級**：toggle 關閉（`enabled=false`）優先於 `alert_pending`；已停止的 site
  即使有殘留的 `alert_pending=true` 也只顯示「已停止」。未啟用的 site（`enabled` 從未設定）
  狀態欄留空。

## Outstanding Questions

### Deferred to Planning

- [Affects R2, R3][Technical] `BackgroundScheduler` 未設定 `timezone=` 參數，`job.next_run_time`
  為 host 本地時區（非 UTC）。模板渲染與 POST 回應序列化時需確認轉換邏輯，兩者保持一致。
- [Affects R1, R2][Technical] 相對時間格式化責任歸屬：後端 Jinja filter 渲染絕對時間字串，
  還是後端注入 ISO 時間戳由前端 JS 即時轉換？前者靜態頁面停留後會過期，後者需前端 formatter。
- [Affects R2, R5][Technical] `get_job()` 回傳 `None` 的情境（job 不存在或 scheduler
  尚未啟動）：狀態欄應顯示什麼（隱藏？「排程讀取失敗」？）？
- [Affects R1][Technical] R1 狀態優先級：當 `alert_pending=true` 且 autopilot 同時被關閉
  時，顯示「⚠ 上次失敗」還是「已停止」？
- [Affects R2][Technical] GET /sites route 需擴充 `all_sites` 每項加入
  `alert_pending`、`next_run_time`——需確認 `_scheduler.get_job()` 跨模組引用方式
  （現有 POST handler 用 `_sched_mod._scheduler`）。

## Next Steps
→ `/ce:plan` for structured implementation planning
