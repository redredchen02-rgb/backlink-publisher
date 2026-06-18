---
date: 2026-06-11
topic: pipeline-orchestrator-closed-loop
---

# PipelineOrchestrator：全鏈路自動化閉環

## Summary

建一個中央 PipelineOrchestrator（event-driven state machine）來協調已存在的 CLI 元件——gap detection → plan → validate → publish → recheck → optimize——形成完整閉環。operator 不再需要手動啟動每個環節或處理散落在多個 cron 裡的半自動任務。

---

## Problem Frame

當前 backlink-publisher 的自動化處於**半連結狀態**：每個核心環節都已建好 CLI 工具，但它們之間沒有協調機制。

- `weights optimize` 每 6 小時跑 dry-run，但**從未實際寫入權重**，發布決策不受數據驅動
- `recheck-backlinks` 每週一觸發但仍在 `--probe` gate 後面，存活率數據要 operator 手動確認才進 production
- `run-full-pipeline.sh gap` 每天定時跑但結果不回饋到下一次決策
- 沒有任何 stage 有 circuit breaker——一個平台持續失敗不會觸發降權或隔離
- 失敗時 operator 只能從 logs 或非預期的空結果發現，而非主動通知

結果是 operator 的日常仍然是「每早檢查 → 手動跑缺失環節 → 判斷結果」，與 `plan-gap` 和 `weights` 等工具建好前的流程差異不大。**自動化的價值不在於每個元件都能獨立跑，而在於它們能在無人介入的情況下串成有意義的循環。**

---

## Actors

- A1. **Operator**：設定策略、監控儀表板、響應警報、必要時手動干預（pause/trigger/rollback）
- A2. **PipelineOrchestrator**：中央 state machine，負責偵測觸發條件、協調 stage 執行、管理重試與斷路
- A3. **CLI Components**：現有 CLI 入口（`plan-gap`、`plan-backlinks`、`validate-backlinks`、`publish-backlinks`、`recheck-backlinks`、`weights`）——以 subprocess 方式調用，**不做 rewrite**

---

## Key Flows

- F1. **完整閉環（Gap-Driven Pipeline）**
  - **Trigger：** `plan-gap` 輸出新 seed JSONL（即有 gap）
  - **Actors：** A2, A3
  - **Steps：** Orchestrator 收到 gap signal → `plan-backlinks`（生成文章）→ `validate-backlinks` → `publish-backlinks` → `recheck-backlinks` → `weights collect + optimize` → 權重寫入 → 更新存活儀表板
  - **Outcome：** gap 已被填補、存活率數據已更新、權重已反饋到下次發布
  - **Covered by：** R1, R2, R3, R5

- F2. **故障降級（Stage Failure + Circuit Breaker）**
  - **Trigger：** 任一 stage 回傳非零 exit code
  - **Actors：** A2, A1
  - **Steps：** Orchestrator 收到 failure → 判斷 failure type → 可重試？→ 重試（configurable attempts + backoff）→ 仍失敗？→ 觸發 circuit breaker（針對 platform/channel）→ 記錄 checkpoint → 通知 operator（WebUI banner + stderr）
  - **Outcome：** 單一 platform 的故障不會阻塞整個 pipeline；operator 被通知但不需立即介入
  - **Covered by：** R6, R7, R8

- F3. **Operator 干預（Manual Override）**
  - **Trigger：** Operator 在 WebUI 觸發 pause / trigger / rollback
  - **Actors：** A1, A2
  - **Steps：** Pause：Orchestrator 完成當前 stage 後停止排程；Trigger：手動啟動一次完整 pipeline 或指定 stage；Rollback：還原最近一次權重寫入
  - **Outcome：** Operator 保有完全控制權，Orchestrator 不取代 human-in-the-loop
  - **Covered by：** R9

---

## Requirements

