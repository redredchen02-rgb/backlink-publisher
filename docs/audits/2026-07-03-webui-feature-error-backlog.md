# WebUI 逐功能驗證與優先序 backlog（U14 產出，2026-07-03）

對應 [docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md](../plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md) 的 U14（R15）。本文件是唯讀盤點的產出物，U14 本身不修改任何原始碼。

## 方法（分兩輪，兩輪都已完成）

1. **第一輪：後端/靜態層 curl 掃描**——對全部 legacy 頁面路由、SPA 頁面依賴的 `/api/v1/*`／`/api/*` 端點、SPA bundle 資產發 GET 請求，檢查 HTTP 狀態碼與伺服器端錯誤標記。
2. **第二輪：瀏覽器層走查**（使用者確認用 Browser 2／Windows／本機後執行）——用 `claude-in-chrome` 實際開瀏覽器逐一造訪 22 個 URL，讀 console/network 錯誤、看渲染畫面，讓既有五個前端擷取掛點在真實 JS 執行環境下運作。

**兩輪共同的殘留限制**：這個執行個體雖然已有 5 個綁定 channel（Medium／notes.io／Rentry／Telegraph／txt.fyi，第二輪走查才發現——比第一輪 curl 掃描當下的判讀更豐富），但仍然**沒有任何發佈歷史、沒有進行中 campaign**——`history_store`/`drafts_store` 是空的。這直接觸發了下面第 2 條最重要的發現（`pipeline:never_run` 降級橫幅），但仍未覆蓋「有真實發佈歷史／campaign 時」的渲染與互動路徑。

## 資料來源 1：錯誤回報儀表板現況

`GET /api/v1/error-reports` → `{"items": [], "total": 0}`，**兩輪走查前後皆為 0**——即使第二輪瀏覽器走查中親眼看到兩個真實、可重現的使用者可見錯誤畫面（見下）。這件事本身是本輪最重要的發現，見「結構性缺口」一節。

## 資料來源 2＋3：功能清單 × 現況比對

### Legacy route 模組（37 個，`webui_app/routes/*.py`）

| 模組 | 對應主要 GET 頁面路由 | 結果 |
|---|---|---|
| `main.py` | `/` | 200；**顯示持續性「系统降级」橫幅**（見下方發現 #2）；dual-live（未 redirect 到 SPA） |
| `sites.py` | `/sites` | 200，第二輪走查無錯誤 |
| `batch_campaign.py` | `/batch-campaign` | 200，表單正常渲染（含平台勾選） |
| `schedule.py` | `/schedule` | 302 → `/app/schedule`（已 redirect，計畫快照已過時） |
| `dashboard.py` | `/ce:history`、`/ce:dashboard` | `/ce:history` 200，**同樣顯示「系统降级」橫幅**；dual-live（計畫快照誤把這條列成 `/schedule`） |
| `health.py` | `/ce:health`、`/ce:health/publish-metrics` 等 | 200，深色 dashboard 正常渲染，無 console/network 錯誤；legacy-only |
| `health_actions.py` | `/ce:health/*` 動作端點 | 安全排除（POST） |
| `command_center.py` | `/ce:command-center`、`/ce:command-center/jobs` | 200，正常渲染，無錯誤；legacy-only |
| `copilot.py` | `/copilot/advice` | 404——LITE 設計行為，非 bug |
| `pr_queue.py` | `/pr-queue` | 404——LITE 設計行為，非 bug |
| `metrics.py` | `/metrics` | 未走查（技術性端點） |
| `optimization_status.py` | `/optimization-status` | 302 → `/app/optimization-status`；SPA 頁第二輪走查無錯誤 |
| `equity_ledger.py` | `/ce:equity-ledger` | SPA 對應頁 `/app/equity-ledger` 第二輪已測，無錯誤；legacy 版本仍未補測 |
| `equity_batch_recheck.py` / `equity_gap.py` | 動作端點 | 安全排除 |
| `keep_alive.py` | `/ce:keep-alive` | SPA 對應頁 `/app/keep-alive` 第二輪已測，無錯誤；legacy 版本仍未補測 |
| `survival_dashboard.py` | `/survival-dashboard` | 302 → `/app/survival`；SPA 頁無錯誤 |
| `drafts.py` / `history.py` / `profiles.py` | 無獨立 GET 頁 | 對應 SPA 頁第二輪已測，空態正常 |
| `queue.py` | 無獨立 GET 頁 | 未直接測試 |
| `batch.py` / `batch_sites.py` | 動作端點 | 安全排除 |
| `campaign_progress.py` | `/campaign/<id>` | 未走查——無真實 campaign id |
| `checkpoint.py` | 動作端點 | 安全排除 |
| `settings_basic.py` | `/settings` | 302 → `/app/settings`；SPA 頁見下方發現 #1（瞬時卡頓，非確定性 bug） |
| `publish_defaults.py` | `/publish/defaults` | 204，待查（未在第二輪覆蓋） |
| `oauth.py` | OAuth callback | 未走查（需真實憑證流程） |
| `llm.py` / `image_gen.py` | 設定子面板 | 刻意保留的測試 patch 對象，不在本輪範圍 |
| `url_verify.py` | 無獨立 GET 頁 | 未走查 |
| `pipeline.py` 系列 | `/api/v1/pipeline/*` | 安全排除（POST） |
| `spa.py` | `/app/*` | 200，bundle 資產正常 |

