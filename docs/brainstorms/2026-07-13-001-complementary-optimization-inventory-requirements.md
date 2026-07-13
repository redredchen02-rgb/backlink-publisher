---
date: 2026-07-13
topic: complementary-optimization-inventory
scan_provenance: 8-lens adversarially-verified workflow (49 agents, 40/41 confirmed), deduped vs the 2026-07-13 bug-audit backlog
---

# opt: 全面優化第四輪 — 互補式掃描清單與工作包分流（Complementary Optimization Inventory）

## Problem Frame（問題框架）

這是使用者**第四次**提出「全面掃描並優化」。前三次已產出並多數落地
`2026-07-07-003-opt-backend-code-health`、`2026-07-09-001-opt-comprehensive-repo-state-and-optimization`；
同日（2026-07-13）另有一輪 14-finder bug 審計，找出 47 個 net-new bug，其中約 **34 個仍未修**。
（**校正 2026-07-13 doc-review**：原稿稱 `fix/audit-batch2` 的「SSRF/XSS/token 安全叢集」未合併——security-lens 以 `git diff main fix/audit-batch2 -- <files>` 實測發現該叢集**內容已在 `main`**（以不同 hash 落地，如 `c4f7ed9a`…；branch-ancestry 查不到、須用 content-diff）。batch2 分支上**尚未進 main 的**只剩 **P1 keep-alive 死流程** 與非安全性漂移（`safe_write.py` jitter、`circuit.py` backoff、前端檔）。)

因此本輪**刻意不重掃 bug**。經與使用者確認，方向鎖定為「全新多視角掃描」，
只針對 bug 審計**沒有深掃**的四個軸：**效能、架構/設計品質、UX/產品完整度、文件與 API 契約**。
掃描以 8 個 lens finder 並行執行、每一個發現由對抗式 verifier 對照**真實程式碼**獨立複核
（預設 refute），並逐一去重比對 34 項 backlog。結果：**41 raw → 40 confirmed（1 refuted、0 落在 backlog）**。