**Orchestrator Core**
- R1. Orchestrator 作為 persistent process（或 launchd service）運行，監聽 gap trigger 信號。啟動時從 events.db 恢復上次 state。
- R2. 每個 stage 是可獨立 enable/disable 的 step。Stage 之間用 exit code + stdout JSONL 傳遞結果（現有 CLI 契約不變）。
- R3. Gap trigger 有二種來源：(a) `plan-gap` 定期執行後輸出非空 JSONL；(b) keep-alive recovery loop 產生的 republish 需求。Orchestrator 對二者使用相同的 pipeline 執行路徑。
- R4. Pipeline 執行結果寫入 events.db（`pipeline.started`、`pipeline.stage_completed`、`pipeline.completed`、`pipeline.failed`），每個事件攜帶 stage name、duration、exit code、checkpoint ref。
- R5. Orchestrator 週期性（預設每 24h）觸發一次 `plan-gap` 作為 gap detection pulse——無 gap 時 pipeline 不執行（zero-work skip）。

**Optimization 閉合**
- R6. `weights optimize` 的 write mode 從 dry-run-only 改為 configurable：operator 可設定 `weights.write_mode = "always" | "preview" | "threshold"`。Threshold mode：只在存活率變化超過 N% 時才寫入（防止噪聲觸發頻繁調整）。
- R7. 權重寫入後，Orchestrator 記錄 snapshot 到 events.db（`weights.snapshot`），包含調整前/後的權重表 + trigger 原因。支援 rollback 到任一 snapshot。

**Circuit Breaker + 故障處理**
- R8. Per-platform circuit breaker：連續 failures ≥ N（configurable，預設 5）時自動暫停該 platform 的發布，記錄 checkpoint event。定期（configurable，預設 24h）嘗試恢復（half-open）。
- R9. 非致命 failure（單一 platform 失敗）不阻塞其他 platform 的發布。Orchestrator 繼續剩餘 stage，僅標記失敗 platform 為 degraded。

**Notification**
- R10. Pipeline 完成時輸出摘要 JSONL（包含：gap 量、發布數、成功/失敗數、存活率 delta、權重變動）。此摘要可被外部消費（launchd alert、webhook、日報）。
- R11. 關鍵事件（circuit breaker trip、平台存活率顯著下降、pipeline 完全失敗）在 WebUI 以 banner 顯示。

**WebUI 儀表板**
- R12. `/ce:pipeline` 頁面顯示：目前 pipeline state（idle / running / paused / degraded）、各 stage 最後執行時間與狀態、最近 N 次 pipeline 摘要。資料源為 events.db pipeline events。
- R13. WEBUI 提供 pause/resume/trigger 按鈕，對應 F3 干預流程。

---

## Acceptance Examples

- AE1. **Covers R1, R2, R3, R5.** 設定 launchd 每 6h 觸發 Orchestrator gap pulse。當 `plan-gap` 輸出非空 JSONL 時，Orchestrator 依序執行 plan → validate → publish → recheck → optimize。各 stage 的 stdout/stderr 被正確 routing。
- AE2. **Covers R6, R7.** 設定 `weights.write_mode = "always"`。一次完整 pipeline 完成後，確認 `weights show` 反映新的權重值，且 events.db 包含對應的 `weights.snapshot` 事件。
- AE3. **Covers R8, R9.** 模擬一個 platform 連續 5 次 publish 失敗。確認 circuit breaker 在第五次失敗後 trip，該 platform 被標記 degraded，其餘 platform 不受影響。24h 後 half-open 自動重試一次。
- AE4. **Covers R10, R11.** Pipeline 完成後，WebUI banner 顯示摘要。若 circuit breaker trip，banner 包含 degraded platform 列表。
- AE5. **Covers R12, R13.** 在 WebUI 進入 `/ce:pipeline`，確認顯示 idle state。點擊 trigger，確認 pipeline 啟動。點擊 pause，確認完成當前 stage 後停止。

---

## Success Criteria

