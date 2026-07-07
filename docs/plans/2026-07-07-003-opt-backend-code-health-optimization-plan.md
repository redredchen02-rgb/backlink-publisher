---
title: "opt: 後端程式碼健康與技術債收斂計畫"
type: optimization
status: completed
date: 2026-07-07
priority: medium
claims: {}
---

# opt: 後端程式碼健康與技術債收斂計畫

## Overview

使用者要求「分析專案狀況進行全面優化」,並在釐清範圍時選擇「先做全專案健康檢查再決定」。本計畫是那次健康檢查(三路並行研究:repo 架構/複雜度掃描、`docs/solutions/` 制度性教訓、即時 git/plan/測試現況快照)之後的產出。

**與既有三份 active 計畫的關係是互補,不是重疊**:
- `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md` — 認領 UI/UX SPA 遷移 + per-platform-lane 平行發佈引擎。
- `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` — 認領 WebUI 元件體系、破壞性操作安全、表單保護、a11y。
- `docs/plans/2026-07-07-002-fix-production-wsgi-entrypoint-plan.md` — 認領 WSGI 生產部署入口點。

三者都聚焦前端/WebUI 層或發佈管線的功能面。健康檢查發現的真正缺口在**後端程式碼品質與技術債治理**——複雜度熱點、adapter 可靠性模式、debt registry 時效性、測試隔離脆弱性——這些沒有被任何 active 計畫認領,是本計畫的範圍。

**⚠️ 併發修改警示(本 repo 已多次證實的教訓)**:`docs/solutions/` 記錄過至少兩次「同一 workspace 多 session 同時操作、無 worktree 隔離」事件,其中一次導致未提交的 merge 衝突解決工作被外部動作整組清空。本計畫任何 unit 開工前,先 `git -C backlink-publisher status --short` + `git -C backlink-publisher worktree list` 確認乾淨且無其他 session 活躍痕跡;所有具體數字(SLOC、複雜度分數、測試通過數)都是 2026-07-07 健康檢查快照,執行前務必即時重新量測。

## Problem Frame

三路健康檢查(repo 架構分析、institutional learnings 掃描、即時 git/plan/test 快照)發現以下未被認領的後端缺口:

1. **複雜度熱點**:radon 顯示整體平均健康(A, 4.43),但 4 個函式落在 D 級:`_dispatch_router/routing.py::route`(D28,全庫最差)、`_util/http_probe.py::_triage`(D23)、`scorecard/engine.py::build_channel_scorecard`(D22)、`scorecard/reliability_readiness.py::channel_readiness`(D21)。`complexity_budget.toml` 對這些檔案的 ceiling 是否已經逼近或超標,需要重新量測確認。
2. **Adapter 可靠性模式重現**:`docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 記錄過 `linkedin_api.py`、`medium_browser.py` 的裸 `except Exception` 吞錯模式;即時掃描確認這兩個檔案仍有多處(`medium_browser.py` 9 處,`linkedin_api.py` 1 處),部分帶 `as exc`/`as e` 但需確認是否有記錄或僅靜默吞掉。
3. **Debt registry 時效性未知**:`debt_registry.toml` 58 個項目中 43 個(74%)標記 `accepted`、僅 2 個 `open`、0 個 `mitigated`——高比例的「已接受」可能代表真實已無害,也可能代表從未回頭覆核。2026-06-01 的架構健康稽核(`docs/solutions/architecture-health-audit-2026-06-01.md`)已經 5 週未更新,且其後有一整輪 fleet-merge 落地,結論(尤其 `lease_management.py` 死碼標記)需要重新核實而非直接沿用。
4. **Retired adapter 未決**:`hashnode`、`writeas` 兩個 adapter 在 registry 中標記 `visibility="retired"` 但仍完整註冊、佔用 import 與 registry 空間——目前不清楚這是刻意保留(例如未來復活或保留歷史紀錄)還是遺留待清理。
5. **測試隔離脆弱性重現模式**:`docs/solutions/test-failures/` 下三份文件都指向同一根因類型——fixture teardown 期間對 `os.environ` 的操作(如 `del os.environ[...]`)會毒害同 session 內其他測試,且只在完整套件跑序下重現。這是重複出現的根因類別,而非單一已修復的意外。
6. **Import-linter 邊界未即時驗證**:repo 架構掃描時因 venv 選取錯誤而無法跑出即時 `lint-imports` 結果;`pyproject.toml` 中已知的 `ignore_imports` 例外(`publishing.adapters.instant_web → cli._bind.chrome_backend`、`sdk.* → cli.*`、`keepalive.chain → sdk.api`)是否仍是唯一的邊界違規,需要一次乾淨環境下的即時驗證。

## Requirements Trace

- R1. 重新核實 2026-06-01 架構健康稽核在 fleet-merge 後是否仍然成立(便宜的核實優先於昂貴的重新稽核)。
- R2. 對 `debt_registry.toml` 中標記 `accepted` 的項目做時效性抽查,標出「仍然有效」vs「應該重新開啟」的項目。
- R3. 消除 `linkedin_api.py`、`medium_browser.py` 中會靜默吞錯、不留可觀測痕跡的 except 區塊。
- R4. 對 `hashnode`、`writeas` 的 retired 狀態做出明確決策並記錄理由(保留 vs 移除 vs 轉為輕量 stub)。
- R5. 將 4 個 D 級複雜度熱點降到 `complexity_budget.toml` 綠燈範圍內,且不改變既有行為(需回歸測試覆蓋)。
- R6. 為「env-var teardown 毒害同套件測試」這一類根因新增結構性防護(而非逐一修補已知案例)。
- R7. 取得一次乾淨的 import-linter 即時驗證結果,確認邊界違規清單與 `pyproject.toml` 中的 `ignore_imports` 完全一致。

## Scope Boundaries

- 不涉及 UI/UX、SPA 元件、前端路由——這些屬於 2026-07-02-001 與 2026-07-06-005。
- 不涉及 WSGI/部署拓撲——屬於 2026-07-07-002。
- 不涉及新 adapter 開發或新渠道評估(如需要,使用 `channel-probe` skill 走獨立流程)。
- 不對 `dofollow="uncertain"` 的 canary 佇列(wordpresscom、substack、hatena 等)做業務判斷——那是內容/業務決策,不是程式碼健康問題。
- 不引入新的 lint/CI 工具鏈——沿用既有 ruff/mypy/radon/import-linter/mutmut 工具組。

### Deferred to Separate Tasks

- `bp-w8-shell` worktree 的髒樹(`Icon.vue`、`SideNav.vue`、`TopBar.vue`、`navItems.ts` 未提交修改)——這是另一個 session 的進行中工作(`feat/w8-spa-shell-upgrade`),不屬於本計畫,亦不應被本計畫觸碰。
- `bp-baseline-preref` 的 detached-HEAD 殘留 worktree 是否清理——需要使用者確認這不是有意保留的參考快照後才能刪除(worktree 刪除是難以逆轉的操作,見下方 Unit 7)。

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/publishing/adapters/__init__.py` — lazy registry,`register()` 強制要求 `dofollow=`,非 `True` 需要 `rationale=` ≥80 字元。
- `docs/solutions/workflow-issues/grep-dofollow-map-before-shipping-adapter-2026-05-20.md` — PR #108 教訓:adapter 測試全綠不代表業務正確,需要對照 `webui_app/binding_status.py` 的 `_DOFOLLOW_BY_CHANNEL`。
- `tests/conftest.py` — 既有 `__tier__` 分層機制與 4 個 autouse fixture(封鎖真實網路呼叫);test-isolation 修復應該延伸這個既有機制,而不是另起爐灶。
- `monolith_budget.toml` / `complexity_budget.toml` — SLOC/複雜度 ceiling,超標需要在同一 PR 內附 ≥80 字元 rationale 調高。