### SPA 頁面（15 個）—— 第二輪瀏覽器走查逐頁結果

| 路由 | 結果 |
|---|---|
| `/`（PublishWorkbench） | ok，全部請求（含 `/api/v1/app-config`）200 |
| `/history` | ok，空態，無錯誤 |
| `/drafts` | ok，空態 |
| `/sites` | ok，渲染設定表單（1 筆已存資料） |
| `/schedule` | ok，空態 |
| `/batch-campaign` | ok，表單含平台勾選 |
| `/settings`（+ 子分頁） | 整體 ok，但見下方發現 #1（一次瞬時空白截圖 + 30 秒逾時，重試後恢復正常且完全可互動） |
| `/monitor`、`/keep-alive`、`/survival`、`/optimization-status`、`/equity-ledger` | 全部 ok，乾淨的空態/摘要，無 console/network 錯誤 |
| `/pr-queue` | **可見錯誤畫面**：「出错了 / 发生未知错误，请重试。」+ 重試按鈕（見下方發現 #3） |
| `/error-reports` | ok，「尚无任何错误报告」 |

### 未覆蓋

`/campaign/:id`（無真實 campaign id）；legacy `/ce:equity-ledger`、`/ce:keep-alive` 頁面本身（SPA 對應版本已測，legacy 版未測）；`/publish/defaults` 的 204 語意；`llm.py`/`image_gen.py`/`oauth.py` 相關頁面（刻意排除或需要真實憑證）；所有需要真實發佈歷史/campaign 才能觸發的渲染路徑（表格有列資料、campaign 進度頁等）。

## 發現

### 發現 #1（低優先序、非確定性，暫不進 backlog）：`/app/settings` 切換子分頁時一次瞬時空白+逾時

第二輪走查點擊側邊子分頁時，一次螢幕截圖擷取回傳空白畫面並逾時（「renderer may be frozen」，30 秒），數秒後重試即恢復正常、`get_page_text` 證實所有子區塊（channel 綁定、憑證表單、Blog ID 對應、關鍵字池、排程、LLM 整合）內容都在。**懷疑但未證實**：`get_page_text` 一次抓到所有子分頁內容，暗示子分頁可能是「全部掛載在 DOM、只是切換顯示/隱藏」而非逐頁 lazy mount——若真如此，切分頁時的一次性 reflow/repaint 成本會隨子分頁數量疊加，可能是這次瞬時卡頓的成因。**非確定性重現，暫不列入 U15 backlog**；若使用者也曾感覺設定頁「偶爾卡一下」，值得下一輪針對性重現。

### 發現 #2（高可見度，需要產品判斷，建議列入 backlog）：`/` 與 `/ce:history` 持續顯示「系统降级」橫幅

