---
title: "opt: 全專案隱藏債務強化掃描計畫"
type: optimization
status: active
date: 2026-07-06
priority: medium
deepened: 2026-07-06
claims:
  paths:
    - src/backlink_publisher/
    - webui_app/
    - webui_store/
    - tests/
    - docs/audits/
    - monolith_budget.toml
    - complexity_budget.toml
    - pyproject.toml
    - debt_registry.toml
  shas: []
---

# opt: 全專案隱藏債務強化掃描計畫

## Overview（概覽）

本計畫源自使用者要求「分析項目找到優化項目計畫」（分析專案、找出優化項目）。專案已有成熟的優化脈絡（`docs/optimization-history.md` P1–P11 + Phase 2 mypy/spray + Phase 3 post-v0.5.0 + v0.6.0 UI/UX & Pipeline），使用者明確選擇**不**延續既有計畫的既定範圍，而是要一次**全新、全專案**的優化審查，找出目前四份 active 計畫（Phase 3、v0.6.0、Windows encoding fix、GitHub/GitLab reconcile）都沒有涵蓋到的機會。

兩個平行研究 agent 完成了這次審查：一個掃描 repo 現況（complexity/SLOC 預算、dead code、exception hygiene、測試健康度、架構慣例），一個爬梳 `docs/solutions/`（68 篇制度性學習文件）找出重複發生的失敗模式與尚未解決的伏筆。兩者交叉比對後，本計畫收斂成 **12 個實作單元、5 個 Sprint**，全部是既有計畫範圍之外的新發現，且刻意排除任何已被 2026-06-01 架構健檢報告否決過的方向（例如模組再拆分——該報告已明確結論「瓶頸在執行/收斂，不在模組化程度」）。

**這主要不是一次修 bug 的計畫，是一次誠實度與完整性的強化掃描**：多數項目是「既有機制（budget ratchet、debt registry、vulture gate、store 初始化）在某個角落沒有被正確套用」，而不是新增功能。**〔doc-review 複核修正，scope-guardian + product-lens 兩份獨立複核共同指出原文字「這不是一次修 bug 的計畫」與內容矛盾〕例外：D2 的 `medium_browser.py:330`（已被 `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 點名為「critical silent swallow」）與 D3 的 `chrome_backend.py:60`（`error_code` 契約違規）是兩個具名、已確認需要修復的真實 bug，各自有紅→綠測試把關——這兩者是本計畫範圍內刻意納入的例外，因為它們是分類掃描過程中直接發現的、有明確修復方式的既存缺陷，不代表本計畫整體性質改變為 bug 修復計畫。**

## Problem Frame（問題框架）

### 技術棧摘要

Python ≥3.11、Flask 3.1 + APIFlask、Vue 3.5 SPA（Vite）、SQLite-backed `webui_store/`（10 個 `_LazyStore` 單例）、Playwright 驅動的發佈/綁定流程、~26 個 platform adapter、627 個測試檔案、雙 CI（GitHub Actions 8 個 workflow + `.gitlab-ci.yml`）、兩份複雜度預算 TOML（`monolith_budget.toml`／`complexity_budget.toml`）、`debt_registry.toml` 治理既有債務。詳見 `docs/optimization-history.md` 與現有計畫文件，本計畫不重複記錄。

### 本次審查發現的現況缺口（摘要，逐項證據見對應 Unit）

1. **`webui_store/__init__.py::_refresh_paths()`** 漏掉 `verify_health_store` 與 `error_report_store` 兩個較新的 `_LazyStore` 單例——這是**兩次獨立**的同型遺漏（commit `84fe6046` 與後續新增 `error_reports.py` 的 commit 各自犯了一次），且守護測試 `tests/test_webui_store_pkg/test_store_init.py` 只枚舉原始 4 個 store，抓不到第 3 次重演。
2. **Vulture dead-code advisory gate 在 Windows 上已被證實完全失效**：`tests/test_dead_code_advisory.py::_key()` 用 OS 原生路徑分隔符比對純正斜線的 allowlist key，`pytest tests/test_dead_code_advisory.py -W error::UserWarning` 在本機直接失敗。
3. **兩份複雜度預算 TOML 的完整性有缺口**：11 個 300–370 SLOC 檔案未被 `monolith_budget.toml` 追蹤（儘管 2026-06-15 的稽核聲稱已涵蓋全部 500+ 行檔案）；3 個函式（`spray_backlinks/core.py::main` CC 29、`medium_brave.py::publish` CC 27、`_seal_init.py::_handle_init` CC 27）未被 `complexity_budget.toml` 追蹤，其中第一個只差 1 點就會撞上 CI 的 CC-30 硬性 backstop。`publishing/registry.py`（95.9% 天花板已滿）與 `webui_app/api/v1/spec.py`（97.6% 已滿）直接在 v0.6.0 計畫即將新增內容的路徑上。
4. **~200 個 `# noqa: BLE001` 是死註解**——`pyproject.toml` 的 `ruff.lint.select` 從未啟用 `flake8-blind-except` 規則家族，這些註解暗示「已經過 lint 審查」，但實際上從未被任何工具檢查過。
5. **`except Exception:` 例外處理誠實度掃描尚未涵蓋的三大區塊**：`publishing/adapters/`（56 處、28 個檔案，Phase 3 D2 明確排除——研究時的「78 處」快照已用即時 `grep` 重新驗證並更正為 56，deepening 複核期間發現）、`cli/_bind/`（25 處、4 個檔案，Playwright 憑證綁定流程，零覆蓋）、`events/`（22 處、5 個檔案，僅 1 處有 debt 追蹤）。`docs/solutions/` 裡有三篇獨立文件描述同一種「在派發/分類接縫處靜默丟失訊號」的 bug 形狀（`dofollow-canary-verdict-dropped-at-publish-output-seam`、`projector-silent-drop-status-vocabulary-drift`、`live-dofollow-undercounting-triple-gap`），三者都明確警告「這個模式還沒被全專案掃過」——上述三個未覆蓋區塊正是最可能藏著第四個實例的地方。**deepening 複核已直接確認 `publishing/adapters/medium_browser.py:330` 就是這個形狀的實例**：Save Draft 點擊失敗時仍落到 `final_url = page.url` 並回傳 `AdapterResult(status="drafted", ...)`，沒有任何其他機制驗證草稿真的被儲存；`docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 已點名此站點為「critical silent swallow」，且目前只加了 log 但假成功回傳值本身尚未修復。
6. **`_TransientHTTPError` 被 4 個 adapter 檔案各自重新定義**（`blogger_api.py`、`medium_api.py`、`velog_graphql.py`、`llm_anchor_provider.py`），儘管 `adapters/base.py` 已有共用的 `TransientError` 可用。
7. **main 上 ~366 個既存失敗測試的根因尚未被本計畫獨立驗證過**——v0.6.0 計畫的 U1 已在未合併分支 `fix/u1-test-suite-triage` 上執行過 triage（367 → 90 殘餘），但該分支尚未在真實 CI 上確認、也尚未合併；`docs/solutions/test-failures/` 有 5 篇文件描述同型態的測試污染/假綠/極性反轉根因家族，值得在本計畫獨立、唯讀地重新量測與分類，而不是假設 U1 的分支結果已經是定論。
8. **效能熱點零 benchmark 覆蓋**：`webui_store/history.py` 每次單筆操作都整檔 `load()`+`save()`（唯一還沒遷到 SQLite 的 store）；`campaign_store.py`／`batch_ops.py` 有 Python 迴圈式聚合；`publishing/adapters/link_attr_verifier.py` 每次驗證都跑巢狀迴圈＋多次全文 regex。`tests/test_benchmarks.py` 目前只覆蓋 4 個 CLI 路徑，以上全部掛零。
9. **`docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md`** 記錄了 3 個帶明確恢復觸發條件的延後決策（R7 跨行程 rehydrate、R8 Pydantic 非權威驗證、R10 無 per-probe timeout）——鑑於 scheduler/keepalive/recheck 相關活動持續增加，值得驗證觸發條件是否已經悄悄成立。
10. **`STEWARDSHIP.md` 的 11 個治理領域自 2026-06-04 起全部 `[unassigned]`**，且恰好包含本次發現問題最多的兩個領域（WebUI store SQLite、Platform adapter registry）——這是本次多起「同型缺口重演」背後的組織性成因，非程式碼修復項。
11. **〔doc-review 補充，coherence 複核發現本項原先漏列〕`tests/integration/test_pipeline_e2e.py` 宣告 `__tier__ = "unit"`，與其所在目錄（`tests/integration/`）及檔名（`*_e2e.py`）矛盾且無註解說明——這是研究階段（第 5 節測試健康度）就已發現、對應 A2 的具體 finding，先前的摘要清單漏收，此處補上以保持 Problem Frame 與 Implementation Units 的可追溯性。

## Requirements Trace（需求對照）

| 需求 | 內容 | 對應 Unit |
|---|---|---|
| R1 | `webui_store` 單例完整性修復 + 守護測試強化（防第三次重演） | A1 |
| R2 | 測試 tier 標記錯誤修正 | A2 |
| R3 | Vulture allowlist 跨平台路徑修復 + 過期行號更新 | A3 |
| R4 | 複雜度／SLOC 預算完整性補齊（未追蹤檔案與函式） | B1 |
| R5 | 高滿載天花板預先調高（`registry.py`／`spec.py`），並與 v0.6.0 計畫協調 | B2 |
| R6 | Lint 債務誠實化：清除死 `noqa`、記錄 BLE 規則決策 | C1 |
| R7 | `_TransientHTTPError` 重複定義收斂為共用 `TransientError` | D1 |
| R8 | `publishing/adapters/` except-Exception 分類掃描（含接縫靜默丟失風險審視） | D2 |
| R9 | `cli/_bind/` + `events/` except-Exception 分類掃描 | D3 |
| R10 | main 既存失敗測試獨立唯讀量測與根因分群 | E1 |
| R11 | 熱點路徑效能 benchmark 補齊 | E2 |
| R12 | LITE 延後決策（R7/R8/R10）觸發條件唯讀驗證 | E3 |

## Scope Boundaries（範圍邊界）

- **不重做任何 active 計畫的既定範圍**：不碰 v0.6.0 的 U1–U15（UI/UX 遷移、pipeline 平行化、canary 轉換、錯誤回報走查）、不碰 Phase 3 已完成的 Sprint A–E、不碰 Windows encoding-fix 計畫涵蓋的 subprocess/console 編碼問題、不碰 GitHub/GitLab reconcile 計畫的 git 歷史整併工作。
- **不重新論證模組拆分或 `webui_store` 更名**——2026-06-01 架構健檢報告已明確結論這是低 ROI 方向，不在本計畫重啟。
- **不消除 `except Exception:` 的使用**——本計畫延續 Phase 3 D2 已證實的方法論（分類 + `debt_registry.toml` 追蹤 + `# debt: <slug>` 註解），目標是誠實記錄與篩出真正的靜默風險，不是把每個 broad catch 都改成 typed exception。
- **不啟用 ruff 的 `flake8-blind-except`（BLE）規則家族**——C1 會清除死掉的 `# noqa: BLE001` 註解，但不會反過來啟用該規則；理由與後續資料需求見 Key Technical Decisions K3。
- **不修復 main 既存失敗測試本身**——E1 是唯讀量測與根因分群，實際修復動作屬於 v0.6.0 U1 的範圍（或其後續），本計畫刻意避免與該分支的在途工作重工。
- **不承諾解決 LITE 的 3 個延後決策**——E3 只驗證觸發條件是否成立，若成立則記錄並建議另開追蹤項，不在本計畫內直接實作跨行程 rehydrate / per-probe timeout / Pydantic 權威驗證。
- **不指派 `STEWARDSHIP.md` 的治理責任人**——這是組織決策，記錄在 Documentation / Operational Notes 供使用者決定，不是本計畫的實作單元。