### Institutional Learnings

- `docs/solutions/architecture-health-audit-2026-06-01.md` — 上次全面稽核結論(3/4 誤報是刻意設計,1 個真死碼)。
- `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` — adapter 吞錯模式的既有修復案例,本計畫延續同一模式掃描其餘檔案。
- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`、`ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md`、`strict-markers-addopts-noop-conftest-module-load-2026-06-01.md` — 三份文件共同指向 fixture teardown 期間環境變數操作的隔離風險類別。
- `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md` — 目前基準:105 failed / 12648 passed / 57 skipped / 10 errors(2026-07-06,fleet-merge 後)。任何 unit 動工前應以此為對照組,而非零基準。
- `docs/solutions/developer-experience/per-worktree-venv-vs-pythonpath-2026-05-19.md` — `pip install -e` 綁定單一 worktree,跨 `bp-*/` worktree 測試可能悄悄跑到 canonical `backlink-publisher/src`,是本計畫 Unit 6 執行時需要注意的環境陷阱。

## Key Technical Decisions

- **審計優先於重寫**:Unit 1、2、4、7 都是「核實/決策」而非「大改」,因為 2026-06-01 稽核已經證明多數表面異常是刻意設計——先核實比先重構的 ROI 高,且避免重工。
- **複雜度重構不改行為**:Unit 5 的降複雜度以「拆函式、抽早退路徑」為主,明確排除任何邏輯變更;每個熱點函式重構前後跑既有測試作為行為不變的證據。
- **測試隔離修在機制層,不修在案例層**:Unit 6 針對「env-var teardown 毒害套件」這個根因類別新增一個結構性防護(例如 fixture 層的環境快照/還原斷言),而非逐一修補三份文件裡列出的具體測試。

## Open Questions

### Resolved During Planning

- 是否要涵蓋 UI/UX?否——三份既有 active 計畫已認領,本計畫刻意互補而非重疊。
- `lease_management.py` 是否仍是死碼待清?即時檢查確認該檔案已不存在(已被移除),Unit 1 只需在核實報告中記錄「已解決」,無需再處理。

### Deferred to Implementation

- Unit 2 的 debt registry 抽查可能發現某些 `accepted` 項目其實應該重新開啟為 `open`——具體要重開哪幾項需要看抽查結果,無法在規劃階段預先列出。
- Unit 4 的 hashnode/writeas 決策(保留/移除/轉 stub)需要先看 registry 裡 `visibility="retired"` 的既有使用意圖(是否有其他地方依賴這兩個 adapter class 的存在),規劃階段無法斷定。
- Unit 5 每個熱點函式的具體拆分方式(拆成幾個 helper、抽哪些早退路徑)留給實作階段,因為需要先讀懂函式的完整分支邏輯才能決定安全的切法。

## Implementation Units

- [x] **Unit 1: 核實 2026-06-01 架構健康稽核在 fleet-merge 後的現況**

**Goal:** 用最小成本確認上次稽核結論是否仍成立,避免重工,同時為後續 unit 建立乾淨的現況基準。

**Requirements:** R1, R7

**Dependencies:** None

**Files:**
- Create: `docs/audits/2026-07-07-architecture-health-reverify.md`
- Test: 不涉及新程式碼,無獨立測試檔案

**Approach:**
- 核對 `docs/solutions/architecture-health-audit-2026-06-01.md` 列出的 4 個疑點,逐項確認現況(`lease_management.py` 已確認不存在,標記已解決)。
- 在乾淨的 `backlink-publisher/.venv` 環境下跑一次 `lint-imports`,對照 `pyproject.toml` `[tool.importlinter]` 的 `ignore_imports` 清單,確認沒有新增的未列管違規。
- 確認 `webui_store` 共享與 `_report_engine` seam 是否仍是唯一使用者能辨識的意圖(cross-reference 目前 import 路徑)。

**Patterns to follow:**
- `docs/solutions/architecture-health-audit-2026-06-01.md` 的稽核格式與判定標準。

**Test scenarios:**
- Test expectation: none -- 純稽核文件產出,不涉及程式碼行為變更。

**Verification:**
- `docs/audits/2026-07-07-architecture-health-reverify.md` 對 2026-06-01 稽核的每一項疑點都有「仍然成立/已變化/已解決」的明確標註。
- `lint-imports` 的即時輸出附在稽核文件中,清單與 `pyproject.toml` 的 `ignore_imports` 逐條比對過。

---

- [x] **Unit 2: Debt registry 時效性抽查**

**Goal:** 對 `debt_registry.toml` 中 43 個 `accepted` 項目做時效性抽查,標出應維持、應重開、或可以正式關閉(轉 `resolved`)的項目。

**Requirements:** R2

**Dependencies:** Unit 1(用同一次乾淨環境核實)

**Files:**
- Modify: `debt_registry.toml`(僅對抽查後確認需要變更狀態的項目調整,不批量改動)
- Create: `docs/audits/2026-07-07-debt-registry-triage.md`

**Approach:**
- 對每個 `accepted` 項目讀取其 `(slug, location)`,對照目前程式碼確認該項目描述的狀況是否仍然真實存在。
- 分三類記錄:「仍然成立,維持 accepted」「狀況已消失,可轉 resolved 並附 claim」「狀況惡化或應重新評估,建議轉 open」。
- 對確認要變更狀態的項目才動 `debt_registry.toml`,並依照現有結構性檢查(D2b,`(slug, location)` 唯一性 + cross-reference)補上對應的 freshness claim 測試(若專案已有此機制,沿用;若尚未落地,只記錄在稽核文件中留給下個 unit 決定是否要補機制)。

**Test scenarios:**
- Happy path: 一個確認已解決的 `accepted` 項目轉為 `resolved` 後,對應的既有測試套件仍然通過。
- Edge case: 一個項目的 `location` 已經因為檔案搬遷而失效——記錄為「位置需更新」而非直接判定為已解決。

**Verification:**
- `docs/audits/2026-07-07-debt-registry-triage.md` 對 43 個 `accepted` 項目逐一有分類標註。
- 任何 `debt_registry.toml` 的實際修改都能對應到稽核文件中的具體理由。

---

- [x] **Unit 3: Adapter 吞錯模式掃描與修復**

**Goal:** 消除 `linkedin_api.py`、`medium_browser.py`(以及掃描發現的其他 adapter)中會靜默吞錯、無可觀測痕跡的 except 區塊。

**Requirements:** R3

**Dependencies:** None(可與 Unit 1/2 平行)

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/linkedin_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/medium_browser.py`
- Test: `tests/publishing/test_linkedin_api.py`(若不存在則於既有 adapter 測試目錄下建立對應檔案)
- Test: `tests/publishing/test_medium_browser.py`(同上)

