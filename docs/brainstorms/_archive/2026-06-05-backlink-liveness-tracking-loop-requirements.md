---
date: 2026-06-05
topic: backlink-liveness-tracking-loop
---

# 外鏈存活追蹤閉環（Per-Link Drill-Down，複用既有記分板）

## Problem Frame

外鏈發布出去後會「悄悄死掉」：被平台剝連結（link stripped）、dofollow 降成
nofollow、主機 404。底層偵測引擎已完整（5 級 verdict、events.db `link.rechecked`
時間序列、CLI+WebUI 重檢雙入口）。

**宏觀層其實也已經有了**：`scorecard/engine.py` 的 `ChannelScoreRow` 已逐平台聚合
`live_pct` / `live_dofollow` / `liveness_breakdown` / `small_sample`（小樣本誠實標記），
並由 `webui_app/health_metrics.py` → `templates/health.html` 在儀表板渲染。所以「哪個
平台最會吃鏈」這個讀取型訊號**並非缺口**——它已經在線上（這修正了本文件初稿「存活數據
從未回流」的錯誤前提）。

真正缺的、有價值的淨增量只有一塊：**從宏觀（平台聚合）點進去看微觀（每一條 URL）的
能力**。目前操作者能看到「某平台平均 strip 率」，但**看不到該平台/目標底下每一條鏈結
各自的生死**——無法逐條 trackable，也無法對單條即時重檢。

這是一個「宏觀掃描 → 微觀查單條」的探索需求：在既有記分板底下，加一個**逐條鏈結明細
抽屜**，讓操作者點某平台/目標就能展開看到每條 URL 的 verdict，並單條重檢。回饋仍刻意
做成**讀取型**——操作者看完自行決定下次別發哪個平台，不自動接回發布器。

## User Flow

```
┌─ 操作者打開既有 health 儀表板 ───────────────────────────────┐
│                                                              │
│  [Per-Channel Scorecard]  ← 已存在,複用不重建                │
│   telegra.ph   live 14%  dofollow … N=40  ⚠小樣本?  …       │
│   ghpages      live 84%  dofollow … N=22                     │
│        │                                                     │
│        │ ★新增★ 點某平台列 → 展開逐條抽屜                     │
│        ▼                                                     │
│  [逐條鏈結明細抽屜]  ← 本案唯一淨增量                          │
│   url₁  ALIVE          檢查於 6/2 14:00   [重檢]            │
│   url₂  LINK_STRIPPED  檢查於 6/2 14:01 🔴 [重檢]           │
│   url₃  DOFOLLOW_LOST  檢查於 6/2 14:01   [重檢]            │
│   （rel / anchor-drift 僅在 ALIVE 列有意義時才顯示）          │
│   （example.com 測試列預設過濾或標記）                        │
│        │  單條 [重檢] → 走會寫 link.rechecked 的那條路        │
│        │  → 該列 verdict + 時間就地更新                       │
│        ▼                                                     │
│  操作者讀完,自己決定下次別發 telegra.ph(讀取型,不自動接回)   │
└──────────────────────────────────────────────────────────────┘
```

## Requirements

**逐條鏈結抽屜（Per-Link Drill-Down — 本案核心）**
- R1. 在既有記分板（health 視圖的 `ChannelScoreRow`）每一列可**展開**，看到該平台
  底下**每一條已發布鏈結的獨立列**。資料源為 events.db `link.rechecked` 時間序列，
  取每條鏈結的**最新** verdict。
- R2. 每條鏈結列顯示：published URL（即 `live_url`，本庫無獨立 published_url 欄）、
  平台、最新 verdict（ALIVE / HOST_GONE / LINK_STRIPPED / DOFOLLOW_LOST /
  PROBE_ERROR）、最後檢查時間（`ts_utc`）。