### Deferred to Separate Tasks

- **LITE 延後決策的實際修復**（若 E3 發現觸發條件已成立）：另開獨立計畫，觸發點＝E3 的驗證結果。
- **main 既存失敗測試的實際修復**：屬於 v0.6.0 U1 範圍；本計畫的 E1 僅提供獨立量測資料供該 unit 或後續 CI 驗證參考。
- **`STEWARDSHIP.md` 責任人指派**：組織決策，交由使用者處理，見 Documentation / Operational Notes。

## Concurrent Plan Coordination（併發計畫協調）

本 workspace 已證實會有多個 session 同時修改（Phase 3 與 v0.6.0 計畫皆記錄過此現象），執行任何 unit 前務必用 `git status` + 即時查一次 `docs/plans/` 有無新的重疊 active 計畫，不要依賴本文件的快照。已知的重疊風險：

| 計畫 | 重疊檔案/範圍 | 因應方式 |
|---|---|---|
| `2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`（active） | `publishing/registry.py`（U10 平行化）、`webui_app/api/v1/spec.py`（U3/U5/U6/U7 新增 endpoint） | B2 提高這兩個檔案的 ceiling 前，先查 v0.6.0 對應 unit 的進度，避免同一天花板被兩份 PR 各自調整造成衝突；B2 的 rationale 需說明「一次調升涵蓋兩份計畫的預估總量」（比照 v0.6.0 自己 K22 的做法） |
| `2026-06-30-001-opt-phase3-post-v050-iteration-plan.md`（active，但全部 unit 已勾選） | `debt_registry.toml`、`# debt: <slug>` 註解慣例、`publishing/adapters/` 排除範圍 | D1–D3 沿用 Phase 3 D2/D2b 已確立的分類方法論與 registry schema，不自創第三套 |
| `2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`（active） | 無檔案重疊（該計畫聚焦 `_util/`、`sdk/_cli_runner.py`、`pipeline_orchestrator.py`、`bind_job.py` 的編碼修復） | 無需協調 |
| `2026-07-06-001-refactor-reconcile-github-gitlab-main-plan.md`（active，同日） | 潛在全面重疊——該計畫在整併 GitHub/GitLab 分歧的 `main` 歷史，**這條風險適用於本計畫的每一個 unit（A1-A3、B1-B2、C1、D1-D3、E1-E3 全部包含在內），與該 unit 是否觸碰重疊檔案無關**，因為風險來源是整個 `main` 分支歷史即將被改寫，不是特定檔案內容衝突 | **本計畫任何 unit 開工前，先確認 reconcile 計畫的狀態**；若其尚未完成，本計畫的分支應該從 reconcile 完成後的 `main` 切出，避免在即將被覆蓋的歷史上工作。〔doc-review 新增〕不要以「這個 unit 只改 2 個檔案、跟 git 歷史整併無關」為由跳過這個檢查——上面「無需協調」的判斷只適用於 Windows encoding-fix 計畫（該列是唯一經檔案級比對後確認無重疊的計畫），reconcile 這一列的風險是分支基準本身，任何 unit 都適用 |

## Context & Research（脈絡與研究）

### 要遵循的既有模式

- **`debt_registry.toml` 分類方法論**：`slug`/`severity`/`rationale`（≥80 字）/`discovered`/`owner`/`status`/`location`（`# debt: <slug>` 對應行號陣列），schema 定義於檔案開頭註解，由 `tests/test_debt_registry_format.py` 全套強制（唯一性、交叉引用、`resolved_date` 規則）——D1–D3 全程沿用，不新增欄位。
- **budget ratchet 規則**：超過 ceiling 需同 PR 附 ≥80 字 rationale 調高；`round_up_to_10(SLOC+30)` 的既有 ratchet 公式（見 v0.6.0 K22 的先例）。
- **紅色路徑自證護欄**：`tests/test_events_r8_gates.py` 的模式——新增/強化的守護測試需附「故意違規 → 紅燈」證明，A1 的 `_refresh_paths()` 守護測試強化要照此模式。
- **既有 benchmark 型態**：`tests/test_benchmarks.py` 用 `pytest-benchmark` 的既有 3 個案例（batch/single-row/JSONL 序列化）作為 E2 新增 benchmark 的樣板。
- **seam 三態分類模式**：`kind | NO_EMIT | QUARANTINE` 分類器 + 每條 emit 路徑的 presence/absence 測試（`docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift-2026-05-26.md`）——D2/D3 對「疑似接縫靜默丟失」的 except 區塊要用同樣的檢查框架，不是只貼一個 `# debt:` 註解了事。
- **量測優先於規劃**：`docs/solutions/best-practices/sweep-tasks-run-pytest-before-planning-2026-05-18.md`——E1 的第一步是空手量測，不沿用本文件或 v0.6.0 文件記錄的任何靜態數字（367/90 這兩個數字都可能已經過時）。
- **〔deepening 新增，security review〕憑證錯誤文字清洗機制已存在，D3 應沿用**：`events/scrubber.py::scrub_text()`（掃描 cookie/session token/JWT/bearer/basic-auth URL 樣式 + entropy fallback，已用於 `events/_project_reducers.py:316,424`）是 D3 處理 `cli/_bind/` 例外訊息時的既有工具，不是需要新建的機制；`_util/logger.py` 的 `_SENSITIVE_KEYS`/`_redact_in_place` 是另一層既有防護，但只保護走 `PipelineLogger` 的呼叫，不會自動涵蓋 `_driver_impl.py::_emit()` 這個獨立的 stdout writer。

### 制度性學習（Institutional Learnings）

- **「接縫靜默丟失」三案同型**（`dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25`、`projector-silent-drop-status-vocabulary-drift-2026-05-26`、`live-dofollow-undercounting-triple-gap-2026-06-05`）：三篇都明確說「還沒被全專案掃過」——D2/D3 是回應這個明確缺口的第一次全面掃描。
- **測試污染/假綠家族**（`tests-coupled-to-operator-config-state`、`del-os-environ-poisons-session-scoped-config-dir-fixture`、`app-level-csrf-guard-makes-blueprint-csrf-dead-code`、`negative-assertion-locks-in-bug`、`strict-markers-addopts-noop-conftest-module-load`）：E1 的分群方法直接套用這五篇文件各自記錄的 grep 稽核配方（`rg 'assert .+ not in'`、`del os.environ` 模式、`stderr == ""` 斷言等），而不是假設 366 個失敗是 366 個獨立問題。
- **2026-06-01 架構健檢報告**：已明確結論「不需要更多模組拆分」，其唯一標記的孤兒檔案（`lease_management.py`）已被清除——這個結論直接框定了本計畫的 Scope Boundaries（不重新論證模組化）。
- **`2026-06-05-lite-accepted-deferrals.md`**：R7/R8/R10 三個延後決策各自有明確恢復觸發條件——E3 直接對照這些觸發條件與目前 scheduler/keepalive/recheck 的實際狀態。
- **`salvage-unmerged-work-from-dirty-behind-main-tree-2026-05-26.md`**：若本計畫執行過程中發現 Phase 3 遺留的 `.gitignore`/`frontend/src/lib/` 未合併修復需要處理，此文件提供安全的搶救流程（snapshot → 分類 → 零迴歸證明 → 乾淨 worktree 重建）——本計畫不主動處理該項（屬 Phase 3 的收尾工作），但 E-系列 unit 若意外撞到，照此流程處理而非臨場發明。

### External References

未做外部研究——本次全部發現都是既有內部機制（debt registry、budget ratchet、vulture gate、benchmark 型態、seam 分類法）在特定角落沒被套用，屬於補完既有慣例的誠實度掃描，不涉及新技術引入。

## Key Technical Decisions（關鍵技術決策）

