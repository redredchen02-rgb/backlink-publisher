---
date: 2026-06-05
topic: lite-release-readiness-triage
---

# LITE Release-Readiness Triage

## Problem Frame

操作者帶著五項「殘留風險」清單來收斂。稽核實際程式碼後發現:這五項處在**三個完全不同的成熟度**,不是五件等價待辦。把它們當「五件都要關掉」會浪費執行力,因為其中兩項在已 ship 的計畫文件裡是白紙黑字的「刻意延後」。

本文件的目的是 **backlog 收斂分類**:替每項定優先序、定義「過關標準」,並把無須動工的項目正式記成「已決策的延後」,讓它們離開焦慮清單。**不開硬性 go/no-go 發布閘。**

## Triage Overview

| 層級 | 項目 | 現況(已稽核) | 收斂動作 |
|------|------|------------|---------|
| **P1 動工** | #5 adapter 成功率量化 | health 只報混合 `{ok,fail}`,per-adapter 訊號丟失 | 真的寫 |
| **P2 待排** | #1 SQLite 壓測 · #3 LITE E2E 隔離 | 程式碼已 ship + 有單元測試,缺真實量/威脅模型驗證 | 補測試,排在 P1 後 |
| **P3 現狀接受** | #2 Keep-Alive G5b · #4 Pydantic 閉環 | 計畫文件中明列「刻意延後」 | 不動工,記成已決策延後 |

## Requirements

**P1 — Adapter 成功率可觀測性 (#5,動工)**
- R1. 在 health 儀表板 / 報告中,以 **per-adapter** 粒度輸出指標,取代目前的混合 `{ok,fail}`。
- R2. 每個 adapter 並列**兩欄**:**發布時成功率**(publish 動作回傳 ok)與 **live 存活率**(發布後連結仍活著且 dofollow 未被 strip)。
- R3. 沿用既有時間窗(w24h / w7d / w30d),per-adapter × 兩欄各自分窗。
- R4. 兩欄落差大(貼得上但留不住,如 telegraph strip 56–67%)時須一眼可見,不必手挖 events.db。

**P2 — 驗證缺口 (#1 / #3,待排)**
- R5. (#1) 對 6-store → `webui.db` 遷移補一個真實資料量 / 併發壓測(request 執行緒 + APScheduler worker 同時讀寫),證明遷移在生產規模下不壞。
- R6. (#3) 對 LITE 的 loopback-only 綁定 + DNS-rebinding 威脅模型補 E2E 驗證(目前只有單元測試,無端到端瀏覽器層驗證)。

**P3 — 已決策延後 (#2 / #4,現狀接受)**
- R7. (#2) 正式記錄:Keep-Alive **G5b(重啟存活 rehydrate)維持延後**。理由:recheck 冪等且廉價、scorecard 重啟會重繪、LITE 為單操作者在場模型。記下**重啟觸發條件**(見下)。
- R8. (#4) 正式記錄:Pydantic payload models **維持 opt-in 並行層,不接管真實路徑**。`test_payload_types_divergence.py` 作為防漂移柵欄已足夠。記下重啟觸發條件。

## Success Criteria

- **P1 (#5)**:打開 health/報告即可看到每個 adapter 的「發布成功率」與「live 存活率」兩欄分窗數字;一個表現差的 adapter 無須手動稽核 events.db 即浮現。有對應測試。
- **P2 (#5/#3 之 P2 項)**:壓測(R5)與 E2E(R6)各自有可重跑的測試,且在 CI 或可手動觸發的入口存在。
- **P3**:`docs/solutions/` 或計畫文件中存在一條明確「接受現狀 + 重啟觸發條件」紀錄;R7/R8 不再出現在任何 active backlog。

## Scope Boundaries

- **不開硬性發布閘**:本次是收斂分類,非 go/no-go gate。
- **#2 / #4 不寫任何程式碼**:收斂結果是文件決策,不是實作。
- **#5 不擴成完整 analytics**:只補 per-adapter 兩欄 + 既有時間窗,不引入新儀表板框架、不接 GA4(自有金錢站語料不足,見既有決策)。
- **P2 兩項不阻擋 P1**:壓測與 E2E 是補強,不是 #5 的前置。

## Key Decisions

- **三層分類,P1=#5 先動**:#5 是唯一淨能力缺口,且讓 #1/#3 的風險變可觀測,槓桿最高(操作者確認)。
- **#5「成功」= 兩個都要**:per-adapter 同時量發布成功率與 live 存活率(操作者確認),因為兩者數字差很大,只看其一會誤判 adapter 健康。
- **#2 / #4 接受現狀**:兩者皆為計畫文件中既有的刻意延後,收斂動作是「記成已決策」而非「執行」(操作者確認)。

## Dependencies / Assumptions

- 假設 events.db 已記錄足以區分「發布成功」與「live 存活」的事件(publish 結果 + recheck 結果)。**此假設需 planning 驗證**——若 live 存活率所需的 recheck 事件未按 adapter 歸因,R2 第二欄需要先補資料管線。
- per-adapter 名單由 `publishing.registry.registered_platforms()` 動態提供(adapter registry,post-R9)。

## Outstanding Questions

### Resolve Before Planning
- (無)

### Deferred to Planning
- [Affects R1][Technical] per-adapter 指標的輸出位置:health 路由(`webui_app/routes/health.py`)、CLI 報告(`_report_format.py`)、還是兩者都要?
- [Affects R2][Needs research] events.db 是否已能按 adapter 歸因 recheck 結果(live 存活率欄的資料來源)?若否,需先補歸因欄位 —— 這會決定 R2 第二欄是「小改」還是「需資料管線」。
- [Affects R7/R8][User decision] #2 / #4 的「重啟觸發條件」具體寫什麼(例:#2 「當出現非操作者在場的長跑 recheck 需求時」;#4 「當 dict validators 與 Pydantic models 第三次漂移時」)。可在 planning 或落紀錄時定。
- [Affects R5][Technical] SQLite 壓測的「真實資料量」基準:用幾筆 / 幾併發執行緒算過關?

## Next Steps

→ `/ce:plan`(以 P1 #5 為主軸切第一個可執行單元;P2/P3 在 plan 中分別列為後續單元與「決策紀錄」單元)