**Approach:**
- 對照 `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 記錄的既有修復模式(用 `_util.errors` 的既有例外分類 + 結構化 log,而非新發明機制)。
- `medium_browser.py` 第 192 行 `except Exception:`(無 `as` 綁定、無日誌)是最明顯的靜默吞錯案例,優先處理。
- 其餘 `except Exception as exc/e` 案例逐一確認:是否有 `logger`/`structlog` 記錄?是否應該改為 `DependencyError`(讓下一個 adapter 接手)還是 `ExternalServiceError`(應該往上傳)?依照 CLAUDE.md 的例外分類原則(`DependencyError` fall-through,`ExternalServiceError` propagate)判斷。

**Patterns to follow:**
- `_util/errors.py` 的既有例外類別與 `retry_transient_call` 包裝模式。
- `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` 的具體修復手法。

**Test scenarios:**
- Happy path: adapter 正常發佈流程不受影響,既有成功案例測試維持綠燈。
- Error path: 模擬 medium_browser 內部呼叫拋出非預期例外,驗證現在會被記錄(而非靜默吞掉)且正確分類為 `DependencyError` 或 `ExternalServiceError`。
- Error path: 模擬 linkedin_api 呼叫失敗,驗證失敗會傳播到呼叫端而非被吞成「表面成功」。
- Integration: 一個因吞錯而過去測試也綠燈、但實際邏輯有缺陷的路徑(若稽核中發現)——新增測試證明修復後能捕捉到。

**Verification:**
- `grep -rn "except Exception" src/backlink_publisher/publishing/adapters/linkedin_api.py src/backlink_publisher/publishing/adapters/medium_browser.py` 顯示的每一處都有對應的記錄或明確的重新拋出/分類邏輯,不存在裸 `pass`。
- 既有 adapter 測試套件全綠,新增的錯誤路徑測試通過。

---

- [x] **Unit 4: Retired adapter(hashnode/writeas)處置決策**

**Goal:** 對 `hashnode`、`writeas` 的 `visibility="retired"` 狀態做出明確決策並落地。

**Requirements:** R4

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/__init__.py`(視決策調整,或僅補充註解說明保留理由)
- Modify: `docs/solutions/`(視決策新增一則記錄決策理由的文件)