| # | 決策 | 理由 |
|---|---|---|
| K1 | **E1（測試基準量測）與 E3（LITE 觸發條件驗證）均為唯讀單元，不修改任何原始碼或測試檔案** | 避免與 v0.6.0 U1 在途分支（`fix/u1-test-suite-triage`）及 reconcile 計畫的 git 歷史工作產生檔案級衝突；讀寫分離讓盤點資料可以先被審查，如 v0.6.0 U14 的先例 |
| K2 | **D1（`_TransientHTTPError` 收斂）排在 D2 之前** | D2 要對 `publishing/adapters/` 做 except-Exception 分類，若先讓 4 個重複的 exception 類別收斂成一個，D2 的分類基礎更乾淨，不用同時處理「這是哪個 TransientError」的額外變數 |
| K3 | **不啟用 ruff 的 `BLE001`（flake8-blind-except）規則** | 465 個 `except Exception` 站點若要套用 BLE001，需要為每個判定為「合理邊界捕捉」的站點加 per-site `# noqa: BLE001`——這在 D2/D3 的分類方法論（`debt_registry.toml` + `# debt: <slug>`）已經達成同等的誠實度追蹤效果前提下，是重複建置兩套治理機制。C1 只清除死註解、記錄決策理由於 `pyproject.toml` 註解中；待 D2/D3 完成分類、有完整資料後，未來若要重新評估啟用 BLE，屆時再議 |
| K4 | **B2（天花板調升）與 v0.6.0 計畫協調，不搶跑** | `registry.py`／`spec.py` 是 v0.6.0 U10/U3/U5/U6/U7 直接會碰的檔案；本計畫調升 ceiling 前先查其進度，避免兩份 PR 各自調整同一 TOML 條目造成合併衝突 |
| K5 | **D2 對「疑似接縫靜默丟失」的站點套用 seam 三態分類框架，其餘站點沿用標準 debt_registry 分類** | 56 個站點裡多數是既有的型別轉譯樣板（`except Exception as exc: raise ExternalServiceError(...) from exc`），少數（如 `medium_browser.py` 271/322/330 行的 Playwright UI 互動捕捉）有實際遮蔽真實失敗的風險，值得用更嚴格的框架個別審視，而非一視同仁貼標籤 |
| K6 | **A1 的守護測試強化採用「掃描式」而非「列舉式」防禦**：新測試應該用 `_LazyStore(` 的 grep/AST 掃描找出 `webui_store/*.py` 裡所有的單例宣告，並斷言每一個都出現在 `__init__.py` 的 `__all__` 與 `_refresh_paths()` 的重設清單中，而不是像現有測試一樣手動列舉 4 個名字 | 現有 `tests/test_webui_store_pkg/test_store_init.py` 只枚舉原始 4 個 store，這正是它抓不到第 2、3 次重演的原因；掃描式斷言對任何未來新增的 store 都自動生效，不需要每次手動更新測試 |
| K7 | **E2 只新增 benchmark，不修改 `webui_store/history.py` 等熱點的實作邏輯** | 目標是建立效能基準線，供未來真正要做效能優化的計畫比較用；本計畫範圍不含實際優化這些路徑（那是下一輪迭代的判斷依據） |
| K8〔deepening 新增〕 | **D2/D3 對「疑似接縫靜默丟失」站點判斷「本 unit 內修復」vs「記錄 `open` 留待另開追蹤項」時，依序套用以下四步判斷，不得僅寫「依風險程度判斷」：(1) 該 except 是否位於產生「權威輸出欄位」（status/verdict/published_url/bound 狀態——其他子系統或 store 會當作既定事實、不會再覆核的欄位）的路徑上？若否（純資訊/展示欄位、best-effort 旁路，或例外已朝「失敗/未確認」方向 fail-closed 退化，讓呼叫端自然重試或視為尚未完成），一律 `accepted`——例如 `cli/_bind/recipes/velog.py` 106/114/127 行例外時把 `authed` 留在 `False`，輪詢迴圈只是繼續等待，不會誤判為已綁定。(2) 若是，檢查是否已有「獨立、無條件執行」的覆核機制稍後會重新驗證同一事實（keepalive/recheck 探測、canary link-attr 驗證、排程 reconcile）。若有，記錄 `open`、`severity = "medium"`，rationale 需指名該覆核機制與其執行時窗——例如 `link_attr_verifier.py` 多處 `except Exception` 退化為 `unknown`/generic 判定是安全的，因為 `recheck/probe.py` 對 `uncertain` 平台已有獨立的 dofollow 覆核路徑（2026-06-05 `live-dofollow-undercounting` Gap 3 的修復）稍後會重新解析同一訊號。(3) 若沒有覆核機制——此站點一旦誤判就會變成永久、無人再檢查的「假成功」——且修復可表達成該 except handler 自身回傳值的局部修改（不需新建偵測基礎設施），則**必須在本 unit 內修復**，依 Test scenarios 既有規定寫紅→綠測試——例如 `medium_browser.py:330` 的 Save Draft 點擊失敗後仍落到 `final_url = page.url` 並回傳 `AdapterResult(status="drafted", ...)`，沒有任何其他機制驗證草稿真的被儲存；此站點已被 `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 點名為「critical silent swallow」，與三篇接縫案例共同的 bug 形狀（權威狀態欄位在失敗時仍宣告成功）完全同型，**判定為 D2 內必須修復的具名站點**。(4) 若沒有覆核機制、且正確修復需要新建基礎設施（規模比照 `live-dofollow-undercounting` Gap 2 新增 `_unverified_universe`/`select_unverified_candidates` 那種新查詢/新資料流），記錄 `open`、`severity = "high"`，rationale 必須指名負責該基礎設施工作的後續計畫或 unit，不能只寫「之後修」。**〔doc-review 新增，adversarial 複核發現〕步驟 (2) 的「獨立覆核機制」必須是「不同的程式碼路徑或不同的資料來源」，不能是「呼叫回同一個函式/模組的另一個入口」——K8 原文舉的範例本身就不符合這個標準：`link_attr_verifier.py` 的 except-Exception 站點被判定安全，理由是 `recheck/probe.py` 有獨立覆核，但 `recheck/probe.py:103` 的 `inspect = inspect_fn or link_attr_verifier.inspect_target_anchor` 顯示這個「獨立」覆核實際上呼叫回 `link_attr_verifier.py` 自己（`inspect_target_anchor`），且與 `medium_browser.py` 的 `verify_link_attributes` 共用同一個 `_fetch_body_via_preflight` helper——若這個共用 helper 本身有系統性盲點（例如 URL 正規化邊界情況），「原始訊號」與「獨立覆核」會產生同一個錯誤答案，等於零額外保護。執行 D2 前，先獨立審視 `_fetch_body_via_preflight`／`inspect_target_anchor` 本身的例外處理（`link_attr_verifier.py` 364/389/417 行），確認它們不是被其他機制覆核的「安全」站點，而是需要獨立評估的站點；同理，`events/projector.py::project_run_safe` 的「dashboard 的 project-on-read 是安全後備」註解也不構成獨立覆核——那只是對同一個失敗的 `flush_for` 函式手動重新呼叫，若原始失敗是確定性的（例如損毀的 checkpoint 格式），重試會得到一樣的失敗，D3 分類此站點時不能只憑這行註解就判定為 `accepted`。 | 56+25+22=103 個站點裡「風險程度」本身不是可操作的分界線——K5 只分出「型別轉譯樣板 vs 疑似接縫靜默丟失」兩類，但後者內部仍需回答三個獨立問題（是否在權威輸出欄位路徑上、是否已有獨立覆核、修復規模是局部還是需要新基礎設施）才能落到 accepted/open-medium/fix-now/open-high 四種結果之一；這讓分類可重現、可被下一個 reviewer 用同一套問題覆核，而不是依賴實作者對「風險程度」的主觀判斷 |

| K9〔doc-review 新增，product-lens 複核發現〕 | **本計畫是目前第 5 個 active 計畫，而 v0.6.0（priority: high，15 個單元）僅完成 1 個（U1，且尚未在真實 CI 上確認合併）——這個優先序取捨是刻意選擇，而非疏漏**：使用者已明確選擇「全新全項目優化審查」而非延續既有計畫，本計畫的 12 個單元多數是小型、獨立、與 v0.6.0 檔案範圍不重疊的修復（唯一例外是 B2，已透過 K4 與 v0.6.0 協調時序），執行時不會搶佔 v0.6.0 的工時；但若使用者之後判斷應該優先完成 v0.6.0 backlog，本計畫的任何未開始單元都可以暫緩，不需要撤銷已完成的部分 | 記錄本次規劃期間曾提出「是否該先完成 v0.6.0 backlog」的問題（product-lens 複核），使用者未在規劃階段即時回覆——依照最保守的預設處理方式（記錄取捨、不阻塞、不重排），實際執行優先序留給使用者在啟動任何單元前決定 |

## Open Questions（開放問題）

### Resolved During Planning

- 是否要包含全部 15 項研究發現：使用者已選擇「全新全項目優化審查」，本計畫收斂為 12 個涵蓋最高信心度／最佳範圍匹配的項目，其餘（如 debt_registry 刪除已解決項目而非標記 `resolved_date` 的治理慣例落差）記錄在 Documentation / Operational Notes 而非獨立 unit，因為它們沒有明確的程式碼修復動作。
- BLE001 規則是否啟用：不啟用，見 K3。
- E1 與 v0.6.0 U1 的關係：E1 是獨立、唯讀的重新量測，不假設 U1 分支結果是定論，也不修復任何殘餘失敗（那是 U1 的範圍）。

### Deferred to Implementation

- D2/D3 分類後每個站點最終落在 `debt_registry.toml` 的 `severity` 與 `status`（`open` vs `accepted`）——需要實際讀過每個站點的上下文才能判斷，不能在規劃階段預先決定。
- E1 的殘餘失敗根因分群結果——只能實測得知，可能與 v0.6.0 U1 分支的 90 個殘餘不同（因為兩者量測時間點不同、且未合併分支的效果尚未反映在本計畫可見的 main 上）。
- E3 若發現 LITE 觸發條件已成立，後續獨立計畫的範圍與優先序——留給使用者在看到 E3 結果後決定。
- B1/B2 實際要調高的 ceiling 數值——需要在執行當下重新用 `radon` 量測，不沿用本文件記錄的快照數字。

### From Document Review（doc-review 複核，FYI 級觀察，不強制決策）

- **K3（不啟用 BLE001）是一項治理哲學決策，而非純技術細節**：product-lens 複核指出，鑑於 `STEWARDSHIP.md` 的「Debt governance」領域目前 `[unassigned]`，這個決策目前是由本計畫單方面拍板，沒有一個責任人可以獨立覆核這個取捨。K3 本文已註明「待 D2/D3 完成分類、有完整資料後可重新評估」，這裡僅記錄：若未來要重新評估，應該是一次明確的、有責任人覆核的決策，而不是預設維持現狀。
- **K8 的四步判斷法被設計為可重複使用的治理方法論**（K8 原文：「這讓分類可重現、可被下一個 reviewer 用同一套問題覆核」），product-lens 複核建議：若這套方法論打算成為本專案往後所有 except-Exception 分類工作的標準做法，值得在本計畫完成後促成一份獨立文件（如 `AGENTS.md` 或 `docs/solutions/`），而不是只留在這份計畫文件裡。
- **E1 的獨立量測數字不會與 v0.6.0 U1 分支的 90 個殘餘做調和**——K1 已刻意設計成唯讀、不修復，product-lens 複核提出另一個角度：更直接降低測試風險的路徑可能是驗證/推進 U1 分支上真實 CI，而非產生第二份不調和的量測報告。E1 仍保留現狀設計（唯讀、獨立），但這個替代角度值得記錄供執行時參考。
- **`tests/test_dead_code_advisory.py` 的設計本質是 advisory（`warnings.warn`），非 CI 阻斷閘門**——adversarial 複核指出 Problem Frame 第 2 項「已被證實完全失效」的措辭略微誇大：目前沒有任何 CI workflow 對這個檔案套用 `-W error::UserWarning`，所以 Windows 上的路徑分隔符 bug 影響的是「警告摘要的準確度」而非「一個原本會擋 CI 的閘門失效」。A3 的修復本身依然成立，只是嚴重度框架應該對應到「警告失真」而非「阻斷閘門失效」。
- **`debt_registry.toml` 治理慣例落差**（commit `f835820e` 刪除已解決項目而非標記 `resolved_date`）：scope-guardian 複核指出這與 A1/A3 選為獨立 unit 的判斷標準（「既有機制在某角落沒被正確套用」）其實是同一類問題，但本計畫選擇只記錄為 Documentation Note 而非獨立 unit——這個範圍界線的不一致程度輕微（git 歷史仍保留完整記錄，無功能性缺陷），予以記錄但不改變本計畫的範圍分類。

## Implementation Units

> 執行紀律：每個 unit 獨立分支、動手前 `git status` 確認乾淨並重新查一次 `docs/plans/` 有無新的重疊 active 計畫（尤其是 reconcile 計畫的狀態，見 Concurrent Plan Coordination）；碰 `debt_registry.toml`／`# debt: <slug>` 的 unit 沿用 Phase 3 D2/D2b 確立的 schema，不自創新格式。**〔doc-review 新增，feasibility 複核直接重現〕在非 UTF-8 locale 的 Windows 機器上，`tests/test_no_monolith_regrowth.py`、`tests/test_no_complexity_regrowth.py`、`tests/test_debt_registry_format.py`、`tests/test_debt_registry_freshness.py` 皆用裸 `Path.read_text()` 讀取 TOML，會在 collection 階段直接拋出未處理的 `UnicodeDecodeError`（`pytest tests/ --collect-only` 在本機重現為「Interrupted: 6 errors during collection」）。這與 `2026-07-03-001` Windows encoding-fix 計畫涵蓋的 subprocess/console 編碼問題是不同根因（該計畫只處理 subprocess 文字 I/O，不含這個裸 `read_text()` pattern），屬於本計畫執行環境的前置條件，不是要修的功能缺陷：**執行本文件任何涉及 pytest 的指令前，先設定 `PYTHONUTF8=1`（或 `PYTHONIOENCODING=utf-8`）**，B1、B2、D2、D3、E1 的 Verification 步驟皆適用。若這個根因值得長期修復，可另外建議併入 `2026-07-03-001` 計畫的範圍（同一根因類型），但不在本計畫內處理。