根因已追到 `webui_app/services/health_projection.py:90-91`：只要 `history_store` 是空的（`last_pipeline_run is None`），就無條件把 `degraded_reasons` 加上 `"pipeline:never_run"`、`healthy` 設 `False`，對應的 `/health` 端點回 **503**，首頁 JS（`static/js/index.js:329`）據此渲染紅色/警示色「系统降级 · pipeline:never_run」橫幅。

這是**刻意設計**（程式碼本身有意識地把它當一種健康訊號），不是程式碼層面的 bug——但語意上把「這個安裝從來沒發佈過任何東西」跟「系統目前故障」用同一個「degraded ＋ 503」管道呈現，對任何全新安裝或剛設定完 channel、還沒來得及發第一篇的使用者來說，首頁會**持續**顯示一個看起來很嚇人的警示，直到成功發佈過一次為止。**這很可能就是使用者「時常看到功能報錯」感受的一部分來源**——不是某個按鈕壞了，而是主入口頁面本身在正常、預期的使用情境下（剛裝好、還沒發過文）長期顯示警示狀態。

**這不在既有 U1–U13 任何 unit 範圍內**（U2 只動 Docker healthcheck 目標、明確不碰這個 richer-readiness 端點的語意；U6 是移植 `/ce:health` 叢集，是不同的健康檢查機制）。**是否要處理、怎麼處理是一個產品判斷**（例如：「從未發佈」是否該算「degraded」？該用 503 還是 200＋提示？橫幅文案要不要區分「你還沒開始」跟「東西壞了」？），不是我能單方面決定的規格變更——列入 backlog 但標記「需要使用者拍板」，不在 U15 未經確認就自行修改。

### 發現 #3（中優先序，獨立 bug，建議列入 backlog）：`/app/pr-queue` 在 LITE 版下顯示通用「未知錯誤」而非「功能未開放」

後端 `/api/pr-queue` 在 LITE 版下 404 是設計行為（`LITE_HIDDEN_BLUEPRINTS`），但 SPA 前端拿到這個 404 後，`classifyError` 沒有把它識別成「此功能在目前版本不可用」，而是落到通用分支顯示「出错了 / 发生未知错误，请重试。」+ 一個永遠不會成功的重試按鈕。這是一個真實、可重現、獨立於既有 unit 範圍的小 bug——**不是資料層問題，是前端錯誤分類遺漏了 LITE-hidden 這個案例**。

### 發現 #4（結構性、影響本計畫方法論本身，需要使用者決定）：錯誤回報儀表板無法擷取 StateBlock 內聯錯誤狀態

發現 #2 與#3 都是使用者一眼就能看到的真實錯誤畫面，但整輪走查後 `/api/v1/error-reports` 始終是 `{"items":[],"total":0}`。原因：儀表板的五個擷取掛點（`window` error/`unhandledrejection`/Vue `errorHandler`/`router.onError`/query-mutation cache/Pinia `$onAction`）擷取的是**未預期的例外**；而 `StateBlock` 顯示「出錯了」或系統橫幅走的是**正常、受控的程式碼路徑**（API 回應被正確分類成錯誤狀態並渲染）——對錯誤擷取機制來說這不是一個「例外」，所以永遠不會被記錄。

**這是一個比任何單一功能 bug都更根本的落差**：只要一個錯誤被 UI 「優雅處理」，它就完全不會進儀表板，使用者只能自己記得、口頭描述——這正是 2026-07-01-002 錯誤回報計畫當初想解決但顯然沒完全解決的問題（該計畫的 Problem Frame 也承認「確切重現步驟」的擷取被刻意延後）。**這不在本次擴充的 Scope Boundaries 內**（K：U14/U15 明確「不重建或修改該儀表板本身的擷取/儲存/呈現邏輯」），修這個需要碰已完成計畫的程式碼，是範圍外的決定——**列在這裡供使用者評估是否要另開任務**，不由 U14/U15 自行擴權處理。

## 優先序 backlog（U15 輸入）