**Approach:**
- 先搜尋 `visibility="retired"` 在 WebUI/CLI 端的實際處理邏輯(例如是否有地方依賴這個標記來隱藏但保留操作能力),判斷這是否是刻意設計的「保留但隱藏」模式。
- 若確認是刻意設計(例如未來可能復活、或保留歷史發佈記錄的解析能力),則不做程式碼變更,只在 `__init__.py` 補充一行說明性註解(僅在既有 `rationale` 之外缺乏「為何保留」的說明時才補)。
- 若確認純屬遺留、無任何依賴,則移除 `register()` 呼叫與對應 import,並確認 `catalog/` 或其他設定沒有懸空引用。

**Test scenarios:**
- Test expectation: none -- 若決策為「維持現狀,僅補充文件」則不涉及行為變更。
- 若決策為移除:Happy path — 移除後 adapter 註冊表不再出現這兩個 key,既有測試套件(尤其驗證 registry 完整性的測試)綠燈。
- 若決策為移除:Edge case — 確認沒有其他模組(WebUI 顯示、CLI 選單、catalog YAML)硬編碼引用這兩個渠道名稱而導致找不到 adapter 時的錯誤處理是否得當。

**Verification:**
- 決策(保留或移除)有書面理由記錄在 `docs/solutions/` 或計畫文件的稽核附錄中。
- 若移除,`pytest -k "adapter" -m unit` 全綠且沒有殘留的懸空引用。

---

- [x] **Unit 5: 複雜度熱點降複雜度**

**Goal:** 將 4 個 D 級複雜度函式重構到 `complexity_budget.toml` 的綠燈範圍,不改變既有行為。

**Requirements:** R5

**Dependencies:** Unit 3(部分 adapter 相關函式可能有交集,先完成 Unit 3 再動這裡的重構,避免衝突)

**Files:**
- Modify: `src/backlink_publisher/_dispatch_router/routing.py`
- Modify: `src/backlink_publisher/_util/http_probe.py`
- Modify: `src/backlink_publisher/scorecard/engine.py`
- Modify: `src/backlink_publisher/scorecard/reliability_readiness.py`
- Test: 對應既有測試檔案(先跑 `pytest --collect-only` 確認涵蓋這 4 個函式的既有測試位置,重構前先補齊行為快照測試若覆蓋不足)

**Execution note:** 重構前先確認每個函式有足夠的既有測試覆蓋其分支邏輯;覆蓋不足的函式先補充 characterization 測試,再動手拆分,避免在不知道原行為的情況下重構出回歸。