- Operator 可以設定一次後，系統連續一週無人介入仍正常運轉：每 6–24h gap detection → 有 gap 就自動跑 pipeline → 權重自動調整 → 存活率自動更新。
- 任何異常（單一 platform 連續失敗、存活率顯著下降）在一小時內透過 WebUI banner 可視。
- weights optimize 從 dry-run 改為 actual-write 後，operator 可以透過 snapshot rollback 回退任何變動。
- `/ce:pipeline` 儀表板讓 operator 一眼知道「現在系統在做什麼」和「上次做得怎樣」。

---

## Scope Boundaries

- **不重寫現有 CLI 元件**：Orchestrator 透過 subprocess + stdout JSONL 調用，不做 SDK refactor。
- **不新增 platform adapter**：已有 20 註冊平台，本次不擴充。
- **不新增數據儲存**：使用 events.db + 現有 stores（webui.db、channel-status.json）。
- **不取代現有 launchd plist**：Orchestrator 與 launchd 共存——launchd 負責定時觸發 Orchestrator，Orchestrator 負責編排內部 stage。
- **不 redesign WebUI**：僅新增 `/ce:pipeline` 頁面和 banner 機制，不改動現有 UI 結構。
- **不做 RAG/LLM 整合**：copilot Q&A 已有，本次不擴充。
- **不做跨機器分散式調度**：Orchestrator 是單機 process，同當前架構。

---

## Key Decisions

- **Orchestrator 作為 process 而非 library**：與 CLI 元件透過 subprocess 通訊，而非 Python import。這保持各元件的獨立性、測試隔離，且與現有 launchd 排程相容。
- **State 存在 events.db 而非新資料庫**：events.db 已有 checkpoint 機制，pipeline events 是自然擴充——無需 migration。
- **Trigger 模式是 periodic pulse + event-driven，而非 daemon 常駐輪詢**：launchd 每 N 小時喚醒 Orchestrator → 它檢查 gap → 決定是否跑 pipeline。這比常駐 process 更簡單、更 macOS-native、且 crash 後自動恢復。
- **Circuit breaker 是 per-platform 而非 global**：一個平台出問題不影響其他管道。threshold 可獨立配置。
- **權重 write mode 預設為 "preview"**：首次安裝後 operator 可以看 diff 但不自動寫入。明確 opt-in 才啟用自動寫入，降低初始風險。

---

## Dependencies / Assumptions

- `events.db` 已有 events 寫入機制——R4 pipeline events 可以複用相同模式（verified via `tests/test_events_store.py` 和 `events/_project_reducers.py`）。
- `plan-gap` CLI 已產出 seed JSONL 格式——R3 gap trigger 可直接消費其 stdout。
- `weights optimize` 已有 collect 和計算邏輯——R6 是新增 write mode config 而非重寫優化器（verified: `cli/weights.py` 有 `--dry-run` flag）。
- v0.4.0 Operator Autonomy 的 keep-alive 循環已就緒——R3b republish trigger 可以 hook into 現有 `/ce:keep-alive` 的 recheck → gap → republish 循環。
- `recheck-backlinks` 每個 platform 的 `post-publish-delay` 環境變數已定義——R8 circuit breaker 的 per-platform threshold 可以與此並行配置。

---

## Outstanding Questions

### Resolved

- ~~[Affects R1][Decision] Orchestrator 的實作語言~~ **RESOLVED 2026-06-11**: Python。直接讀 events.db、複用 error types、最低引入成本。
- ~~[Affects R6][Decision] `weights.write_mode` 的預設值~~ **RESOLVED 2026-06-11**: `"preview"`。首次只輸出 diff，operator 看過後手動確認才啟用寫入。

### Deferred to Planning

- [Affects R4][Technical] Pipeline events 在 events.db 的 schema shape——需要與現有 `checkpoint.*` events 相容。
- [Affects R6][Technical] `threshold` mode 的具體觸發條件——存活率變化百分比、絕對值、還是 min sample size gate？需要看 `weights optimize` 的輸出格式決定。
- [Affects R8][Technical] 現有 recheck/adapter 是否有可複用的 failure classifier？還是需要新加 circuit breaker state store？