| # | 症狀 | 使用者可見度 | 修復成本粗估 | 去重狀態 |
|---|---|---|---|---|
| B1 | `/app/pr-queue` 在 LITE 版下顯示通用「未知錯誤」而非「功能未開放於 LITE 版」 | 中（只有點進 pr-queue 才看到，且僅 LITE 版） | 簡單 | **已修復**（2026-07-03，分支 `fix/pr-queue-lite-error-message`，見下方「已完成」） |
| B2 | `/`、`/ce:history` 首頁在「從未發佈過」的正常情境下持續顯示「系统降级」紅色橫幅 | **高**（每次打開主入口都看到，任何新安裝/新設定完 channel 但還沒發第一篇的使用者都會遇到） | 需要先有產品決策（見發現 #2），程式碼修改本身不難 | **已修復**（2026-07-06，分支 `fix/pr-queue-lite-error-message-2`，見下方「已完成」） |
| B3〔2026-07-03，B1 code review 發現〕 | `frontend/src/api/prQueue.ts` 的 `fetchPrQueue()`/`updatePrStatus()` 沒有 timeout/AbortController（`frontend/src/api/client.ts` 的 `getJson`/`sendJson` 有 15s timeout + 重試，這兩個手寫 `fetch` 呼叫繞過了它）——後端若 hang，使用者卡在 loading 骨架、刷新按鈕被 disabled，沒有逃生路徑 | 低（僅在後端異常掛起時才會遇到，屬邊角情境） | 中（改用 `client.ts` 的 `getJson`/`sendJson` 取代手寫 `fetch`，需確認錯誤形狀相容） | **已修復**（2026-07-06，分支 `fix/pr-queue-lite-error-message-2`，見下方「已完成」） |
| B4〔2026-07-03，B1 code review 發現〕 | `PrQueuePage.vue` 的 `load()` 沒有 request-generation 防護，`markStatus()` 的內部重新載入與手動「刷新」按鈕可並發觸發多次 `load()`，最後 resolve 的（不一定是最後啟動的）會覆蓋 `items`/`error`/`liteUnavailable`，可能讓過期的錯誤狀態蓋掉之後成功的資料 | 低（需要快速連續操作才會踩到，UX 級而非資料損毀） | 中（加一個遞增的 request-generation counter，~8-10 行） | **已修復**（2026-07-06，分支 `fix/pr-queue-lite-error-message-2`，見下方「已完成」） |
| B5〔2026-07-06，B2 code review 發現〕 | `_initHealthBar()` 的 `/health` fetch resolve 時無條件 `bar.classList.remove('d-none')`，若使用者在 fetch 進行中點擊「關閉」橫幅按鈕，稍後 resolve 的回應會悄悄把已關閉的橫幅重新顯示出來 | 低（需要在 fetch 進行中恰好點擊關閉才會踩到，邊角情境） | 低（在 `.then()` 開頭重新檢查 `sessionStorage.getItem(DISMISS_KEY)` 並提早 return） | **既存缺陷，非 B2 引入**（`_initHealthBar()` 的整體結構在 B2 之前就存在；B2 的 diff 只新增 `neverPublished` 分類邏輯，未改動這段 fetch/dismiss 互動）；獨立，未排入本輪 |

## 已完成

- [x] **B1**（2026-07-03，分支 `fix/pr-queue-lite-error-message`）：`frontend/src/pages/PrQueue/PrQueuePage.vue` 現在會先讀 `/app-config` 的 `lite_edition` 旗標，LITE 版下直接跳過必然 404 的 `fetchPrQueue()` 呼叫，改顯示 `StateBlock` 的 `empty` 狀態「PR 机会队列在当前版本（LITE）中未开放。」，不再是通用「出错了」+ 打不通的重試按鈕。沒有動後端 404 gate（刻意維持「跟任何未匹配路徑一樣」，不洩漏隱藏路由存在）也沒有動共用的 `classifyError` 分類法（範圍只限本頁）。新增 `PrQueuePage.spec.ts`。`ce-code-review`（10 位 reviewer：correctness/testing/maintainability/project-standards/agent-native/learnings/security/reliability/kieran-typescript/julik-frontend-races）跑過一輪，其中 correctness＋reliability＋kieran-typescript 三方獨立收斂到同一個真實問題：初版把 `/app-config` 讀取與 `fetchPrQueue()` 包在同一個 try/catch，導致 `/app-config` 瞬斷會誤擋住原本健康的 `/api/pr-queue`——已修正為「best-effort、fail-open」（`/app-config` 失敗時預設當作非 LITE，照常嘗試 `fetchPrQueue()`），並補測試涵蓋這條路徑與 `lite_edition` 欄位缺失的情況。測試最終 6 案例，`npm test` 246/246 綠、typecheck 乾淨（3 個既有無關錯誤不受影響）。審查中發現兩個既存（B1 之前就有）、獨立於本次修復的缺陷已記錄為 B3／B4；race-condition／無 timeout 相關發現與此次修復無關，不阻擋本次合併。