**Approach:**
- `routing.py::route`(D28,全庫最差)優先處理:多半是多條件分派邏輯,可抽成查表或早退 guard clause。
- `_util/http_probe.py::_triage`(D23)、`scorecard/engine.py::build_channel_scorecard`(D22)、`scorecard/reliability_readiness.py::channel_readiness`(D21)依序處理。
- 每個函式重構後立即跑 `radon cc -s -n C <file>` 確認等級降到 B 以下,並跑對應測試確認行為不變。
- 若重構後 SLOC 超過 `monolith_budget.toml` 的既有 ceiling,在同一 PR 內以 ≥80 字元 rationale 調整 ceiling。

**Technical design:** *(directional,非實作規格)*

> 以 `route` 為例:目前可能是一長串 `if/elif` 依 platform/mode 分派。方向性拆法是把「判斷用哪個 handler」與「呼叫 handler」分離——例如一個小型查表(dict 映射 dispatch key → handler 函式)取代長 `if/elif` 鏈,把每個分支的例外處理抽到共用 wrapper。這只是示意分派結構的方向,實際判斷邏輯與早退順序需依實作階段讀完整函式後決定。

**Patterns to follow:**
- 專案既有的複雜度重構案例(若 `docs/solutions/` 中有既往降複雜度的記錄,優先參考該手法而非另創風格)。

**Test scenarios:**
- Happy path: 每個函式重構前後,對相同輸入產生相同輸出(用既有測試或新增的 characterization 測試驗證)。
- Edge case: 每個函式原本處理的邊界分支(例如 `_triage` 的逾時/不可達分類、`channel_readiness` 的資料缺失分支)重構後仍走到相同的分類結果。
- Regression: 重構後跑一次相關模組的完整測試子集,確認沒有新增失敗。

**Verification:**
- `radon cc -s -n C` 對這 4 個函式回報 B 級或以上。
- `complexity_budget.toml` 中對應項目無需提高 ceiling,或提高時附完整 rationale。
- 相關測試子集(`pytest tests/ -k "routing or http_probe or scorecard"`)全綠。

---

- [x] **Unit 6: 測試隔離機制強化(env-var teardown 毒害套件)**

**Goal:** 針對「fixture teardown 期間操作 `os.environ` 毒害同套件其他測試」這一類根因,新增結構性防護,而非逐一修補案例。

**Requirements:** R6