```mermaid
graph TB
    A1[A1 store 單例完整性] 
    A2[A2 test tier 修正]
    A3[A3 vulture allowlist 修復]
    B1[B1 budget 完整性補齊] -.->|建議晚於，非硬依賴| B2[B2 天花板調升]
    C1[C1 noqa 誠實化]
    D1[D1 TransientHTTPError 收斂] --> D2[D2 adapters/ 分類掃描]
    D1 --> D3[D3 _bind/+events/ 分類掃描]
    E1[E1 測試基準唯讀量測]
    E2[E2 熱點 benchmark 補齊]
    E3[E3 LITE 觸發條件驗證]
```

（A/B/C/E 系列彼此獨立、可平行執行；D 系列內部 D1 先行，D2/D3 可平行；B2 需與 v0.6.0 計畫協調時序，見 Concurrent Plan Coordination。）

---

### Sprint A — 基礎正確性修復（小型、高信心）

- [x] **A1: `webui_store` 單例完整性修復 + 掃描式守護測試〔R1〕** ✅ 已完成（含 `error_report_store`/`verify_health_store` 皆已修復；私有 DB 連線經調查後決定維持現狀，理由見執行紀錄）

**Goal:** 修復 `verify_health_store` 與 `error_report_store` 未被 `_refresh_paths()` 重設、未被 `__init__.py::__all__` 匯出的遺漏，並用掃描式測試防止第三次同型重演。

**Dependencies:** 無。

**Files:**
- Modify: `webui_store/__init__.py`（`_refresh_paths()` 重設清單、`__all__`）
- Modify: `webui_store/verify_health.py`、`webui_store/error_reports.py`（若需改用共享 `_get_webui_db()` 快取而非各自私有 `WebUIDatabase` 實例）
- Modify: `tests/test_webui_store_pkg/test_store_init.py`（改為掃描式斷言）
- Test: `tests/test_webui_store_pkg/test_store_init.py`

**Approach:**
1. 確認 `verify_health_store`／`error_report_store` 目前各自建立私有 `WebUIDatabase` 實例的原因（是否有意設計成獨立連線），若無特殊理由則改用 `_get_webui_db()` 共享快取，與其他 8 個 store 一致。**〔doc-review 新增，scope-guardian 複核發現〕這項調查設定時間框：若 15 分鐘內無法排除「刻意獨立連線」的可能性，或改用共享快取後出現非預期的連線爭用行為，就保留現狀的私有連線，本 unit 只做 `__all__`／`_refresh_paths()` 的修復，把快取整合留給後續 unit——不要讓這項調查無限展開，A1 的核心目標是修復遺漏，不是重構 store 的連線模型。**
2. 兩者加入 `webui_store/__init__.py` 的 `__all__` 匯出與 `_refresh_paths()` 的重設 tuple。
3. 重寫守護測試：用 grep/AST 掃描 `webui_store/*.py` 找出所有 `_LazyStore(` 宣告，斷言每一個對應名稱都出現在 `__all__` 與 `_refresh_paths()` 清單中（K6）。

**Patterns to follow:** `tests/test_events_r8_gates.py` 的紅色路徑自證模式；現有 8 個 store 在 `__init__.py` 的宣告方式。

**Test scenarios:**
- Happy path：掃描式守護測試對修復後的 `__init__.py` 綠燈（10 個 store 全部被追蹤）。
- 紅色路徑：故意在測試 fixture 裡新增一個第 11 個 `_LazyStore` 但不加入 `__all__`/`_refresh_paths()` → 守護測試須紅燈，證明掃描式斷言真的有效（而非退化成另一種硬編碼列舉）。
- Integration：`tests/test_webui_store_verify_health.py` 現有的 `_refresh_paths()` 呼叫（目前是 no-op）在修復後應該真正重設該 store 的內部快取——需要一個能觀察到快取確實被清空的斷言（例如修改 config dir 後驗證新路徑生效），而不只是呼叫函式不出錯。

**Verification:** 掃描式守護測試綠燈且紅色路徑自證通過；`tests/test_webui_store_verify_health.py` 與新增/修改的 `error_reports` 對應測試全綠。

---

- [x] **A2: 測試 tier 標記修正〔R2〕** ✅ 已完成（改為 `integration`，不是 `e2e`——確認不觸碰真實網路/瀏覽器）

**Goal:** `tests/integration/test_pipeline_e2e.py` 目前宣告 `__tier__ = "unit"`，與其目錄（`tests/integration/`）和檔名（`*_e2e.py`）矛盾，且無註解說明原因——修正為正確 tier。

**Dependencies:** 無。

**Files:**
- Modify: `tests/integration/test_pipeline_e2e.py`

**Approach:** 讀懂該測試實際的執行內容與耗時特性，對照 `tests/integration/test_gsc_referral_integration.py`（已正確宣告 `integration`）的判斷標準，改為正確的 `__tier__` 值（`integration` 或 `e2e`，依實際內容而定）。若刻意標成 `unit` 有未記錄的理由（例如故意讓它跑得快、內容其實不觸碰外部依賴），改為在程式碼中加註解說明，而非直接改動 tier。

**Test expectation:** none -- 純測試中繼資料修正，其正確性由 CI 的 tier 過濾行為（`pytest -m "unit"` 是否納入/排除此檔）直接體現，不需要額外的單元測試。

**Verification:** `pytest -m "unit"` 與 `pytest -m "integration"`（或對應 tier）的收集結果符合修正後的分類；CI 的 unit job 執行時間未因此意外拉長或缩短到異常範圍。

---

- [x] **A3: Vulture allowlist 跨平台路徑修復〔R3〕** ✅ 已完成（分隔符修復生效，另發現 17 個真實既存未 allowlist 發現，記錄為後續追蹤項，見 Verification）

**Goal:** 修復 `tests/test_dead_code_advisory.py::_key()` 在 Windows 上因路徑分隔符不一致導致整個 dead-code advisory gate 失效的問題，並更新 2 筆過期的行號。

**Dependencies:** 無。

**Files:**
- Modify: `tests/test_dead_code_advisory.py`

**Approach:**
1. 修復 `_key()`：對 `path.relative_to(REPO_ROOT)` 的結果做路徑分隔符正規化（`.replace("\\", "/")`），比照 `_scan_for_undeclared_monoliths` 既有的同類修復模式。
2. 更新過期行號：`content/fetch.py` 從 `:56` 改為 `:52`；`livejournal_api.py` 從 `:154` 改為 `:138`（需在執行時重新確認實際行號，不沿用本文件記錄的快照）。
3. 重新跑一次完整 vulture 掃描，確認 60% 信心門檻下的發現數（研究時量測為 545，較設定門檻時的 343 成長 59%）是否需要重新校準門檻或新增 allowlist 項目——若發現數過多，記錄為後續追蹤項而非本 unit 內全部清理。

**Test scenarios:**
- Happy path：`pytest tests/test_dead_code_advisory.py -W error::UserWarning` 在 Windows 與 Linux 兩種路徑分隔符下皆不觸發誤判警告。
- Edge case：allowlist 中含巢狀路徑（多層目錄）的項目在兩種平台下都能正確比對。
- 紅色路徑：故意讓某個真實 allowlist 項目的行號錯誤 → 測試應明確標示是哪個項目行號不符,而非籠統失敗。

**Verification:**〔執行期更正〕`pytest tests/test_dead_code_advisory.py`（不加 `-W error::UserWarning`，與實際 CI 呼叫方式一致——CI 從未套用該 flag，本測試設計上就是 advisory-only）通過（36 passed, 17 warnings）；分隔符修復本身已用 A/B 對照證實有效（修復前 22/22 個 80% 信心度發現誤判為「未在 allowlist」，修復後僅 17/22，且這 17 個是真實、修復前因 bug 而從未被看見的既存問題，不是修復引入的新問題）。**執行期發現，偏離規劃假設**：原本假設 80% 信心度門檻下的發現數會剛好等於 6 個 allowlist 項目（零 surplus），但即時重跑顯示實際是 22 個發現、17 個未被 allowlist（全部是 adapter 檔案裡「return 後接不可達程式碼」的同型態，例：`devto_api.py:70`、`wordpresscom_api.py:28`、`writeas_api.py:28`、`zenn_github.py:59` 等）——這比原本規劃的「60% 信息性門檻可能需要重新校準」更明確、範圍更小，但仍超出本 unit 的範圍（比照計畫本身的 scope 註記：發現數過多時記錄為後續追蹤項，不在本 unit 內展開）。**後續追蹤項**：17 個「return 後不可達程式碼」很像是跨 adapter 複製貼上的同型模式，值得開一個小範圍的後續 unit 逐一確認是否為真死碼或建立新的 allowlist 分類規則（而非逐條加 allowlist）。6 個既有 allowlist 項目中，`content/fetch.py`（:53，非原快照的 :52）與 `livejournal_api.py`（:151，非原快照的 :138）兩筆行號已修正；`_chrome_session_impl.py` 的 `Page` unused-import 項目經確認已不再是真實發現（`Page` 現在被一處回傳型別註解使用），目前是無害但過期的 allowlist 項目，未動它，留待下次 allowlist 整體整理時一併處理。