- R3. 單條鏈結可即時重檢，且**必須走會寫 `link.rechecked` 事件的重檢路徑**
  （`recheck_link` → `emit_recheck`，即 keepalive 那條），重檢後該列 verdict 與時間
  就地更新。**不可**用只回傳二元 ok/failed、不發事件的 `recheck_one` 路徑，否則抽屜
  讀到的時間序列不會更新。
- R4. PROBE_ERROR 的鏈結列**照常顯示**在抽屜中（操作者要看得到「這條沒測成功」），
  但任何存活率/strip 率計算都不計入其分母（與既有 gap 引擎「不確定不進缺口」一致）。

**資料誠實性（Data Honesty）**
- R5. anchor 漂移與 target rel **只在 verdict == ALIVE（實際檢視過目標頁）時才顯示**；
  在 HOST_GONE / LINK_STRIPPED / PROBE_ERROR 等死鏈/未檢視的列上，這兩個欄位是
  探測早退時的預設值（`anchor_drift=False`、`target_rel=None`），**必須渲染為「—／n/a」
  而非「無漂移／dofollow」**，以免把「沒測」誤顯示成「測得正常」。
- R6. 抽屜的逐條列**預設過濾或明確標記 example.com / 測試 fixture 來源**的鏈結，避免
  真實鏈結被測試資料淹沒（events.db 目前以 example.com 為主，真實自有佔比 ~0.6%）。

**閉環定位（Scope / Governance）**
- R7. 回饋為**讀取型**：抽屜與記分板只呈現訊號供判讀，**不**自動修改 plan-gap、
  發布優先級或平台白名單。操作者看完自行決定下次發布策略。

## Success Criteria
- 操作者能在既有 health 記分板上，對任一平台列**展開看到該平台底下每一條外鏈現在是死
  是活、何時檢查的**，並能對單條一鍵重檢、就地看到結果更新。
- 死鏈列不會出現誤導性的「無 anchor 漂移／dofollow」資訊（顯示 n/a）。
- 抽屜呈現的是真實鏈結，測試資料不混入（或明確標記為測試）。
- 全程不需離開儀表板、不需翻 CLI 或 events.db raw。

## Scope Boundaries
- **不**重建平台聚合記分板——R5–R7（原初稿）已被既有 `scorecard/engine.py` +
  `health.html` 滿足，本案**複用**它，只在其下掛逐條抽屜。
- **不**做逐條列的 verdict 篩選/排序——目前真實鏈結僅 ~73 條，量級不需要；待鏈結量
  起來再加（原初稿 R3 降級為 deferred）。
- **不**自動把訊號接回發布決策（plan-gap / 平台白名單 / 發布優先級不動）。
- **不**新建偵測引擎或改 verdict 分類——5 級 verdict、events.db schema、recheck 服務
  全部沿用。
- **不**做自動排程重檢（定期 cron 屬既有 plan 的 UPGRADE 範疇；R3 的逐條即時重檢
  **在**本案範圍內，不受此限）。
- **不**做 anchor-drift 的修復工作流——僅在 ALIVE 列上顯示標記（R5）。
- **不**接 GA4/GSC 流量歸因（owned-target 語料太小，正交）。

## Key Decisions
- **複用既有 scorecard 而非重造**：審查（product-lens 0.86 / adversarial 0.88）證實
  per-channel 記分板已 ship（PR #362 系，`scorecard/engine.py`、`health.html`）。重造
  已 ship 的東西正是本專案「執行才是瓶頸、程式碼常跑在計畫前」的反覆陷阱，故砍掉。
- **唯一淨增量 = 逐條抽屜**：宏觀層已有，本案只補微觀層 + 單條重檢，把工作量從「建追蹤
  系統」縮成「一個薄抽屜」。
- **回饋維持讀取型**：自有金錢站僅 1 個、events.db 以 example.com 測試資料為主、瓶頸是
  執行——先零誤傷地把訊號攤出來，把貴的自動化延後。