**Dependencies:** None

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_env_isolation_guard.py`

**Execution note:** 這是為既有脆弱性類別補測試防護,建議先寫一個會在當前(未修復)狀態下失敗的 characterization 測試,證明問題類別真實存在,再實作防護機制。

**Approach:**
- 在 `tests/conftest.py` 的既有 autouse fixture 層級新增一個環境變數快照/還原斷言:每個測試結束後比對 `os.environ` 與測試開始前的快照,若發現未還原的變更且該測試沒有明確標記為允許此行為,則讓測試失敗並指出是哪個 key。
- 這個機制設計上要能同時抓到已知的三個案例類型(`del os.environ[...]`、直接賦值後未清理、monkeypatch 誤用而非用 `monkeypatch.setenv`),而不是只針對特定測試檔案打補丁。
- 需要確認這個防護不會與既有的 `PYTHONHASHSEED=0` 或其他刻意全域設定的環境變數衝突(需要一個允許清單機制)。

**Patterns to follow:**
- `tests/conftest.py` 既有的 `__tier__` AST 掃描機制風格(結構性檢查,非清單維護)。

**Test scenarios:**
- Happy path: 一個正常使用 `monkeypatch.setenv` 的測試不會觸發防護誤報。
- Error path: 一個刻意 `del os.environ["X"]` 而不清理的測試,能被防護機制捕捉並清楚報出是哪個測試、哪個 key。
- Edge case: 全域刻意設定的環境變數(如 `PYTHONHASHSEED`)在允許清單中,不會被誤判為洩漏。
- Integration: 對 `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md` 描述的具體案例跑一次完整套件驗證(而非單一測試),確認該案例現在會被機制捕捉而非要跑滿全套件才重現。

**Verification:**
- 新增的防護機制在乾淨 checkout 上跑通過(對正常測試無誤報)。
- 針對已知案例的 regression 測試能重現「修復前失敗、修復後通過」的對比證據。

---

- [x] **Unit 7: Workspace 衛生——dangling worktree 處置**

**Goal:** 對 `bp-baseline-preref` 這個 detached-HEAD 殘留 worktree 做出明確處置決策。

**Requirements:** (workspace hygiene,不對應功能性 R,但影響後續 unit 執行安全)

**Dependencies:** None,但應在其他 unit 之前先確認,避免誤判 workspace 狀態

**Files:**
- 無程式碼檔案變更;操作對象是 `bp-baseline-preref` worktree 目錄本身

**Approach:**
- **不要自動刪除**——依照 `docs/solutions/`(shared-directory 教訓)的教訓,worktree 刪除是難以逆轉操作,需先向使用者確認這不是有意保留的參考快照(其名稱與 commit `9d20754d`"close out bp-baseline-preref discard" 相關,暗示它可能已經是「處理完畢但未清乾淨」的殘留,而非仍在使用的參考)。
- 確認後執行 `git worktree remove bp-baseline-preref`(或使用者指定的替代動作)。

**Test scenarios:**
- Test expectation: none -- 純 workspace 清理操作,不涉及程式碼行為。

**Verification:**
- `git worktree list` 不再顯示 `bp-baseline-preref`,且清理前已取得使用者明確同意。

## System-Wide Impact

- **Interaction graph:** Unit 3(adapter 例外處理)與 Unit 5(部分複雜度重構若觸及 adapter 相關的 dispatch/routing 邏輯)有交集,已在依賴順序中處理。
- **Error propagation:** Unit 3 的修復直接影響 `DependencyError`/`ExternalServiceError` 在 adapter 鏈中的傳播行為,需要跨 adapter 驗證不會意外讓某個平台的失敗被錯誤分類而導致整條發佈鏈提前中止或錯誤地靜默跳過。
- **Integration coverage:** Unit 6 的防護機制需要在完整套件跑序下驗證(而非單一測試檔案),因為原始 bug 的重現條件就是「只在特定跑序下出現」。
- **Unchanged invariants:** 本計畫不改變 adapter registry 的 `register()` 介面契約、不改變 `dofollow=`/`rationale=` 的強制要求、不改變任何既有 CLI/WebUI 對外行為——所有變更都是內部實作層的健康強化。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 5 的複雜度重構在缺乏完整測試覆蓋下引入行為回歸 | Execution note 要求重構前先確認/補齊 characterization 測試 |
| Unit 2 的 debt registry 狀態變更誤判「已解決」而實際仍有問題 | 抽查決策附具體理由於稽核文件,可事後覆核 |
| Unit 6 的環境變數防護機制誤報,拖累無關測試 | 設計允許清單機制,並先在乾淨 checkout 驗證無誤報後才視為完成 |
| 執行期間其他 session 同時操作同一 workspace,覆蓋本計畫的變更 | 每個 unit 開工前檢查 `git status`/`worktree list`,遵循 workspace 已記錄的教訓 |
| Unit 7 誤刪使用者仍需要的參考 worktree | 明確要求使用者確認後才執行刪除,不自動化 |

## Sources & References

- Related plans: `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`, `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md`, `docs/plans/2026-07-07-002-fix-production-wsgi-entrypoint-plan.md`
- `docs/solutions/architecture-health-audit-2026-06-01.md`
- `docs/solutions/correctness/adapter-silent-exceptions-resolution.md`
- `docs/solutions/workflow-issues/grep-dofollow-map-before-shipping-adapter-2026-05-20.md`
- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
- `docs/solutions/test-failures/ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md`
- `docs/solutions/test-failures/strict-markers-addopts-noop-conftest-module-load-2026-06-01.md`
- `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md`
- `docs/solutions/developer-experience/per-worktree-venv-vs-pythonpath-2026-05-19.md`