---

### Sprint B — 複雜度／SLOC 預算完整性

- [x] **B1: 補齊未追蹤的 SLOC／複雜度預算項目〔R4〕** ✅ 已完成（commit `0441486f`）——11 個 SLOC 項目 + 3 個 CC 項目全數補上，`pytest tests/test_no_monolith_regrowth.py tests/test_no_complexity_regrowth.py` 對新增項目全數通過。**執行期發現，偏離規劃假設**：3 個新追蹤函式（CC 27–29）都低於 CC-30 backstop，原本「沿用既有 style（exact-current-CC 零 headroom）」的假設不適用——那個慣例只用於已經超過 backstop 的函式。改用 `ceiling = 31`（backstop+1，schema 本身文件化的最小合法 seed 值）統一套用於三者，並在 rationale 中說明理由。另外，`pytest` 全量執行仍有 9 個既有失敗（`cli/publish_backlinks/__init__.py`、`webui_store/channel_status.py`、`webui_app/routes/health.py`、`webui_app/health_metrics.py`、`cli/_report_format.py`）——經比對 branch base commit（`667e5cce`）確認為此分支建立前就已存在的 SLOC/ceiling 漂移，與 B1、C1 皆無關（`git diff --stat` 顯示這些檔案在 C1 前後行數不變，純 noqa 註解增刪），不在本 unit 範圍內修復，記錄為後續追蹤項。

**Goal:** 為 11 個落在 300–370 SLOC 區間但未被 `monolith_budget.toml` 追蹤的檔案，以及 3 個未被 `complexity_budget.toml` 追蹤的高複雜度函式（`spray_backlinks/core.py::main` CC 29、`medium_brave.py::MediumBraveAdapter.publish` CC 27、`_seal_init.py::_handle_init` CC 27），補上正式的預算項目。

**Dependencies:** 無。

**Files:**
- Modify: `monolith_budget.toml`
- Modify: `complexity_budget.toml`

**Approach:**
1. 執行時重新用 `radon` 量測所有候選檔案/函式的當下實際數值（不沿用本文件快照）。
2. 對每一項套用既有的 ratchet 公式（`round_up_to_10(SLOC+30)`）設定 ceiling，並附 ≥80 字 rationale 說明為何這是「新追蹤」而非「新超標」。
3. 特別標註 `spray_backlinks/core.py::main`（CC 29，僅差 1 點觸及 CI 硬性 CC-30 backstop）為優先項，避免它在下一次無關的小改動時意外撞牆而阻塞其他 PR。

**Test expectation:** none -- 純 TOML 設定新增，其正確性由 `tests/test_no_monolith_regrowth.py`／`tests/test_no_complexity_regrowth.py` 既有的 CI 閘門直接驗證。

**Verification:** `pytest tests/test_no_monolith_regrowth.py tests/test_no_complexity_regrowth.py` 通過；新增的 11+3 個項目在兩份 TOML 中皆可查到且 rationale ≥80 字。

---

- [x] **B2: 高滿載天花板預先調高（`registry.py`／`spec.py`）〔R5〕** ✅ 已完成（commit `c8c64a38`）——`registry.py` 340→364、`spec.py` 1290→1309。協調檢查：掃描本 workspace 所有本地 worktree 分支、`origin/*`、`gitlab/*`，確認沒有任何分支對這兩檔案有領先 `main` 的 commit；v0.6.0 計畫的 U10 Files 清單未直接列出 `registry.py`，K22 對 `spec.py` 的成長估計則延後到 U3/U5/U6/U7 實際落地時才會有具體數字——皆已記錄於 rationale。**執行期發現，偏離規劃假設**：原計畫 Approach 建議「比照 v0.6.0 自己 K22 的做法一次涵蓋兩份計畫的預估總成長量」，但 `tests/test_no_monolith_regrowth.py::test_policy_to_seed_drift` 有一條無條件的 `SEED_HEADROOM_MAX=50` 反漂移閘門（`ceiling-SLOC<=50`，沒有 rationale 可覆寫），使得單次 PR 能調升的幅度被硬性上限鎖住——因此改用兩檔案各自的 `SLOC+50` 最大合規值（364、1309），而非更大膽的 K22 式一次到位緩衝，並在 rationale 中記錄下一個實際落地 v0.6.0 endpoint 成長的 unit 應重新檢查此 ceiling 是否仍有餘裕。

**Goal:** 為已達 95%+ 天花板的 `publishing/registry.py` 與 `webui_app/api/v1/spec.py` 預先調高 ceiling，避免它們在 v0.6.0 計畫的平行化/路由遷移 unit 進行到一半時意外撞牆。

**Dependencies:** 建議晚於 B1（避免同一 PR 週期內對兩份 TOML 做過多次調整），且需與 v0.6.0 計畫協調（見 Concurrent Plan Coordination）。

**Files:**
- Modify: `monolith_budget.toml`

**Approach:**
1. 執行前查詢 v0.6.0 計畫中 U10（`registry.py`）與 U3/U5/U6/U7（`spec.py`）的實際進度——若對應 unit 已經在其他分支上動工，協調由誰負責這次調升，避免衝突。
2. 調升幅度需一次涵蓋兩份計畫（本計畫 + v0.6.0）對這兩個檔案的預估總成長量，而非只解決眼前的些微超標，比照 v0.6.0 自己 K22 的做法。
3. rationale 需明確引用 v0.6.0 計畫作為調升原因之一。

**Test expectation:** none -- 純 TOML ceiling 調升，正確性由既有 CI 閘門驗證。

**Verification:** `tests/test_no_monolith_regrowth.py` 通過；rationale 明確記錄本次調升考量了 v0.6.0 計畫的預估需求。

---

### Sprint C — Lint 債務誠實化

- [x] **C1: 清除死 `noqa` 註解 + 記錄 BLE 規則決策〔R6〕** ✅ 已完成（commit `4bf8b70f`）——132 檔（131 原始碼 + `pyproject.toml`）、共移除 340 個死 `noqa`（218 個 `BLE001` 符合原估計，另 122 個是同樣已被 per-file-ignores 涵蓋的 `F401`/`E402`/其他規則死註解）。`ruff check --extend-select RUF100` 復驗確認 0 殘留；`ruff check src/ webui_app/ webui_store/` 前後皆為 173 個既有錯誤、集合完全相同，證實純註解移除、無行為/lint 訊號變化。**執行期發現，偏離規劃假設**：計畫原文的 `ruff check --select RUF100 --fix` 指令本身有風險——`--select` 會**取代**（而非疊加）`pyproject.toml` 設定的規則集，導致 ruff 判斷「noqa 是否死亡」時只看得到 RUF100、看不到專案實際啟用的 `F,E,W,UP,I`，因而誤刪了仍在抑制真實違規的合法 noqa（例如 `anchor/profile.py` 的 `# noqa: F401`/`E402`）。第一次嘗試導致全專案錯誤數從 173 暴增到 377，已用 `git checkout --` 撤銷重做。正確指令改為 `ruff check --extend-select RUF100 --fix --fixable RUF100 src/ webui_app/ webui_store/`（疊加規則集以取得正確判斷情境，同時把自動修復範圍限制在僅 RUF100）。

**Goal:** 清除約 200 個暗示「已通過 lint 審查」但實際從未被任何啟用規則檢查過的 `# noqa: BLE001` 註解，以及其他重複/已被 `per-file-ignores` 涵蓋的 `F401`/`E402` 死註解，並在 `pyproject.toml` 中明確記錄「暫不啟用 BLE 規則」的決策理由。

**Dependencies:** 無（建議先於 D2/D3，讓後續的 except-Exception 分類掃描不受過期 noqa 註解干擾，但非硬性檔案級依賴）。

**Files:**
- Modify: 受影響的原始碼檔案（`ruff check --select RUF100 --fix` 自動處理，範圍涵蓋 `webui_app/api/v1/__init__.py`、`routes/health.py`、`config/__init__.py`、`content/fetch.py`、`keepalive_job.py` 等高密度檔案）
- Modify: `pyproject.toml`（新增註解說明 BLE 規則決策，見 K3）

**Approach:**
1. 執行 `ruff check --select RUF100 --fix` 自動清除確認為死掉的 noqa 註解。
2. 人工複核清除結果，確認沒有誤刪仍然有效的 noqa（例如涵蓋已啟用規則的合法抑制）。
3. 在 `pyproject.toml` 的 `[tool.ruff.lint]` 區塊附近加註解，說明本專案的 except-Exception 治理策略是 `debt_registry.toml` + `# debt: <slug>`（Phase 3 D2 方法論），而非 BLE 規則，並記錄「若未來 D2/D3 分類資料顯示有系統性需求，可重新評估」。

**Test scenarios:**
- Happy path：`ruff check --select RUF100 src/ webui_app/ webui_store/` 清除後回報 0 個可自動修復的多餘 noqa。
- Edge case：手動複核抽樣的 20 個被清除的 noqa 註解位置，確認清除後 `ruff check` 對那些站點沒有新增任何警告（證明它們確實是死註解，不是遺漏規則配置）。

**Verification:** 完整 `ruff check src/ webui_app/ webui_store/` 通過（不新增任何新警告）；`pyproject.toml` 的決策註解可讀、有日期與理由。

---

### Sprint D — Exception Hygiene 掃描擴展（延續 Phase 3 D2 方法論）

- [ ] **D1: `_TransientHTTPError` 重複定義收斂〔R7〕**

**Goal:** 將 `blogger_api.py`、`medium_api.py`、`velog_graphql.py`、`llm_anchor_provider.py` 四處各自獨立定義的 `_TransientHTTPError` 收斂為統一使用 `publishing/adapters/base.py` 既有的 `TransientError`。

**Dependencies:** 無（建議先於 D2，見 K2）。

**Files:**
- Modify: `publishing/adapters/blogger_api.py`、`publishing/adapters/medium_api.py`、`publishing/adapters/velog_graphql.py`、`publishing/adapters/llm_anchor_provider.py`
- Modify: `publishing/adapters/base.py`（若 `TransientError` 建構子需要擴充以涵蓋四個重複定義各自的建構參數差異）
- Test: 對應四個 adapter 現有的測試檔案