- **重檢走會寫事件的路徑**：兩條既有重檢路徑中只有 `recheck_link → emit_recheck`
  會寫 `link.rechecked`；`recheck_one` 收斂成二元且不發事件。抽屜既讀時間序列，重檢
  就必須走前者（R3）。

## Empirical Grounding (events.db 實查 2026-06-05)
- 已重檢鏈結共 **88 條 distinct**（vs 1726 篇文章 / 2041 publish.confirmed）→ 重檢
  **覆蓋率僅 ~5%**：抽屜只照得到「已驗過」的這批，未驗的大多數需先補重檢才看得到。
- 重檢子集**非**測試資料主導：78/88（89%）指向真實目標（51acgs.com），僅 10 條
  example.com。adversarial「記分板全是測試雜訊」的質疑對全量發布成立、對**重檢子集
  不成立** → 逐條抽屜有真實鏈結可用，範圍不需再縮。
- 真實逐平台 strip 訊號（取最新 verdict、排除 probe_error）：telegraph(+api) 57 條
  ~42% strip（強訊號）、blogger(+api) 25 條 ~28%（可用）、ghpages N=1、medium 僅
  probe_error → 既有 scorecard 的 small_sample 旗標正確涵蓋了 ghpages/medium 的薄樣本。

## Dependencies / Assumptions
- 依賴既有 `scorecard/engine.py` / `health_metrics.py` / `health.html` 作為宿主視圖。
- 依賴 events.db `link.rechecked` 時間序列；其 payload 結構性永遠帶 verdict / live_url
  / platform / anchor_drift / indexability / ts_utc 等鍵，但見 R5：部分鍵在死鏈列上
  是預設值而非觀測值。
- 依賴 `recheck_link → emit_recheck`（keepalive 路徑）做單條即時重檢並寫回事件。

## Outstanding Questions

### Resolve Before Planning
（無——產品決策已收斂：複用記分板、只做逐條抽屜、讀取型、走寫事件的重檢路徑。可進規劃。）

### Deferred to Planning
- [Affects R1][Technical] 抽屜逐條讀取**不可**直接複用 `derive_per_target_status`
  （它 `WHERE article_id IS NOT NULL`，會丟掉 stdin/CLI 來源、NULL article_id 的重檢，
  正是 overlay.py 刻意保留的那批）；需照 overlay.py 以 `live_url` 為主鍵取最新 verdict。
- [Affects R1][Technical] 抽屜掛在 `health.html`（記分板宿主）還是同時掛 keep_alive /
  equity_ledger？建議單一宿主（記分板）+ 共用 partial，避免第三份重複視圖。
- [Affects R2/R5][Technical] 對照 `recheck/probe.py` 早退路徑，確認各 verdict 下
  `target_rel` / `anchor_drift` / `indexability` 的真實語義，定下「ALIVE 才顯示」的判斷點。
- [Affects R6][Needs research] example.com / 測試來源的判定規則（網域比對？fixture 標記？）
  與「過濾 vs 標記」的 UI 取捨；先跑一次 events.db 真實（非 example.com）逐平台計數，
  確認真實鏈結分佈再定抽屜預設。
- [Affects 記分板][Optional] 既有 scorecard 是否已明確暴露 strip-rate（或僅
  `liveness_breakdown` 可推導）；若操作者要一眼看到 strip%，可補一個衍生欄——低成本，
  非本案必需。
- [Affects R3][Technical] 單條重檢的並發/in-flight/失敗（服務錯誤 vs PROBE_ERROR 是
  兩回事）與 aria-live 更新，沿用 keep_alive.js / equity_ledger 既有狀態機樣式。
- [並行課題／非本案] 重檢覆蓋率僅 ~5%（88/1726）——抽屜的真正價值上限受此封頂。讓更多
  鏈結被檢查（既有 bulk-recheck 一鍵補檢、或日後排程重檢）是閉環的下一個瓶頸，獨立於
  本抽屜，建議另起 plan，不混入本案範圍。

## Next Steps
→ `/ce:plan` for structured implementation planning