> **核心觀察（Product Pressure Test 結論，經 2026-07-13 doc-review 校準）**：
> 有一組**「兩份真相來源／靜默漂移」**的架構缺口，共同特徵是**「錯得很安靜、且零測試覆蓋」**——
> CI 沒在跑它宣稱在跑的邊界規則（[1]）、優化訊號回傳 "unavailable"（[2]）、
> 未來 browser adapter 會靜默突破「絕不在 Flask 行程內開 Chrome」的憑證隔離（[4]）、
> 未來匿名 adapter 會被路由靜默丟棄（[16]）。它們對應 `2026-07-01-phase3-signal-integrity-hardening`
> 命名的根因家族「訊號在接縫被靜默丟掉」。
>
> **但 doc-review（product-lens + adversarial，經程式碼實測）修正了「A 是最高槓桿」的斷言**：
> 工作包 A 五項**目前全是潛在/fail-safe**，沒有一項是「現在正在發生的錯誤」——[1] 的 domain→cli
> 契約啟用後其實**乾淨通過**（[1] 的價值是*防未來回歸*，不是修現有 bug）；[4]/[16] 只在*未來*新增
> adapter 且有人漏改硬編集合時才咬人；[3] 是 fail-safe import cycle；[2] 是 fail-safe 靜默失能
> （見下方 [2] 校正）。**反而 [5]（全失敗 publish 存成 `status='success'`）與 [10]（連點開多個
> Chromium）是*今天正在傷害操作者*的活躍問題**，原稿卻把它們排在 B(#3)/D(#5)。若「槓桿」以
> *可達傷害的機率×影響面* 衡量而非「架構漂移的複利」，排序會翻轉——見下方修訂後的 Prioritization。

本文件**不重寫**任何既有 active 計畫，而是把去重後的互補發現整理成 6 個可獨立執行的工作包，
並給出排序建議；每個工作包可直接交給 `/ce-plan` 產生詳細計畫或以 worktree 隔離直接執行。

## Inventory — 40 掃描確認 + 1 doc-review 新增（共 41；依工作包分組）

嚴重度為**影響層級**（非 bug 分級）：P1 高、P2 中、P3 低。effort：S<0.5d / M / L>2d。
路徑為 repo-relative（相對 `backlink-publisher/`）。完整 evidence/verifier_note 見掃描原始輸出。

### 工作包 A — 靜默漂移與邊界強制（Silent-drift & boundary enforcement）
「兩份真相來源」造成的（多為潛在/fail-safe 的）靜默失效，零測試覆蓋。**價值主要是防未來回歸**。
⚠️ **[1] 與 [3] 必須同一 PR 落地**：[1] 一旦讓 CI 讀 pyproject 契約，`_util 不得 import domain` 契約會立刻
因 [3] 的 `_util.paths→config` 邊而**紅燈**（feasibility+adversarial 實測：這是唯一的阻斷違規）；
且啟用時 domain→cli 契約其實**乾淨通過**，故 [1] 的實質收益是防回歸而非修現有 bug。
機制二擇一（規劃階段定）：刪 `.importlinter`，或 `ci.yml:157` 的 `lint-imports` 加 `--config pyproject.toml`。

| id | Sev | Eff | 位置 | 發現 | 為何重要（濃縮） |
|----|-----|-----|------|------|------------------|
| 1 | **P1** | S | `pyproject.toml:299` | `[tool.importlinter]` 是死設定；CI 讀較弱的 `.importlinter` | import-linter reader 順序 ini→toml，`.importlinter` 先命中，pyproject 的 27-module domain→cli 契約與**整個 `_util 不得 import domain`** 契約從未執行。12 個 domain 套件可任意 import cli、CLAUDE/AGENTS 宣稱在跑的規則全是空話 |
| 2 | P2 | M | `optimization/collector.py:88` | 優化訊號 collector shell-out CLI 取 survival/canary/equity；除了傳**不存在的旗標**（`--json-summary`…），還**呼叫錯的模組路徑**（`cli.recheck_backlinks` 而非真正的 `cli.ops.recheck_backlinks`），subprocess 在 import 就死 | **校正（adversarial 實測）**：影響是「優化功能被呼叫時**靜默失能**」而非「loop 長期用壞訊號做出錯誤決策」——`evaluate_rules` 只由**手動** `optimize-weights` CLI + opt-in `--optimize` 觸發，且失能是 **fail-safe**（unavailable→無 survival 資料→rules `if total < min_confirmations: continue` 跳過→權重不變）。「永遠 unavailable」僅限 recheck/equity；**canary 有可用的 file-read 直讀路徑**。仍是 phase3「訊號在接縫被丟掉」家族，但無現行錯誤路由 |
| 3 | P2 | M | `_util/paths.py:65` | `_util` 反向 import `config`/`persistence`，形成 `config↔_util.paths` import cycle | 最底層 `_util` 依賴 domain，只為一個 test monkeypatch 的間接層；因 [1] 而無人守 |
| 4 | P2 | M | `publishing/reliability/policy.py:59` | `_BROWSER_TIER` 硬編 browser 平台名單，與 adapter 已宣告的 `mechanism='browser'` 重複 | 新增 browser adapter 若漏改此集合 → `_is_browser_tier` 回 False → 在**長生命週期 Flask 行程內開 Chrome**，破壞憑證隔離，靜默無錯 |
| 16 | P3 | S | `_dispatch_router/signals.py:65` | `_ALWAYS_BOUND` 硬編匿名 auth 平台名單，registry 已用 `auth_type()` 分類 | 新增匿名 adapter 漏改 → binding 判為 unbound → 路由**靜默不派發**，無錯（fix 乾淨：`platforms_by_auth_type('anon')` 剛好等於現有 4 個） |

### 工作包 A2 — 架構重複與死碼（Duplication & dead code）
（**doc-review 校正補回**：初稿遺漏這 5 項架構重複/死碼發現，導致清單只列 35 項卻宣稱 40。全 P3、低風險、與 A 的邊界工作可同分支收。）

| id | Sev | Eff | 位置 | 發現 | 為何重要 |
|----|-----|-----|------|------|----------|
| 11 | P3 | S | `config/types.py:582` | token-path 有兩套並行 API：table-driven `token_path()` 已取代 15 個 per-platform `*_token_path` property，其中 **9 個零呼叫** | 重複存取面須與 `_TOKEN_FILE_NAMES` 手動同步、易漂移；刪 9 個死 property |
| 12 | P3 | S | `events/_project_reducers.py:454` | quarantine-reconcile + `ProjectionResult` build 尾段在 3 個 projector reducer **逐字複製** | `missing_field` 計數校正（正確性不變式）三處重複，改一處易漏 |
| 13 | P3 | S | `config/parsers/anchor.py:106` | 尾斜線/scheme 域名變體查找迴圈在 3 個 config getter 各自重寫 | 域名匹配語義載重卻散落三份；改 normalization 須同步 |
| 14 | P3 | M | `optimization/rules.py:276` | Rule 3 & 4 是同閾值（survival<0.3/dofollow<0.2）的重疊懲罰規則且都 enabled；docstring 仍稱「Two v1 rules」 | **verifier 校正**：last-write-wins 使 Rule 4 覆蓋 Rule 3（非複合雙罰），實害是冗餘 + 矛盾的 adjustment-history + 漂移風險 |
| 15 | P3 | S | `events/history_query.py:471` | `list_events`/`list_publish_events` 近乎相同，且三個低階 event query 函式**全零呼叫**（死碼、不在 `__all__`） | 兩份 events-row projection 須隨 schema 變；可刪 |

### 工作包 B — 契約與結果誠實性（Contract & result honesty）
前後端 `/api/v1` 契約錯配，與已修的 keep-alive bug 同類；含「假綠」誠實性問題。

| id | Sev | Eff | 位置 | 發現 | 為何重要 |
|----|-----|-----|------|------|----------|
| 5 | P2 | M | `frontend/src/api/pipeline.ts:50` | publish 結果 envelope 分裂：`/pipeline/publish` 給 `n_total`、`/operations` 給 `n_failed`；`PublishResult.state` 少了後端會發的 `all_failed` | 同一邏輯兩種型別；**`all_failed` 在 workbench 渲染成無樣式「0/N 成功」**；worker 更把 `all_failed` 存成 `status='success'`（假綠，正是 phase3 要防的） |
| 22 | P3 | S | `frontend/src/api/operations.ts:11` | operations API 宣傳 `plan`/`validate` kind，worker 無條件失敗 | 前端可送出必然失敗的操作 |
| 23 | P3 | S | `frontend/src/api/settings.ts:176` | velog login：前端宣告 `log_path`，後端只送 `has_log` | **⚠️ 修正方向（security-lens）**：`api/v1/velog.py:49` 是**刻意**不回傳檔案路徑（有註解 + 迴歸測試）。修法必須是**刪前端死欄位 `log_path`**，**絕不可**把 `log_path` 加回 API 回應——那會倒退一個蓄意的路徑資訊揭露防護 |
| 24 | P3 | S | `frontend/src/api/health.ts:92` | `HealthSummary.projection/health` 型別非 null，但 fail-open fallback 會回 null | 型別謊報，前端未防 null |
| 41 | P2 | S | `webui_app/routes/settings_basic.py:268` | **（doc-review 新增）** 舊 legacy route `/api/velog/login` 仍**外洩原始絕對 log 路徑**（暴露本機使用者名/目錄結構），與已做 redaction 的 `/api/v1` 端點不對等 | security-lens 實測的**活躍資訊揭露**；redact 以與 SPA 端點對齊 |

### 工作包 C — 熱路徑效能（Hot-path performance）
多數 S-effort、有既有 `.benchmarks/` 守護；集中在 recheck 掃描與 `/health/summary`。

| id | Sev | Eff | 位置 | 發現 | 為何重要 |
|----|-----|-----|------|------|----------|
| 6 | P2 | M | `recheck/probe.py:144` | `probe_liveness` 對每個 live 頁面**下載兩次**（anchor inspect + indexability），皆未快取 | recheck 掃全 backlink 語料：2N 次 fetch，是每輪 recheck 的主要 wall-clock/頻寬成本，且**加倍反爬請求足跡** |
| 7 | P2 | M | `webui_app/health_metrics.py:744` | 3 個 health panel 用 per-keyword correlated subquery over `json_extract`（不可索引） | 每次 `/health/summary` ~O(keywords×snapshots) 的 json_extract，三 panel 重複同一掃描 |
| 25 | P3 | M | `recheck/selection.py:221` | keepalive cycle 用兩個獨立 selector **各全掃一次** events.db+articles | 每輪雙倍全表掃描 |
| 26 | P3 | S | `cli/plan_backlinks/_engine.py:238` | 每個 seed 驗證兩次、兩次都建 `SeedPayload` pydantic model | plan 熱路徑重工 |
| 27 | P3 | S | `cli/publish_backlinks/_engine.py:342` | `supported_platforms()` 每個 publish row 重建一次 sorted frozenset | per-row 重算 |
| 28 | P3 | S | `keepalive/chain.py:213` | reverify loop 每個結果都 load+fsync 重寫 `optimization_state.json` | per-result 全檔 fsync |
| 29 | P3 | S | `webui_app/health_metrics.py:541` | `publish_to_index_latency` N+1：每個 target_url 開新 SQLite 連線（conf 0.6，最不確定） | 連線抖動 |
| 30 | P3 | S | `webui_app/api/v1/health_dashboard.py:293` | `_storage_health` 每次 summary 走整個 config dir + 全表 `COUNT(*)` | 每次 summary I/O |
| 31 | P3 | S | `webui_app/api/v1/health_dashboard.py:183` | `_reconciliation_gaps` 讀+JSON-parse 最多 100 個 checkpoint 檔只為取一個 count | 純為計數而全解析 |
| 32 | P3 | S | `frontend/src/pages/Health/HealthPage.vue:35` | HealthPage 用預設 refetch-on-focus + 30s staleTime，卻是**全 app 最貴的端點** | 過度重取最貴 aggregate |

### 工作包 D — SPA 對等與誠實狀態（SPA parity & honest states）
功能性缺口（非視覺 polish；視覺/token 由 wave2/uiux-comprehensive 認領）。
⚠️ **範圍衝突（scope-guardian 實測）**：active 計畫 `2026-07-06-005-opt-webui-uiux-comprehensive` **已認領**
D6（per-row in-flight busy mutex = 本清單 [10]）與 W8/D10（SideNav badge 由 attention 聚合器供資 = [35]）。
故 **[9][10][35][37][38] 執行前必須先與該計畫 content-diff 去重**，屬其 backlog 的併入該計畫、勿在此重定；
D 的淨新範圍與驗收標準須待去重後才能定案（可能顯著收縮）。

| id | Sev | Eff | 位置 | 發現 | 為何重要 |
|----|-----|-----|------|------|----------|
| 8 | P2 | M | `webui_app/templates/_copilot_panel.html:1` | Pro-Mode Copilot 顧問面板只存在於 legacy Jinja，**預設 SPA 完全沒有** | 主 UI 操作者看不到 AI 顧問；3 個後端端點對 SPA 是死重量。**非 drop-in（design-lens）**：port 前須決 FAB 在 AppShell 的落點（全域 vs 頁面級）、與 [35] sidenav badge 的共存、5 個狀態 + Q&A-lock 焦點/inert 行為哪些須 1:1 保留；真實 effort 可能 >M |
| 9 | P2 | S | `frontend/src/pages/EquityLedger/EquityLedgerPage.vue:64` | 搜尋/篩選無 zero-result 狀態；批量重新檢查 `catch { // Silent }` 吞錯 | 篩到 0 筆顯示空白無提示；批次失敗看似靜默成功 |
| 10 | P2 | S→M | `frontend/src/pages/Settings/MediumCard.vue:35` + `webui_app/services/browser_login.py` | Medium/Velog 登入卡在 in-flight POST 期間按鈕仍可點 | 連點 → **重複開多個 headed-Chromium 視窗**，可能損毀登入 profile。**前端守衛不夠（security-lens）**：`spawn_browser_login()` 的 `subprocess.Popen` **無伺服端鎖**（不像 `bind_job.py` 的 `BindJobRegistry` threading.Lock）；兩個分頁/直接打 API 仍能並發。修法：前端停整個 action group（clicked 顯示 busy）**＋** 伺服端 per-platform 鎖 |
| 33 | P3 | S | `frontend/src/pages/Health/HealthPage.vue:179` | 「Dismiss autopilot alert」動作在 SPA 無法觸及 | 主 UI 清不掉告警 |
| 34 | P3 | M | `frontend/src/pages/BatchCampaign/BatchCampaignPage.vue:81` | batch-campaign 進度頁純 transient，無 campaign list 可回到執行中的 campaign | 重新整理即失去進行中活動入口 |
| 35 | P3 | S | `frontend/src/stores/operations.ts:3` | 「任務進行中」sidenav badge 是死接線（`activeCount` 無 consumer 且非響應式） | 承諾的 badge 永不顯示 |
| 36 | P3 | S | `frontend/src/router/index.ts:8` | Onboarding CTA 深連 Settings 子區塊的 `#anchor` 被忽略（不捲動） | 引導點擊到不了目標 |
| 37 | P3 | S | `frontend/src/pages/Operations/OperationsPage.vue:27` | 四態矩陣在 empty 檢查前先回 'ready'，empty 狀態是死碼 | 空清單渲染只有表頭 |
| 38 | P3 | S | `frontend/src/pages/OptimizationStatus/OptimizationStatusPage.vue:17` | 從不發出 'empty' 狀態，empty-text 死碼 | 零平台安裝顯示只有表頭 |
| 39 | P3 | S | `webui_app/templates/_tab_new.html:192` | legacy Jinja 仍用 inline `on*`（及一處 inline innerHTML），違反已明訂的 anti-rot 規則 | 護欄自身被違反 |
| 40 | P3 | S | `frontend/src/components/OnboardingWizard.vue:62` | modal 關閉後未還原 focus 到觸發元素（a11y 退化 vs ConfirmDialog） | 鍵盤/螢幕閱讀器 a11y |

### 工作包 E — 文件真相同步（Docs truth-sync）★全 S、零風險、可並行
掃描發現文件漂移**已造成實際浪費**（改到 shim 卻無行為變化）。一次 sweep 修完。

| id | Sev | Eff | 位置 | 發現 |
|----|-----|-----|------|------|
| 17 | P3 | S | `AGENTS.md:128` | CLI entrypoints 表 Source 欄過期：14 列指向 backward-compat shim 而非 console script 實際 import 的子套件模組 |
| 18 | P3 | S | `docs/spa-migration-roadmap.md:34` | 「Remaining Jinja-only pages」列了 7 個**已 302 redirect 到 SPA** 的頁；檔案計數 ~2x 過期 |
| 19 | P3 | S | `AGENTS.md:87` | §Frontend「Remaining Jinja-only」8 項中 6 項已 redirect；且列 8 卻宣稱 10（自我矛盾） |
| 20 | P3 | S | `CLAUDE.md:75` | CLAUDE/AGENTS 的 SPA 路由清單漏了已上線的 `/operations`、`/error-reports` |
| 21 | P3 | S | `CLAUDE.md:44` | 宣稱 `__init__.py` 是「13 lines, no bridge」，實際 **102 行**含 public SDK facade + win32 shim |

## Prioritization & Sequencing（排序建議，doc-review 修訂）

**排序取決於「槓桿」的定義**（product-lens + adversarial 提出的核心校正）：
- **可達傷害優先（reachable-harm-first）**：先修*今天正在傷害操作者*的活躍問題——
  [5]（全失敗 publish 存成 success / 渲染成「0/N 成功」）、[10]（連點開多個 Chromium 損毀 profile）、
  [41]（legacy velog route 洩露絕對路徑）——這些不需等未來 adapter 就在發生。
- **防回歸優先（regression-prevention-first）**：先立 A 的邊界護欄，防未來 adapter/重構把潛在漏洞變成活躍漏洞。
  但 A 五項**目前全 fail-safe/潛在**，收益是「防未來」而非「修現在」。

| 順位（reachable-harm-first） | 內容 | 理由 | 風險 |
|------|------|------|------|
| 1 | **E 文件同步（[17-21]）** | 全 S、零程式風險、可與任何 session 並行；漂移已造成實際浪費 | 極低 |
| 2 | **活躍誠實/安全修正**：[5] 假綠 + store-write、[10] 登入守衛（前端+伺服端鎖）、[41] velog 路徑洩露 | *正在傷害操作者*，非潛在；[5] 是 phase3 明訂的「假綠」 | 中（[5] 改 API+store；[10]/[41] 須先與 D 的 uiux 計畫去重） |
| 3 | **A 邊界護欄（[1]+[3] 同 PR、[4]、[16]、[2]）** | 防未來回歸；[1] 讓 CI 誠實。**但先確認想投「防未來」而非「修現在」** | 低-中（[3] 動 import、[4] 見下方陷阱、須測試護航） |
| 4 | **A2 重複/死碼（[11-15]）+ C 熱路徑效能** | 全低風險、有 benchmark 守護；[6] 真頻寬+反爬足跡 | 低（C 的 M 項先 cProfile 證實） |
| 5 | **B 其餘契約（[22][23][24]）** | 型別對齊；[23] 注意修正方向勿倒退 redaction | 低 |
| 6 | **D 其餘（去重後淨新項）** | 完整度/a11y；**須先與 `2026-07-06-005` uiux 計畫去重** | 中（跨計畫協調） |

**另一個一直存在的競爭選項（product-lens 提醒，勿只當去重註腳）**：與其開新優化流，
可先**落地已建好的在途工作**——但 doc-review 校正了前提：batch2 的 **SSRF/XSS/token 安全叢集其實已在 main**
（見 Problem Frame），故「落地 batch2」實際只剩 **P1 keep-alive 死流程** + 非安全漂移，加上 bug 審計的
**34 個未修項**（另 session 認領）。這仍是合理的「收斂而非發現」路線，值得與上表首波並列考量。

**修訂後建議首波**：**E（文件，零風險並行）+ 第 2 順位的活躍誠實/安全修正**，優於原稿的「A+E」——
因為 A 全是潛在風險而 [5]/[10]/[41] 是活躍傷害。若你的意圖明確是「先立護欄防未來」，則 A 仍可首發。
**首波前置**：確認 batch2 落地狀態（content-diff）、與 uiux 計畫就 [9][10][35][37][38] 去重。

## Success Criteria（驗收標準，供 /ce-plan 展開）

- **A**：
  - **[1]+[3] 同一 PR**：CI 實際執行 pyproject 的兩份 import 契約（新增 smoke test 斷言 contract 數）；`_util` 不再 import 任何 domain（cycle 消失，`_util.paths→config` 邊移除且**保留 `config._config_dir` monkeypatch target**）。機制擇一（刪 `.importlinter` 或 `ci.yml:157` 加 `--config pyproject.toml`）。
  - **[4] ⚠️ 勿從 `mechanism='browser'` 衍生**（feasibility+security 實測：只有 medium 宣告 browser，velog 走 `velog_graphql`=api、devto/mastodon 未宣告；naive 衍生會縮成 `{medium}`、**重開 in-process-Chrome 憑證漏洞**）。改為新增專屬 registry 屬性（如 `browser_login: bool`）並**依 fallback 鏈判定**（平台的鏈中*任一* adapter 為 browser 即算 browser-tier）；drift test 須含 medium 的多機制鏈案例，且**不得改動 `CROSS_MECHANISM_FALLBACK`**。
  - **[16]** 乾淨衍生：`auth_type(name)=='anon'` / `platforms_by_auth_type('anon')` + drift test。
  - **[2]**：實作 `events.db` 直讀（整合測試、**非 mock subprocess** 下真的回資料），或退而刪除誤導性註解並修正模組路徑（`cli.ops.recheck_backlinks`）+ 旗標；至少讓失能不再被 mock 掩蓋。
- **A2**：[11] 刪 9 個死 property（其餘 6 個遷至 `token_path()`）；[12]/[13] 抽共用 accumulator/helper；[14] 收斂重疊規則並更新 docstring；[15] 刪三個零呼叫函式。各以行為不變的單元測試護航。
- **B**：`/pipeline/publish` 與 `/operations` 發**同一** publish envelope（同時含 `n_ok`/`n_failed`）；`PublishResult.state` 補上 `all_failed` 且 `StatusBadge` 映到 **danger/error 色系（絕不 success/neutral）** + 明確標籤（如「全部失敗」）；**[5] 修 store-write**：`operation_worker` 不再把 `all_failed` 存成 `status='success'`；[23] **刪前端死欄位**（勿加回 API）；[41] redact legacy route 的 `log_path`；[22]/[24] 型別對齊（`plan`/`validate`、nullable health）。
- **C**：先以 cProfile/現有 benchmark 量測基線，改後基準不退化且對 [6]/[7] 有可量測降幅；S 項各自單元驗證行為不變。
- **D**（**須先與 `2026-07-06-005` uiux 計畫去重**，屬其 backlog 的移交）：淨新項須逐一列明並各有**斷言渲染**的測試——[8] copilot（含 FAB 落點/badge 共存/狀態保留的 IA 決策）、[9] filtered-empty + 錯誤 toast、[10] 前端 group 停用 **+ 伺服端 per-platform 鎖**、[33] dismiss-alert 可達、[34] campaign 清單/索引、[35] badge 接上 consumer、[36] anchor 捲動、[37]/[38] empty 狀態（用 `StateBlock` 的 `empty-action` slot 給 CTA）、[39] 移除 inline `on*`、**[40] modal 關閉還原 focus（唯一 a11y 項，勿遺漏）**。
- **E**：文件計數/路徑/清單與 `git`+`pyproject`+router 即時量測一致；可選加一個「文件計數 vs 實測」的機械化檢查防再漂移。**注意**：[1] 的落地本身要修正 CLAUDE/AGENTS「邊界已強制」的說法，與 E 的 [19][20][21] 同改 `AGENTS.md`/`CLAUDE.md`——若 A、E 並行 worktree 須協調這兩檔的編輯（或把該 doc 修正併入 E）以免衝突。

## Cross-plan De-confliction（避免重複認領）

| 既有 active 計畫 | 與本清單的交疊 | 處置 |
|---|---|---|
| `2026-07-09-001-opt-comprehensive-repo-state-and-optimization` | D1 複雜度熱點；本清單**不含**複雜度（已 dedupe） | 互補，不重疊 |
| `2026-07-02-001-opt-v060-uiux-pipeline-upgrade` | 並行發佈引擎（已排除）；工作包 C 的 publish 熱路徑須避開 `_engine.py` 並行化 | C 只碰非並行化的 per-row 重工 |
| `2026-07-06-005-opt-webui-uiux-comprehensive` / `2026-07-09-002-webui-uiux-wave2` | **已認領** D6（in-flight busy mutex=[10]）、W8/D10（sidenav badge=[35]）；工作包 D 的 SPA 頁面 | **D 的 [9][10][35][37][38] 執行前必須 content-diff 去重**，屬其 backlog 者移交、勿在此重定 |
| `2026-07-13-002-fix-windows-test-suite-failures`（另一 session，`feat/operation-progress`） | 無直接檔案交疊，但同 workspace | 開工前查 `git worktree list` |
| `fix/audit-batch2`（另一 session） | **校正**：security-lens 實測其 SSRF/XSS/token 安全叢集**內容已在 main**（不同 hash）；分支上剩 P1 keep-alive + 非安全漂移（`safe_write`/`circuit`/前端） | **A 與 B 開工前**都以 `git diff main fix/audit-batch2 -- <files>`（**content-diff，非 branch-ancestry**）確認實際差異，只 reconcile 真正未落地者 |

## Execution Safeguards（沿用制度性教訓）

- 本 workspace 有**共用目錄併發 session** 已知風險（見 memory `shared-directory-hazard`）；開工前必跑
  `git -C backlink-publisher status --short` + `git worktree list`，確認乾淨且無他 session 活躍。
- **一律 worktree 隔離，絕不在 `main` 直接做修改性工作**；每個工作包一個分支。
- 所有行號/計數為 2026-07-13 快照，執行前重新量測。
- 任何 SLOC/CC 改動即核對 `monolith_budget.toml` / `complexity_budget.toml`。
- TDD：先寫會失敗的測試（尤其 A 的 drift test、B 的契約測試、C 的 benchmark、D 的狀態渲染斷言）。
- **[4] 的「絕不在 Flask 內開 Chrome」不變式僅限 publish-dispatch 路徑**（security-lens 校正）：
  現況 `medium_login_api.py → launch_login_window → sync_playwright()` 已在 Flask 行程內同步開 Chrome
  供**登入**流程用——這是既有、獨立、未被本清單任一工作包涵蓋的暴露；[4] 修的是 publish 路徑，別誤以為修完就恢復全域保證。

## Open Decision（待使用者定奪，doc-review 後）

**1. 首波的「槓桿」以什麼衡量？**（決定排序）
- (i) **可達傷害優先**：先修 [5]/[10]/[41] 等*正在傷害操作者*的活躍問題 + E 文件（修訂後建議）。
- (ii) **防回歸優先**：先立工作包 A 的邊界護欄（明知目前全 fail-safe，投資防未來）。

**2. 要不要改走「收斂而非發現」？** 先落地 batch2 剩餘的 P1 keep-alive + 另 session 的 34 個未修 bug，
而非開新優化流（安全叢集已在 main，此路線比原稿以為的小）。

**3. 承接方式**：(a) 直接以 worktree 執行選定首波、(b) 先交 `/ce-plan` 產詳細計畫、(c) 自訂排序/範圍。

> **首波前置（無論選哪個，動 A/B/D 前必做）**：① `git diff main fix/audit-batch2 -- <files>` 確認真實差異；
> ② 與 `2026-07-06-005` uiux 計畫就 [9][10][35][37][38] content-diff 去重；③ 查 `git worktree list` 無他 session 活躍。