**Approach:**
1. 比對四個 `_TransientHTTPError` 建構子的差異，確認 `TransientError` 是否已涵蓋全部需求，若否則擴充（保持向後相容的呼叫方式）。
2. 逐一替換四個檔案的 import 與拋出點，移除各自的類別定義。
3. 確認任何 `except _TransientHTTPError:` 的捕捉點同步改為 `except TransientError:`（含 retry 邏輯 `retry.py` 若有針對特定類別的判斷）。**〔deepening 複核提醒〕** `retry.py:65` 對 `_TransientHTTPError` 的提及只是註解文字（說明 retry 邏輯的設計意圖），不是第 5 個類別定義或 `except` 子句——執行時不要被原始 grep 命中數混淆，實際只有 4 個類別定義需要收斂。

**Patterns to follow:** `publishing/adapters/base.py` 現有的 `TransientError` 與其他 21 個已正確共用 `retry.py` 的 adapter 寫法。

**Test scenarios:**
- Happy path：四個 adapter 的既有測試（模擬暫時性 HTTP 錯誤觸發 retry）在改用共用類別後行為不變。
- Edge case：若四個原始類別的建構參數有差異（例如某個多帶一個 `retry_after` 欄位），確認收斂後的呼叫點沒有遺漏該參數導致 retry 邏輯行為改變。
- Integration：`retry.py` 對 `TransientError` 的捕捉邏輯正確涵蓋這四個 adapter 收斂後拋出的例外。

**Verification:** 四個 adapter 對應的既有測試全綠；`grep -rn "_TransientHTTPError" src/` 回傳空結果（確認完全收斂）。

---

- [ ] **D2: `publishing/adapters/` except-Exception 分類掃描〔R8〕**

**Goal:** 對 `publishing/adapters/` 目錄下 56 個 `except Exception` 站點（deepening 複核已用即時 grep 更正自研究快照的 78；Phase 3 D2 明確排除的區塊）套用相同的分類方法論，優先審視有靜默丟失真實失敗訊號風險的站點。

**Dependencies:** D1（乾淨的 exception 類別基礎）。

**Files:**
- Modify: `publishing/adapters/`（28 個檔案，56 個 `except Exception` 站點，deepening 複核已逐檔計數，執行前仍需重新 grep 確認未變動）：`_verify_live.py`(5, 另有 1 處 tuple-form `except (ValueError, Exception):` 於第 276 行同屬此類)、`medium_browser.py`(9)、`link_attr_verifier.py`(6)、`llm_anchor_provider.py`(4)、`http_form_post.py`(3)、`medium_auth.py`(3)、`medium_liveness.py`(3)、`blogger_api.py`(2)、`medium_brave.py`(2)、其餘 19 個檔案各 1 處（`config_driven.py`／`devto_api.py`／`ghpages.py`／`gitlabpages.py`／`hackmd_api.py`／`hashnode_graphql.py`／`hatena_atompub.py`／`instant_web.py`／`linkedin_api.py`／`mataroa_api.py`／`notion_api.py`／`rentry_api.py`／`retry.py`／`substack_api.py`／`telegraph_api.py`／`tumblr_api.py`／`wordpresscom_api.py`／`writeas_api.py`／`zenn_github.py`）
- Modify: `debt_registry.toml`（新增分類後的 debt 項目）
- Test: 對應 adapter 的既有測試 + 針對高風險站點新增的紅色路徑測試

**Approach:**
1. 沿用 Phase 3 D2/D2b 的分類方法論：對每個站點判斷是「型別轉譯樣板」（`except Exception as exc: raise ExternalServiceError(...) from exc`，安全）還是「疑似接縫靜默丟失」（吞掉例外或回傳籠統成功狀態）。
2. 對 `medium_browser.py` 271/322/330 行等 Playwright UI 互動捕捉點套用 K5 的嚴格審視——確認是否可能把「選擇器失效」誤判為通用失敗，比對 `docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift-2026-05-26.md` 的三態分類框架（`kind | NO_EMIT | QUARANTINE`）判斷是否需要引入類似的顯式分類，而不是單純加註解。**deepening 複核已確認第 330 行（Save Draft 點擊失敗仍回傳 `AdapterResult(status="drafted", ...)`）依 K8 判斷落在「必須本 unit 內修復」——這是一個具名、確定要修的站點，不是待評估項；第 271 行（CAPTCHA 探測，例外會 re-raise）與第 322 行（標籤插入，best-effort）依 K8 判斷落在 `accepted`。**〔doc-review 新增〕`link_attr_verifier.py` 自己的 6 個站點（364/389/417 行等）應該優先分類，不要等到其他站點引用它作為「已有獨立覆核」的理由時才回頭看——見 K8 的補充說明。
3. 對確認安全的站點加 `# debt: <slug>` 註解 + `debt_registry.toml` 的 `accepted` 項目；對確認有風險的站點記錄為 `open` 並在 rationale 中說明具體修復方向（是否需要本 unit 內修復或另開追蹤項，依 K8 的四步判斷順序決定，不再籠統寫「依風險程度」）。**`debt_registry.toml` 支援單一 rationale 涵蓋多個同檔案、同函式或 sibling 函式的站點（見 schema 對 `location` 陣列的說明與既有的 `campaign-bootstrap-status-fail-soft`／`image-gen-*` 批次先例）——預期結果是一組「同理由聚類」的 entry，不是 56 個各自獨立的 entry；風險理由明顯不同的站點（如第 330 行）仍應獨立成一個 entry。〔doc-review 新增，adversarial 複核發現〕`tests/test_debt_registry_format.py` 目前只強制 rationale 長度、slug/location 唯一性與交叉引用完整性，沒有任何機制阻止「一個 entry 的 location 陣列橫跨十幾個不同檔案、用一句籠統理由帶過」這種形式上合規但實質規避個別風險判斷的寫法——聚類的正確邊界是同一檔案內的同一函式或 sibling 函式（如既有先例所示），**PR review 時人工確認每個 entry 的 location 陣列沒有跨越無關檔案／無關風險類別，不能只看自動化測試是否通過**。**
4. **〔deepening 新增〕依風險分批送出獨立、可各自合併的 PR，不要求一次涵蓋全部 56 個站點：批次一優先處理 K5 標記的高風險站點（`medium_browser.py` 271/322/330，含第 330 行的修復與紅→綠測試）並完成其 K8 判定；後續批次再依 adapter 檔案分組，逐批完成其餘型別轉譯樣板站點的 `debt_registry.toml` 分類。**
5. **〔doc-review 新增，security-lens 複核發現〕除了 K5/K8 的「是否遮蔽真實失敗」判斷外，同步檢查每個站點的例外文字是否會未經清洗流向使用者可見的輸出**：至少 15 個 adapter（`blogger_api.py`、`medium_api.py`、`devto_api.py`、`notion_api.py`、`wordpresscom_api.py`、`linkedin_api.py`、`gitlabpages.py`、`hashnode_graphql.py`、`mataroa_api.py`、`rentry_api.py`、`substack_api.py`、`tumblr_api.py`、`writeas_api.py`、`zenn_github.py` 等）目前直接把 `raise ExternalServiceError(f\"...HTTP {status}: {resp.text[:200]}\")` 這類原始回應內文塞進 `AdapterResult.error`，經 stdout JSONL 流向 WebUI。`publishing/adapters/llm_anchor_provider.py`（本身也在 D2 範圍內）已有既存的安全樣板可循——其 `_redact_for_log` helper 明確標榜「所有 log 與 str(exc) payload 都要經過清洗」，`debt_registry.toml` 也已有一筆 `pipeline-regen-body-llm-call-error-redacted` entry 把它記錄為既有安全模式。分類時對每個嵌入 `resp.text`/`str(exc)` 到 `AdapterResult.error` 的站點，確認目標 API 的錯誤回應不會回顯請求標頭/token，否則要求改用 `_redact_for_log` 或 `scrub_text()` 清洗後才寫入。