- [x] **B2**（2026-07-06，分支 `fix/pr-queue-lite-error-message-2`）：使用者決策——保留 `/health` 的 `healthy`/`degraded_reasons`/503 語意不變（監控用途不受影響），但橫幅呈現改為區分兩種狀態：`degraded_reasons` 恰好只有 `["pipeline:never_run"]` 時，顯示中性資訊色（`--info-soft`）+ ℹ️ 圖示 +「尚未发布任何内容 · 完成渠道设置后即可开始发布」；其餘任何 degraded 情境（含 `pipeline:never_run` 與其他原因並存）維持原本紅色警示（`--danger-soft`）+ ⚠️ 圖示 + 完整原因列表，不弱化真正的故障訊號。只改 `webui_app/static/js/index.js`（`_initHealthBar`）+ `webui_app/static/css/index.css`（新增 `.health-summary-bar.pending`，重用既有 `--info-soft` token，未新增任何 raw color literal，`test_webui_css_no_raw_colors.py` 的 ceiling 不受影響）；`health_projection.py` 完全未動。`/ce:history` 共用同一個 `index.html`/`index.js`，一併修復。以獨立 webui 執行個體（全新 `BACKLINK_PUBLISHER_CONFIG_DIR`，重現「從未發佈」情境）在真實瀏覽器驗證：橫幅正確顯示 ℹ️ 資訊態；並以合成的多原因 `degraded_reasons` payload 驗證真正故障情境仍正確落在 `.degraded`（紅色、⚠️、完整原因列表）——沒有掩蓋真正的降級訊號。`test_webui_health_routes.py`／`test_webui_css_no_raw_colors.py` 全綠（後端契約無回歸）。

〔B2 code review 修正，2026-07-06，同分支追加 commit〕`ce-code-review`（7 reviewer：correctness/testing/maintainability/project-standards/agent-native/learnings/julik-frontend-races）跑過一輪。testing＋maintainability 兩方獨立收斂到同一個問題：`'pipeline:never_run'` 字串在 `health_projection.py` 與 `index.js` 兩處硬編碼、無任何機制保證兩邊同步——已加一個跨檔一致性測試釘住（`test_health_bar_never_run_literal_matches_backend`）。testing 另外指出「legacy `static/js/` 沒有自動化前端測試框架」的說法並不完全準確——`tests/test_webui_feedback_states.py` 早就用「讀原始碼字串斷言」的模式測過同一個 `index.js` 檔案的其他分支（如 `test_index_error_path_routes_through_classify_error`），只是沒套用到這次的新分支——已補 4 個測試（`test_health_bar_distinguishes_never_published_from_real_degraded`、`test_health_bar_pending_state_has_distinct_icon_and_copy`、`test_health_bar_pending_css_reuses_info_soft_token`、`test_health_bar_never_run_literal_matches_backend`），全綠。project-standards 發現新增的 `docs/plans/2026-07-06-001-...-plan.md` 缺少 2026-05-20 後強制要求的 `claims:` frontmatter（`plan-check` 實測 exit 8）——已補 `claims: {}`（parked、無實作單元的計畫適用此 opt-out），重測 exit 0。julik-frontend-races 發現一個**真實、獨立於 B2 的既存 bug**：`_initHealthBar()` 的關閉按鈕呼叫 `delegate(bar, '[data-action="health-bar-dismiss"]', 'click', handler)`，但 `delegate()` 實際簽章是 `(root, type, selector, handler, opts)`——第二三個參數對調，導致關閉按鈕從 2026-06-09 這個健康橫幅功能上線以來從未真正生效過（比對檔案內其餘 5 處 `delegate()` 呼叫，全部順序正確）。已修正參數順序，並在真實瀏覽器點擊驗證：修前 class 不變，修後正確加上 `d-none`。另外還發現一個較低優先序的既存 race（fetch resolve 時無條件清除 `d-none`，可能在使用者剛點擊關閉後把橫幅悄悄叫回來）——記錄為 backlog 的 B5，本輪未修。agent-native／learnings 兩方皆為 PASS/無阻擋發現。**這個 legacy 頁面沒有自動化前端「執行時」測試框架**（`static/js/` 沒有 jest/vitest runtime harness），但如上所述，既有的「讀原始碼字串斷言」模式已可覆蓋這次的變更，不是無法測試。

