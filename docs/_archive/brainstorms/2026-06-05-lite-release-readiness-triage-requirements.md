---
date: 2026-06-05
topic: lite-release-readiness-triage
---

# LITE Release-Readiness Triage

## Problem Frame

操作者帶著五項「殘留風險」清單來收斂。稽核實際程式碼後發現:這五項處在**三個完全不同的成熟度**,不是五件等價待辦。把它們當「五件都要關掉」會浪費執行力,因為其中兩項在已 ship 的計畫文件裡是白紙黑字的「刻意延後」。

本文件的目的是 **backlog 收斂分類**:替每項定優先序、定義「過關標準」,並把無須動工的項目正式記成「已決策的延後」,讓它們離開焦慮清單。**不開硬性 go/no-go 發布閘。**

## Triage Overview

> 經 review 後重新分層(原始 P1/P2/P3 在 Key Decisions 留有變更紀錄)。

| 層級 | 項目 | 現況(已稽核) | 收斂動作 |
|------|------|------------|---------|
| **P1 動工** | #5 publish 成功率欄(R2a)· #1 SQLite 壓測(R5) | #5:per-adapter publish 已 ship,缺 live 欄+分窗;#1:已上線但**從未量化併發資料風險** | #5 擴充既有查詢 + #1 跑壓測量化風險 |
| **Release-gate(出貨前必綠,不阻 P1 開工)** | #3 LITE DNS-rebinding/loopback E2E(R6) | 唯一網路信任邊界;單元測試**證明不了逐路由都掛 guard** | 逐路由斷言 guard + 偽造 Host/Origin E2E |
| **P1 動工(產品決策已定)** | #5 live 存活欄(R2b)· per-platform strip 診斷(R2c) | 兩者驅動不同決定:R2b → 停用/降級低存活 adapter;R2c → strip 由 telegraph 主導,改內容/放置 | 兩個都做 |
| **補測試(廉價,非 gate)** | #2b Keep-Alive **G5a** 缺測(R9) | `running_job()` 已實作(同 process 分頁重開可恢復 polling),但**無對應測試**;與刻意延後的 G5b 不同 | 補一個 G5a rehydrate 測試 |
| **P3 現狀接受** | #2 Keep-Alive G5b · #2c recheck 無 timeout(R10) · #4 Pydantic 閉環 | 計畫文件中明列「刻意延後」/ LITE 單操作者在場模型下無上限亦可接受 | 不動工,記成已決策延後 |

## Requirements