**Test scenarios:**
- Happy path：每個新分類的 debt 項目通過 `tests/test_debt_registry_format.py` 的 schema 驗證（唯一性、rationale 長度、location 交叉引用）。
- 紅色路徑：`medium_browser.py:330` 的 Save Draft 失敗情境——模擬點擊拋出例外，證明目前行為仍回傳 `status="drafted"`（先紅，重現已被 `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 點名的 critical silent swallow），修復後應回傳明確的失敗/未確認狀態（後綠）。
- Integration：`medium_browser.py` 第 271／322 行的 Playwright 互動失敗情境（模擬選擇器找不到元素）驗證其現有行為（re-raise／best-effort 略過）與 K8 判定一致，不應該被誤分類為需要修復的站點。

**Verification:** `debt_registry.toml` 新增項目全數通過格式測試；`grep -c "except Exception" publishing/adapters/*.py` 的總站點數（56）與新增的 debt entry 涵蓋的 location 數一致（每個站點都被至少一個 entry 的 `location` 陣列涵蓋，沒有遺漏——entry 數量本身可遠少於 56，見 Approach 步驟 3 的批次慣例）；`medium_browser.py:330` 有對應紅→綠測試證明已修復。

---

- [ ] **D3: `cli/_bind/` + `events/` except-Exception 分類掃描〔R9〕**

**Goal:** 對 `cli/_bind/`（25 個站點，Playwright 憑證綁定流程）與 `events/`（22 個站點，僅 1 個已追蹤）套用同樣的分類方法論，並確保任何例外訊息內容的變動不會讓憑證/session 資料外洩到未經清洗的輸出通道。

**Dependencies:** D1（沿用同一套已收斂的 exception 類別基礎；與 D2 可平行執行，檔案不重疊）。

**Files:**
- Modify: `cli/_bind/`（4 個檔案，25 個站點）：`_driver_impl.py`(9)、`recipes/medium.py`(7)、`recipes/velog.py`(5)、`chrome_backend.py`(4)
- Modify: `events/`（5 個檔案，22 個站點，`reconciler.py` 的其中 1 筆已有既有 debt 追蹤，本次補齊其餘 21 個）：`reconcile.py`(7)、`reconciler.py`(7，含已追蹤的 1 筆)、`_project_helpers.py`(3)、`publish_writer.py`(3)、`projector.py`(2)
- Modify: `debt_registry.toml`
- Modify: `cli/_bind/chrome_backend.py`（第 60 行，見 Approach 步驟 4 的既存契約違規修復）
- Modify: `cli/admin/bind_channel.py`（`main()` 內 126-134 行的 `except PipelineError` 與 137-143 行的 `except Exception` 兩處 catch-all，見 Approach 步驟 5，doc-review security-lens 複核發現）
- Test: 對應模組的既有測試 + 高風險站點的紅色路徑測試

**Approach:**
1. `cli/_bind/` 屬於憑證/認證相關流程，敏感度比照已審查過的 `webui_app/api/`——分類時特別留意任何可能讓認證失敗被誤判為「綁定成功」的站點；套用 K8 的四步判斷。
2. `events/` 是狀態投影層，21 個未追蹤站點中若有任何一個涉及事件分類/派發（與已知三案「接縫靜默丟失」bug 家族同型），套用 K5 的嚴格審視框架與 K8 的判斷順序。
3. 沿用 D2 相同的 debt_registry 分類與註解慣例，包含批次送 PR 與同理由聚類的慣例。
4. **〔deepening 新增，security review 發現〕`cli/_bind/` 目前偏向「失敗即安全」（例：`recipes/velog.py` 106/114/127 行例外時 `authed` 留在 `False`，輪詢迴圈自然繼續等待；`_driver_impl.py`／`chrome_backend.py` 的 `bound_predicate` 例外只用於執行清理，之後仍會 re-raise）——本 unit 的分類與任何修復都必須保留這個 fail-closed 語意，不能把「繼續等待」的預設改成「宣告已綁定」。任何觸碰這些站點的修改需附紅色路徑測試證明「掃描/cookie 讀取時發生例外，結果仍是『尚未綁定』」。同時修復/標記 `chrome_backend.py:60` 的既存契約違規：`raise ChromeLaunchError(str(exc)) from exc` 把任意例外文字塞進本應是封閉列舉的 `error_code` 欄位（`webui_app/services/bind_job.py` 用 `BIND_ERROR_MESSAGES.get(error_code, ...)` 做字典查找）——改為使用既有列舉碼，例外文字另外放在不會被當作列舉值解讀的欄位。任何新增的例外文字（尤其 `_driver_impl.py:232` 的 `storage_state` 持久化失敗訊息，其失敗模式若源自序列化/`repr()` 可能夾帶真實 cookie/session token 值）在放進 `_emit()` payload、debt_registry rationale 或任何 log 之前，一律先過 `events/scrubber.py::scrub_text()`（`cli/_bind/` 目前完全沒有使用這個既有機制，儘管 `events/_project_reducers.py` 已在用）。**`debt_registry.toml` 的 rationale 是人工撰寫的 TOML 文字，`scrub_text()` 是一個作用在程式碼呼叫點的 runtime 函式，兩者不是同一種防護——撰寫 rationale 時禁止直接貼上或引用觀察到的原始例外文字，一律改寫成描述性文字（例如「storage_state 序列化失敗時例外訊息可能包含 repr() 化的 cookie 值」而非貼上實際錯誤字串），因為 `scrub_text()` 無法保護人工輸入的 prose。**
5. **〔deepening doc-review 新增，security-lens 複核發現〕`cli/admin/bind_channel.py::main()` 是 `run_bind()` 呼叫的既存 catch-all 出口——126-134 行的 `except PipelineError` 與 137-143 行的 `except Exception` 兩處都用 `driver._emit(\"channel.bind.failed\", ..., message=str(exc))` 把原始例外文字直接寫進 stdout JSONL，這正是 `_emit()` → `bind_job.py` poll API 未過濾直通鏈的實際出口，任何跳脫 `run_bind()` 五種既列舉例外類型的例外（例如 `chrome_backend.py:311`『`_CdpClient.send()`』的 `RuntimeError`）都會落到這裡。這兩處必須套用與 `_driver_impl.py:232` 同等的 `scrub_text()` 清洗要求，不能因為它們在 `cli/admin/` 而非 `cli/_bind/` 目錄下就被本 unit 遺漏。

**Patterns to follow:** `events/scrubber.py::scrub_text()`（`events/_project_reducers.py:316,424` 既有呼叫點）是這個資料類別（憑證相關錯誤文字）的既有清洗機制，D3 應該沿用而非新建；`_util/logger.py` 的 `_SENSITIVE_KEYS`/`_redact_in_place` 是另一層既有防護，但只保護走 `PipelineLogger` 的呼叫，`_driver_impl.py::_emit()` 是獨立的 stdout writer，不會自動套用，需要在 D3 站點層級明確處理。

**Test scenarios:**
- Happy path：新增的 debt 項目通過 schema 驗證。
- 紅色路徑：對 `cli/_bind/` 中任何判定為「認證失敗可能被誤判成功」的站點，新增測試證明目前行為（先紅），若本 unit 內修復則證明修復後正確拋出/分類（後綠）。
- 紅色路徑（security）：對 `recipes/medium.py` 191-219 行、490-493 行與 `recipes/velog.py` 對應站點，新增測試證明「掃描/cookie 讀取拋出例外」時最終判定仍是「未綁定」（防止本 unit 的重分類意外把 fail-closed 改成 fail-open）。
- 紅色路徑（security）：`chrome_backend.py:60` 修復後，故意觸發一個非預期例外，驗證 `error_code` 欄位只會是既有列舉值之一，例外原始文字不會出現在 `error_code`。
- Edge case（security）：模擬 `_driver_impl.py:232` 的 `storage_state` 持久化因序列化錯誤失敗且例外訊息包含類似 cookie value 的內容，驗證最終寫入 `_emit()` payload／debt rationale 的文字已經過 `scrub_text()` 清洗，不含原始敏感值。
- 紅色路徑（security，doc-review 新增）：`cli/admin/bind_channel.py::main()` 中模擬 `run_bind()` 拋出一個五種既列舉例外類型之外的例外（例如 `chrome_backend.py:311` 的 `RuntimeError`），驗證最終 `channel.bind.failed` 事件的 `message` 欄位已經過 `scrub_text()` 清洗。
- Integration：`events/` 中若有站點涉及事件分類，驗證其與既有三態分類器（若適用）或明確的錯誤傳播路徑整合正確。

**Verification:** `debt_registry.toml` 新增項目全數通過格式測試；`cli/_bind/`、`events/` 與 `cli/admin/bind_channel.py` 的 except-Exception／catch-all 站點數與新增分類數一致；`events/reconciler.py` 既有的 1 筆追蹤不受影響；`chrome_backend.py:60` 的 `error_code` 契約違規已修復或明確記錄為 debt；抽樣人工複核 3-5 個修改過的站點，確認沒有任何未清洗的例外文字流向 `webui_app/services/bind_job.py` 的 poll API 回應（含 `bind_channel.py` 的兩個 catch-all 出口）。

---

### Sprint E — 測試基準與效能熱點（唯讀量測 + benchmark 補齊）

- [ ] **E1: main 既存失敗測試獨立唯讀量測與根因分群〔R10〕**

**Goal:** 獨立、唯讀地重新量測 main 上的既存失敗測試數量與構成，套用 `docs/solutions/test-failures/` 五篇文件記錄的分群方法論，產出一份審查用的稽核報告，不修改任何測試或原始碼。

**Dependencies:** 無（但執行前務必確認 reconcile 計畫狀態，避免在即將被覆蓋的 `main` 歷史上量測，見 Concurrent Plan Coordination；K1）。

**Files:**
- Create: `docs/audits/2026-07-0X-existing-test-failure-baseline.md`（唯讀量測報告，比照既有 `docs/audits/2026-07-02-u1-residual-failures.md` 的格式）

**Approach:**
1. 在乾淨的 `main`（或協調後的基準 SHA）上執行兩種模式並分別記錄：(a) `PYTHONPATH=src pytest tests/ -m "unit"`（xdist 關閉，無 rerun）用於曝露 flaky／順序敏感的失敗；(b) 比照 `.github/workflows/ci.yml` 實際使用的 `-n auto -m "unit and not seam" --reruns 2 --reruns-delay 1` 重跑一次，作為與 CI 可比較的數字。〔doc-review 新增，adversarial 複核發現〕xdist 平行執行會改變 worker 間的測試隔離邊界，`--reruns` 會遮蔽暫時性失敗——這兩者都是本文件自己列舉的測試污染根因家族（session-scoped fixture 污染等）敏感的變因，只跑模式 (a) 得到的數字不能直接拿來跟 CI 或 v0.6.0 U1 的數字比較，報告需分別記錄兩種模式的結果，而不是只跑一種就宣稱「與 CI 基準比對」。
2. 套用五篇測試污染/假綠文件各自的稽核配方：`rg 'assert .+ not in'` 負面斷言稽核、`del os.environ` 模式掃描、`stderr == ""` 斷言掃描，判斷有多少殘餘失敗可歸類到已知根因家族。
3. 交叉比對 v0.6.0 U1 分支（`fix/u1-test-suite-triage`）記錄的 90 個殘餘失敗清單（`docs/audits/2026-07-02-u1-residual-failures.md`），標註哪些是本次獨立量測也觀察到的、哪些是新出現或已消失的。
4. 產出報告，不修改任何測試或原始碼檔案。

**Test expectation:** none -- 純唯讀量測與報告產出，無程式碼變更，正確性由報告內容的可重現性（記錄的 pytest 指令與 SHA）體現。

**Verification:** 報告存在且包含可重現的量測指令與基準 SHA；報告明確標註與 v0.6.0 U1 既有殘餘清單的差異對照。

---

- [ ] **E2: 效能熱點 benchmark 補齊〔R11〕**

**Goal:** 為 `webui_store/history.py`（全檔案 load+save 型態）、`campaign_store.py`、`batch_ops.py`、`publishing/adapters/link_attr_verifier.py`（巢狀迴圈 + 多次全文 regex）新增 benchmark，建立效能基準線。

**Dependencies:** 無。

**Files:**
- Modify: `tests/test_benchmarks.py`（或新增 `tests/test_benchmarks_store.py` 若現有檔案已接近其 SLOC ceiling，執行時確認）

**Approach:**
1. 比照現有 4 個 benchmark 案例（100 列批次、單列延遲、JSONL 序列化）的型態，為每個熱點新增至少一個代表性 benchmark（例如 `history.py` 的 100 筆歷史紀錄下單筆 `update_item` 延遲；`link_attr_verifier.py` 的單次驗證在中等長度內容下的延遲）。
2. 使用既有的 `pytest-benchmark` 依賴，不引入新的 benchmark 框架。
3. 本 unit 只建立基準線，不對這些路徑做任何效能優化——若 benchmark 結果顯示明顯的效能懸崖，記錄在報告/PR 說明中供未來迭代參考，不在本 unit 內處理（K7）。

**Test scenarios:**
- Happy path：新增的 benchmark 可執行並產出穩定可重現的計時結果（重複執行 3 次波動在合理範圍內）。
- Edge case：`history.py` 的 benchmark 涵蓋「小型歷史檔案」與「較大歷史檔案（例如 1000 筆紀錄）」兩種情境，驗證 O(n) 行為是否如預期隨檔案大小增長。

**Verification:** `pytest tests/test_benchmarks.py --benchmark-only` 執行成功並產出全部新增熱點的計時數據；CI 的 benchmark diff gate（若適用）不因新增案例而誤觸發（新案例首次執行沒有歷史基準可比較，需確認 gate 邏輯正確處理首次執行情境）。

---

- [ ] **E3: LITE 延後決策觸發條件驗證〔R12〕**

**Goal:** 驗證 `docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md` 記錄的 3 個延後決策（R7 跨行程 rehydrate、R8 Pydantic 非權威驗證、R10 無 per-probe timeout）的恢復觸發條件是否已因近期 scheduler/keepalive/recheck 相關開發而成立。

**Dependencies:** 無。

**Files:**
- Create: `docs/audits/2026-07-0X-lite-deferral-trigger-check.md`（唯讀驗證報告）

**Approach:**
1. 逐一對照三個觸發條件的原始文字與目前程式碼/計畫現況：是否已引入「無人值守/排程 recheck」（R7/R10 觸發條件）；是否已出現第三次 schema drift 或新 publish-payload 欄位未過 `schema.py` 閘門（R8 觸發條件）。
2. 若任一觸發條件已成立，在報告中明確標註並建議另開獨立追蹤計畫（不在本 unit 內實作修復，見 Scope Boundaries）。
3. 若皆未成立，報告記錄「仍維持延後」的結論與下次應該重新檢查的時機或事件。

**Test expectation:** none -- 純唯讀文件對照與程式碼現況檢查，無程式碼變更。

**Verification:** 報告存在，對三個觸發條件皆有明確的「已成立/未成立」結論與依據。

## System-Wide Impact

- **Interaction graph:** A1 影響所有依賴 `webui_store` 單例重設語意的測試（`tests/conftest.py` 的 `_refresh_paths()` 呼叫鏈）；D1–D3 影響 adapter/`_bind`/`events` 的例外傳播路徑，需確認上層呼叫者（`publish_backlinks` 引擎、CLI 綁定流程）對例外類型的假設不受影響。
- **Error propagation:** D2/D3 的分類結果若判定某站點需要修復（而非僅記錄），修復後的例外必須仍能被上層既有的 `PipelineError` 階層或 `_util/error_envelope.py` 正確捕捉與呈現，不能引入新的未捕捉例外類型導致 CLI/WebUI 崩潰。
- **State lifecycle risks:** A1 的 `_refresh_paths()` 修復直接影響測試隔離正確性——若修復不完整，可能反而讓現有測試套件出現新的跨測試污染（需在紅色路徑測試中明確驗證修復前後的行為差異）。
- **API surface parity:** 本計畫不涉及任何對外 API 變更；E2 的 benchmark 新增與 B1/B2 的 TOML 調整皆為內部治理，無外部契約影響。
- **Integration coverage:** D2/D3 對「疑似接縫靜默丟失」站點的紅色路徑測試是本計畫最重要的整合層驗證——單元測試無法證明「例外是否在正確的層級被正確分類」，需要端到端模擬失敗情境的測試。
- **〔deepening 新增，security review〕未清洗的憑證資料傳遞鏈：** `cli/_bind` → stdout JSONL（`_driver_impl.py::_emit()`）→ `webui_app/services/bind_job.py::BindJob.events`（`_drain_stdout` 逐行 append，無過濾）→ poll API（`list(job.events)` 原樣回傳）是一條從 subprocess stdout 到瀏覽器回應完全未過濾的直通管道。D3 在任何 `_emit(...)` payload 新增或修改的欄位，只要可能帶有例外文字或回應內容，都必須經過 `scrub_text()` 清洗或直接省略，不能以自由文字形式新增。
- **〔deepening 新增，security review〕`_emit()` 位於既有 redaction chokepoint 之外：** `_util/logger._SENSITIVE_KEYS` 的自動遮蔽只保護走 `PipelineLogger` 的結構化日誌，`_driver_impl.py::_emit()` 是刻意獨立於此之外的 stdout JSONL writer（設計上 stdout 需保持乾淨的機器可讀格式）——D3 對 `_emit()` 呼叫點的任何修改都得不到這層保護，需要在站點層級自行處理。
- **Unchanged invariants:** `_PUBLISH_LOCK`、adapter registry 的 `register()` 介面、`debt_registry.toml` 的 schema 本身、既有的 `# debt: <slug>` 註解慣例——本計畫延伸使用既有機制，不變更其定義。

## Risks & Dependencies

| Risk | Mitigation |
|---|---|
| Reconcile 計畫（2026-07-06-001）仍在進行時，本計畫的分支基於即將被覆蓋的 `main` 歷史 | 每個 unit 開工前查一次 reconcile 計畫狀態；若未完成，等待或從協調後的基準切分支 |
| B2 天花板調升與 v0.6.0 計畫的同檔案修改衝突 | 執行前查詢 v0.6.0 對應 unit 進度，見 Concurrent Plan Coordination；必要時協調由哪一方先調升 |
| D2/D3 的分類工作量被低估（56+25+22=103 個站點逐一審視是相當大的工作量，deepening 複核已將 D2 的快照數字 78 更正為 56） | 允許分批處理，每批次的 debt_registry 新增可以是獨立、可各自合併的 PR，不要求一次涵蓋全部 103 個站點才算完成；優先處理 K5 標記的高風險站點；`debt_registry.toml` 支援同理由聚類，實際 entry 數可遠少於站點數 |
| E1 的量測結果與 v0.6.0 U1 分支的 90 個殘餘產生矛盾（例如本計畫量測到的失敗數遠高於或低於 90） | 報告中明確記錄兩次量測的時間點、SHA、環境差異（Windows vs CI ubuntu-latest，以及 xdist/rerun 執行模式差異——見 E1 Approach 步驟 1 的雙模式量測），不試圖強行調和兩個數字，留給後續判斷 |
| 修復 D2/D3 中判定為「高風險」的站點時引入回歸 | 每個修復都要求先寫紅色路徑測試證明問題存在，修復後綠燈；不修復本 unit 範圍外可處理的站點,直接記錄為 `open` debt 留待專門的追蹤項 |
| Vulture 60% 信心門檻下的發現數已成長 59%（343→545），A3 只修復 gate 本身，不處理背後的發現量成長 | 在 A3 的 Verification 中記錄發現數是否需要重新校準門檻,若判斷需要則明確記錄為後續追蹤項,不在本 unit 範圍內展開 |
| 〔deepening 新增，security review〕D3 變動 `cli/_bind/` 例外訊息內容時，可能讓憑證/session token 資料經由既有的未過濾 stdout→WebUI 通道（`_driver_impl.py::_emit()` → `bind_job.py` poll API）外洩給操作者瀏覽器 | 任何新增/修改的例外文字一律先過 `events/scrubber.py::scrub_text()`；優先考慮用既有列舉 `error_code` 而非新增自由文字 `detail`/`message` 欄位；見 D3 Approach 步驟 4 |
| 〔deepening 新增，security review〕`_driver_impl.py:232` 的 `storage_state` 持久化失敗訊息，若失敗模式源自序列化/`repr()`，可能在例外文字中夾帶真實 cookie/session token 值 | D3 明確要求此站點的例外文字經 `scrub_text()` 清洗後才能進入 `_emit()` payload 或 `debt_registry.toml` rationale，見 D3 Test scenarios 的 edge case |
| 〔deepening 新增，security review〕D3 重新分類 `cli/_bind/` 例外時，若不慎把現有的 fail-closed（例外時視為「未綁定」）語意改成 fail-open（誤判為「已綁定」），會是比一般邏輯錯誤更嚴重的安全信任問題 | D3 對每個觸碰到的 `cli/_bind/` 站點要求紅色路徑測試證明「例外時仍判定未綁定」；見 D3 Test scenarios |
| 〔deepening 新增，security review〕`chrome_backend.py:60` 已存在的契約違規（`str(exc)` 被塞進本應是封閉列舉的 `error_code` 欄位，未經清洗直接顯示給操作者）與 D3 範圍重疊 | D3 明確修復或至少記錄此站點為 debt，不讓新站點重蹈覆轍；見 D3 Approach 步驟 4 |

## Documentation / Operational Notes

- **`STEWARDSHIP.md` 治理責任人指派**：11 個治理領域自 2026-06-04 起全部 `[unassigned]`，其中「WebUI store SQLite」與「Platform adapter registry」恰好是本計畫發現最多缺口的兩個領域。建議使用者指派責任人並啟動文件記錄的季度輪替機制，但這是組織決策，不在本計畫的實作單元內處理。
- **`debt_registry.toml` 治理慣例落差**：commit `f835820e`（2026-07-03）刪除了 10 筆已解決的債務項目，而非依 schema 文件的說明保留並標記 `resolved_date`。這是低嚴重度的治理一致性落差（git 歷史仍保留完整記錄），值得未來的 debt registry 維護提醒說明，但不構成需要修復的功能性缺陷,故不列為本計畫的實作單元。
- **B1/B2 落地後**，建議在下一次 `docs/optimization-history.md` 更新時，將本計畫收斂為新的一個 Phase 條目，延續既有的歷史記錄慣例。

## Sources & References

- Repo research: 本次審查的兩個平行研究 agent（repo-optimization-surface scan、docs/solutions institutional-learnings sweep）產出的即時發現，未另存獨立文件，證據已內嵌於本計畫各 unit。
- 相關 solutions 文件：`docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md`、`docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift-2026-05-26.md`、`docs/solutions/logic-errors/2026-06-05-001-live-dofollow-undercounting-triple-gap.md`、`docs/solutions/correctness/adapter-silent-exceptions-resolution.md`、`docs/solutions/ux-honesty/webui-false-success-resolution.md`、`docs/solutions/test-failures/`（五篇）、`docs/solutions/architecture-health-audit-2026-06-01.md`、`docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md`、`docs/solutions/workflow-issues/salvage-unmerged-work-from-dirty-behind-main-tree-2026-05-26.md`、`docs/solutions/best-practices/sweep-tasks-run-pytest-before-planning-2026-05-18.md`
- 相關既有計畫：[docs/plans/2026-06-30-001-opt-phase3-post-v050-iteration-plan.md](2026-06-30-001-opt-phase3-post-v050-iteration-plan.md)、[docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md](2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md)、[docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md](2026-07-03-001-fix-windows-webui-encoding-crash-plan.md)、[docs/plans/2026-07-06-001-refactor-reconcile-github-gitlab-main-plan.md](2026-07-06-001-refactor-reconcile-github-gitlab-main-plan.md)
- `debt_registry.toml`（schema 定義於檔案開頭）、`monolith_budget.toml`、`complexity_budget.toml`、`STEWARDSHIP.md`