- [x] **B3**（2026-07-06，分支 `fix/pr-queue-lite-error-message-2`）：`frontend/src/api/prQueue.ts` 沒法直接改用 `client.ts` 的 `getJson`/`sendJson`——後者寫死 `API_BASE = '/api/v1'`，而這是 legacy `/api/pr-queue` 端點（見檔案自己的開頭註解）。改法是在 `prQueue.ts` 內就地實作一個對稱、範圍限縮的 `_fetchWithTimeout`（AbortController + 15s，等同 `client.ts` 的 `DEFAULT_TIMEOUT_MS`），不拉入 `client.ts` 整套 dedup/retry/CSRF-refresh 機制（這個 bug 只缺 timeout，不缺那些）。`fetchPrQueue()`/`updatePrStatus()` 均已套用。新增 `frontend/src/api/prQueue.spec.ts`（7 案例，含「fetch 收到 AbortSignal」與「逾時時 reject 而非卡住」兩條直接釘住本次修復的測試），沿用 `client.spec.ts` 既有的 `vi.stubGlobal('fetch', ...)` 測試慣例。

- [x] **B4**（2026-07-06，分支 `fix/pr-queue-lite-error-message-2`）：`PrQueuePage.vue` 的 `load()` 新增遞增的 `loadGeneration` 計數器——每次呼叫 `load()` 時鎖定自己的世代編號，在每個可能被搶先的檢查點（`/app-config` 讀取後、`fetchPrQueue()` resolve 後）確認自己仍是最新世代才寫入 `items`/`error`/`liteUnavailable`/`loading`，過期的呼叫直接靜默返回。新增測試（`PrQueuePage.spec.ts`）模擬兩個不同列的 `markStatus()` 幾乎同時觸發：驗證較早啟動的 `load()` 在 `/app-config` 檢查點就會發現自己過期並提早返回、**連 `fetchPrQueue()` 都不會呼叫**（比原始 B4 描述的「不覆蓋已渲染資料」更早一步的防護），只有較新的呼叫真正打到網路且結果被套用。以 `git stash` 暫時還原修復、確認測試會真的失敗（會呼叫兩次 `fetchPrQueue()` 且第二次吃到 mock 佇列外的 `undefined` 而拋錯）後復原，紅綠對照確認測試有效。`npx vitest run`（255/255）、`vue-tsc --noEmit`（同前 3 個既有無關錯誤）全綠。

## 待辦

- [x] ~~**B2 需要使用者決策**~~ → 已決策並修復，見上方「已完成」。
- [x] ~~**發現 #4 需要使用者決策**~~ → 已決策：另開追蹤任務，見 `docs/plans/2026-07-06-001-feat-error-dashboard-stateblock-capture-plan.md`（`status: parked`）。順帶印證了發現 #4 本身：B2 觸發的橫幅從未進過 `/api/v1/error-reports`（走查全程 `total:0`），所以本次修復無法透過既有 `PATCH /api/v1/error-reports/<id>` 標記 resolved——儀表板從來就不知道這個錯誤存在過。
- [ ] 直接請使用者具體描述「哪個功能、什麼操作、什麼錯誤畫面/訊息」——仍然是比繼續盲目走查更高訊號密度的路徑，尤其這個實例目前仍缺真實發佈歷史/campaign 資料。
- [ ] `/ce:equity-ledger`、`/ce:keep-alive` 的 legacy 版本、`/campaign/<id>`、`/publish/defaults` 的 204 語意——仍未覆蓋。