**P1 — Adapter 成功率可觀測性 (#5,動工)**

> 稽核更正(review code-verified):per-adapter **發布成功率其實已經 ship**(`webui_app/health_metrics.py` 的 `per_adapter()` + `AdapterHealth` dataclass,`templates/health.html` 已渲染)。目前的混合 `{ok,fail}` 只是另一個獨立的視窗摘要(`_pipeline_summary()`)。所以 #5 的淨新增工作比原想的窄:**live 存活率第二欄** + **per-window 拆分**。

- R1. 以既有的 `per_adapter()`(publish-success)為基線**擴充**,而非重建;確保 per-adapter 粒度在 health 介面清楚可見,取代以混合 `{ok,fail}` 判讀 adapter 健康。
- R2a. **發布成功率欄(確定可 ship,P1 底線)**:per-adapter publish 成功率,沿用既有 `per_adapter()` 查詢。
- R3. R2a × 時間窗(w24h / w7d / w30d)。**注意這是新的查詢形狀,不是「沿用」**:現有 `per_adapter()` 只跑單一 30d 窗,帶三窗的 `_pipeline_summary()` 又是混合、非 per-adapter。
- R4. (隨 R2b 一起,見下)兩欄落差大(貼得上但留不住,如 telegraph strip 56–67%)時須一眼可見。

**P1 — #1 SQLite 併發資料風險量化(R5,動工)**
> review 升級理由:#1 已 ship 到生產卻從未壓測;`#5` 儀表板**偵測不到** lost-update / torn-write(那是資料層故障,非 adapter 成功率訊號)。記憶亦載「atomic_write 不防跨進程 lost-update」。故不再排 P2 之後,與 #5 並列 P1,至少先跑一次量化。
- R5. (#1) 對 `webui.db` 補一個真實資料量 / 併發壓測(request 執行緒 + APScheduler worker 同時讀寫),**量化**是否存在 lost-update / torn-write;先量化風險,不預設要修。

**Release-gate — #3 LITE 網路信任邊界 E2E(R6,出貨前必綠)**
> review 升級理由:這是 WebUI 對外**唯一**信任邊界,不能列為可無限延後的補強。**不阻擋 P1 開工,但出貨前必須綠燈**。
- R6. (#3) 對 LITE 的 loopback-only 綁定 + DNS-rebinding 威脅模型補 E2E 驗證。**過關標準**:枚舉所有狀態改寫路由(POST/PUT/PATCH/DELETE),逐一斷言皆經 `_check_bind_origin_or_abort` + CSRF guard;E2E 以偽造 Host/Origin 標頭驗證 abort。涵蓋「macro 化 binding partial 漏傳 csrf_token → silent 403」這個隱蔽路徑。

**P1 — #5 存活/strip 觀測(R2b + R2c,動工)**
> 產品決策已定(操作者:**兩個都要**)。兩欄答兩個不同問題:R2b「哪個 **adapter** 留不住」驅動 adapter 取捨;R2c「哪種 **放置/平台** 被 strip」驅動內容策略。資料面 review 已驗證可得(`link.rechecked` 帶 `payload.platform`,`GROUP BY` 聚合即可,非資料管線;但須讀 events.db,ledger liveness 欄 stale)。
- R2b. **live 存活率欄(per-adapter)**:per-adapter 發布後存活(連結仍活 + dofollow 未被 strip),驅動「停用/降級低存活 adapter」。對應既有 publish 側 `per_adapter()`,新增 `GROUP BY platform` over `link.rechecked`。
- R2c. **per-platform strip 診斷**:依放置/平台維度顯示 strip 率(non-author 跑通率、深層頁 strip 等),驅動「改內容深度/放置」。telegraph ~86% strip 應在此一眼可見。**注意 R2c 的分組維度與 R2b 不同**(strip 形態 vs adapter),planning 需確認 events.db verdict 是否帶足夠維度,否則 R2c 範圍可能大於 R2b。

**補測試 — #2b Keep-Alive G5a rehydrate(R9,廉價,非 release-gate)**
> review 新發現(本次稽核補入):G5a 與 R7 的 G5b **是兩回事,勿混淆**。G5b=「跨 process 重啟」恢復,刻意延後。G5a=「同 process 內分頁重開」恢復,**已實作**——`keepalive_job.py` 的 `running_job()` + 前端 `keep_alive.js:634-638` 在頁面載入時讀 `window.__keepAliveRunningJob` 並 `beginPolling`。問題只是**這條已實作路徑沒有測試**(`test_webui_keepalive_recheck_job.py` 未涵蓋 rehydrate)。
- R9. (#2b) 對 G5a 補一個測試:recheck job running 中,模擬分頁重開(再次 GET `/ce:keep-alive` 或呼叫 `running_job()`),斷言回傳 in-flight job 且前端能恢復 polling。廉價、補既有功能的回歸保護,不阻擋任何 gate。

**P3 — 已決策延後 (#2 / #4,現狀接受)**
- R7. (#2) 正式記錄:Keep-Alive **G5b(跨 process 重啟存活 rehydrate)維持延後**(≠ R9 的 G5a 同-process 分頁重開,後者已實作只補測試)。理由:recheck 冪等且廉價、scorecard 重啟會重繪、LITE 為單操作者在場模型。**對 LITE 發布的再確認**:此延後成立的前提「單操作者在場、LITE 範圍內無長跑無人值守 recheck」在發布版仍為真——故維持(非僅因「以前延後過」)。記下**重啟觸發條件**(見下)。
- R10. (#2c) 正式記錄:recheck job **無明確 timeout 上限,維持現狀接受**。對照:gap-closure 子程序有 2h timeout,recheck 本身無上限。理由:LITE 單操作者在場、recheck 由操作者觸發、probe 例外已穩定落成 `probe_error` verdict(`keepalive_job.py:251-253`),不會無聲掛死。**重啟觸發條件**:一旦出現無人值守 / 排程化 recheck(與 R7 同前提一旦破),須補 timeout + 上限保護。
- R8. (#4) 正式記錄:Pydantic payload models **維持 opt-in 並行層,不接管真實路徑**。`test_payload_types_divergence.py` 作為防漂移柵欄已足夠。**安全邊界聲明**:`schema.py` 的 dict validators 是 publish payload 的**唯一 authoritative 安全邊界**,呼叫端不得據 Pydantic 層略過 dict 驗證。重啟觸發條件除「漂移第三次」外,加一條:**publish target 一旦新增任何注入 / SSRF 相關欄位、或 authoritative 層涵蓋面不足時,立即重啟收斂**。

## Success Criteria

- **P1 #5 (R2a/R3)**:打開 health/報告即可看到每個 adapter 在三個時間窗(w24h/w7d/w30d)各自的 **publish 成功率**;一個 publish 表現差的 adapter 無須手動稽核 events.db 即浮現。有對應測試。
- **P1 #1 (R5)**:壓測可重跑,且**輸出明確結論**——webui.db 在併發下「有/無」lost-update / torn-write。不是「跑過了」,是「量化出風險值」。
- **Release-gate #3 (R6)**:逐路由 guard 斷言 + 偽造 Host/Origin 的 E2E 全綠;此關**出貨前必綠**,但不阻擋 P1 開工。
- **P1 #5 存活/strip (R2b/R2c)**:health/報告同時看得到 per-adapter live 存活率(R2b)與 per-platform strip 診斷(R2c);telegraph 等高 strip 平台、低存活 adapter 各自一眼可見。各有對應測試。
- **補測試 #2b (R9)**:G5a rehydrate 有一個會紅→綠的測試,證明同-process 分頁重開能恢復 in-flight recheck job 的 polling。
- **P3**:`docs/solutions/` 或計畫文件中存在一條明確「接受現狀 + 重啟觸發條件」紀錄;R7/R8/R10 不再出現在任何 active backlog。

## Scope Boundaries

- **不開硬性發布閘**:本次是收斂分類,非 go/no-go gate。唯一例外是 #3(R6)被標為 release-gate(單項出貨前必綠),不擴及全域。
- **#2 / #4 不寫任何程式碼**:收斂結果是文件決策,不是實作。
- **#5 不擴成完整 analytics**:只補 per-adapter 欄位 + 既有時間窗,不引入新儀表板框架、不接 GA4(自有金錢站語料不足,見既有決策)。「per-adapter 觀測」在範圍內、「analytics 框架」不在。
- **#1 先量化不預設修**:R5 是量化壓測,若量出風險,修復另立計畫,不在本次範圍。
- **R6 不阻擋 P1 開工**:E2E 是 release-gate(出貨前綠燈),不是 #5 的前置——但**不可無限延後**。

## Key Decisions

- **初版三層分類 → review 後調整**(操作者確認 A/B/C 三項):
  - 原 P1=#5 兩欄 → 拆為 **R2a publish 欄(P1 動工)** + **R2b live 欄(待產品決策,gated)**。
  - 原 #1 列 P2 → **升 P1**(B):已上線未量化的併發資料風險,儀表板偵測不到,須先量化。
  - 原 #3 列 P2 → **升 release-gate**(A):唯一網路信任邊界,出貨前必綠但不阻 P1。
- **#5 publish 欄擴充既有查詢**:per-adapter publish 成功率已 ship(`per_adapter()`),淨新增是 per-window 拆分,小改。
- **R2b + R2c 都做(產品決策已定)**:操作者選「兩個都要」。R2b(per-adapter 存活)驅動 adapter 取捨;R2c(per-platform strip 診斷)驅動內容/放置。資料面已驗證可得(`GROUP BY platform`,非管線);R2c 的分組維度與 R2b 不同,planning 須確認 verdict 維度是否足夠。
- **#2 / #4 接受現狀**:兩者皆為計畫文件中既有的刻意延後,收斂動作是「記成已決策」而非「執行」(操作者確認);R7/R8 已補「對 LITE 發布再確認前提」與「安全邊界聲明」。

## Dependencies / Assumptions

- **已驗證(原為假設)**:events.db 的 `link.rechecked` 事件已按 adapter 歸因(`payload.platform`),`link_stripped`/`dofollow_lost` verdict 已存在,故 R2b 的 live 存活率**可直接由 events.db 聚合**,無須新資料管線。唯一注意:ledger liveness 欄 stale(writeback 延後),須讀 events.db 而非 ledger。
- per-adapter 名單由 `publishing.registry.registered_platforms()` 動態提供(adapter registry,post-R9)。

## Outstanding Questions

### Resolve Before Planning
- (無)— R2b 的產品問題已解決:操作者選「兩個都要」,R2b(per-adapter 存活)+ R2c(per-platform strip 診斷)皆動工。Planning 全面解鎖。

### Deferred to Planning
- [Affects R1][Technical] per-adapter 指標的輸出位置:health 路由(`webui_app/routes/health.py`)、CLI 報告(`_report_format.py`)、還是兩者都要?(若「兩者」會把 P1 面積加倍)
- ~~[Affects R2] events.db 是否已能按 adapter 歸因 recheck 結果~~ → **review 已解決:可得,見 R2b**。
- [Affects R7/R8][User decision] #2 / #4 的「重啟觸發條件」具體寫什麼(例:#2 「當出現非操作者在場的長跑 recheck 需求時」;#4 「當 dict validators 與 Pydantic models 第三次漂移時」)。可在 planning 或落紀錄時定。
- [Affects R5][Technical] SQLite 壓測兩個未定義:(a)「真實資料量」過關基準(幾筆 / 幾併發);(b) 壓測對象是「一次性遷移腳本」還是「對 live `webui.db` 的就地併發讀寫」,以及如何繞過 conftest 的 socket-block + 四個 autouse 隔離 fixture(參考 `circuit.py` flock 需兩個真 OS process 的先例)。

## Next Steps

Resolve-Before-Planning 已清空,全部單元可進 planning。
→ `/ce:plan`:
- 單元 1:#5 publish 欄擴充(R2a + R3)
- 單元 2:#5 存活/strip 觀測(R2b per-adapter 存活 + R2c per-platform strip 診斷)
- 單元 3:#1 SQLite 併發壓測量化(R5)
- 單元 4:#3 LITE 信任邊界 E2E release-gate(R6)
- 單元 5:#2/#4/#2c 決策紀錄(R7 + R8 + R10,寫入 `docs/solutions/`)
- 單元 6(廉價,可併入任一單元):R9 G5a rehydrate 回歸測試
