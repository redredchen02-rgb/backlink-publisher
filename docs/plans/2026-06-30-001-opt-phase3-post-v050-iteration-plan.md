---
title: "Optimization Phase 3: Post-v0.5.0 全面優化迭代計畫"
date: 2026-06-30
status: active
type: optimization
priority: high
origin: docs/brainstorms/2026-07-01-phase3-signal-integrity-hardening-requirements.md
deepened: 2026-07-01
claims:
  paths:
    - src/backlink_publisher/
    - webui_app/
    - webui_store/
    - frontend/
    - tests/
    - docs/
    - pyproject.toml
    - CI/*.yml
    - monolith_budget.toml
    - complexity_budget.toml
    - debt_registry.toml
  shas: []
---

# Optimization Phase 3: Post-v0.5.0 全面優化迭代計畫

## Overview（概覽）

v0.5.0 已正式發布，歷經 11 階段優化（P1–P11）+ 代碼解耦重構（Phase 2）。**⚠️ 這份文件裡幾乎每一個具體數字都已經被證實會過時**——2026-07-01 的 doc-review 用計畫自己指定的驗證指令重新量測，發現多處快照數字（SLOC、except 計數、測試檔案數）與即時查證已經有 20%–2500% 的落差（見下方各任務的「⚠️ 數字已過時」標註）。任何執行者在動手前都應該重新跑一次對應的量測指令，不要相信本文件裡的任何靜態數字。

| 指標 | 2026-06-30 快照 | 2026-07-01 部分即時查證 |
|------|------|------|
| Source files | 439 | — |
| Test files | 613 | 613（另有 ~151 個測試檔案 import 接縫模組，見 C1a） |
| Mypy errors | **0**（395 source files） | — |
| `# noqa: C901` | **0**（all CC < 30 backstop） | — |
| `__all__` | **43/43 子包已加** | — |
| Import-linter CI | ✅ enforced | — |
| Dependabot | ✅ pip weekly + GHA monthly | — |
| Docker prod build | ✅ multi-stage, no dev-deps | — |
| Performance benchmarks | ✅ 3 baselines | — |
| 未提交變更 | ⚠️ 174 files（+1106 / -2993） | **2026-07-01 深化再查證：28 files**（A1 原始 25 檔背景完全不變 + 本計畫文件自身 + origin 需求文件 + 一份不相關的並行計畫文件，見 A1 與「併發計畫交叉引用」）——Sprint A 核心積壓仍待處理 |

本計畫定位為 **v0.5.x 維護週期的最後一次集中優化迭代**，目標是在啟動 v0.6.0 功能開發前，將代碼庫推向「下一個穩定基線」。

**2026-07-01 修正（origin: `docs/brainstorms/2026-07-01-phase3-signal-integrity-hardening-requirements.md`）**：一份健檢型 brainstorm 指出，本計畫的驗收標準幾乎全是數量指標（except 計數、SLOC），但 `docs/solutions/` 記錄的實際案例顯示，這個專案最主要的重複性根因模式是「**訊號算對了，卻在子系統接縫被靜默丟掉**」——這不會被任何數量指標保證修好。修正案不重寫本計畫，而是針對 D1/D2/B3/E1/E2/A1 的驗收標準做精準修正，並新增 D2a（訊號往返驗證）、C1a（測試重跑範圍限定）、C1b（接縫層迴歸護欄）三個任務。

**2026-07-01 doc-review 修正（第二輪）**：四個 persona（coherence／feasibility／scope-guardian／adversarial）審查本文件後，發現 C1a 的手動檔名清單、C1b 的理由相似度檢查與固定行數窗口、D2 的驗證範圍，都有具體、可實測的缺陷（細節見各任務內文）。C1a 改為 import-based 自動判定；C1b 收斂為純 AST 掃描器；新增 **D2b** 任務取代原本失效的相似度檢查；D1/D2 的驗證範圍與數字都已修正。下方每個任務內文標有 **〔R#〕** 標記對應的修正案需求編號，完整對照見 Requirements Trace。

**⚠️ 併發修改警示（2026-07-01 深化查證，已從「懷疑」升級為「直接證實」）**：這個 repo 目前正被至少一個其他 session／工具同時操作。這不再只是推測——本次深化（deepening）過程中，短短十餘分鐘內親眼看到 git 狀態三次變化：dirty 檔案數從 30 → 27 → 28，`docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md` 從 untracked 變成已提交（commit `45b9b26e`），期間還多了一個 code-review 修正 commit（`bdd06db7`）。本文件記錄的所有具體數字（未提交檔案數、except 計數、SLOC、commit hash 等）僅供參考——執行任何任務前，務必先用即時指令重新查證，不能沿用本文件任何時間點的快照，包含這次深化查證的數字本身。

**2026-07-01 深化修正（併發計畫協調）**：深化查證發現 `docs/plans/` 裡同時存在兩份與 Phase 3 無關、但檔案範圍有重疊的獨立計畫文件，兩者都不由本計畫管理，但執行 Sprint A／B／D2／E2 時必須知道它們的存在——完整交叉引用見下方新增的「併發計畫交叉引用」小節。

---

## Requirements Trace

| 需求 | 內容摘要 | 對應任務 |
|------|------|----------|
| R1 | 接縫層裸 except 分類（理由+debt_registry，或 log+reraise） | D2 |
| R1a | 五個接縫模組各自需要訊號往返驗證測試 | D2a（新增） |
| R2 | D2 優先處理接縫層，含未提交檔案清單校準 | D2、A1 |
| R3 | SPA 假成功防護：三態驗證、正面規範（不假裝成功）、負面規範（部分失敗有獨立錯誤指示）、組合情境測試、自動化迴歸測試（無假成功斷言） | B3 |
| R4 | 大測試檔拆分時，shape-only 斷言強化為驗證數值 | D1 |
| R5 | 接縫層裸 except 迴歸護欄（CI 新建） | C1b（新增，第二輪收斂為純掃描器） |
| R6 | 死文檔歸檔清單補齊第 4 份報告 + 2 支殘留腳本 | E1 |
| R7 | AGENTS.md/CLAUDE.md 同步範圍擴大 | E2 |
| R8 | Sprint A1 數字重新校準（174→25） | A1 |
| R9 | pytest `--reruns` 範圍限定，接縫層測試排除 | C1a（新增，第二輪改為 import 自動判定） |
| （doc-review 新增） | debt_registry.toml 結構化防敷衍機制，取代失效的相似度檢查 | D2b（新增） |

## Philosophy（方針）

不同於 P1–P11 的「大刀闊斧」，Phase 3 遵循 **90/10 原則**：

- **90% 打磨**：提交積壓、補全遺漏、硬化現有機制
- **10% 新建**：只建那些能讓未來開發更安全的防護層（D2a、D2b、C1a、C1b 屬於這 10%）

> 「不要為了優化而優化——只優化那些能降低未來維護成本的東西。」

---

## Phase 3 架構

```
Phase 3 ─┬─ Sprint A: Workspace Hygiene（工作區清理）
          │   A1: 積壓提交 + 現況重新校準〔R2, R8〕
          │   A2: ci.yml canonical 化 ✅ 已完成
          │   A3: git worktree 協調（待重新確認）
          │
          ├─ Sprint B: Frontend Stabilization（前端穩定）
          │   B1: SPA route 完整性審計
          │   B2: API v1 ↔ Flask 路由雙覆蓋測試
          │   B3: SPA error boundary / loading state〔R3〕
          │
          ├─ Sprint C: CI/CD Hardening（持續整合強化）
          │   C1: CI 合規矩陣驗證
          │   C1a: pytest --reruns 範圍限定（import 自動判定）〔R9，新增〕
          │   C1b: 接縫層裸 except AST 掃描器（純掃描器）〔R5，新增〕
          │   C2: 性能基準趨勢 (benchmark diff gate)
          │   C3: SPA build / lint CI 集成
          │
          ├─ Sprint D: Code Debt Cleanup（代碼債務清理）
          │   D1: 大測試檔拆分〔R4〕
          │   D2: except Exception 窄化 + 接縫層分類〔R1, R2〕
          │   D2a: 訊號往返驗證〔R1a，新增〕
          │   D2b: debt_registry 結構化防敷衍機制〔新增〕
          │   D3: ko-corpus-calibration
          │
          └─ Sprint E: Documentation & Observability（文檔與可觀測性）
              E1: docs/ 目錄整理（死文檔歸檔）〔R6〕
              E2: AGENTS.md/CLAUDE.md 同步〔R7〕
              E3: 運行時健康檢查增強
```

---

## Sprint A: Workspace Hygiene

- [ ] **A1 — 積壓提交 + 現況重新校準〔R2, R8〕**

**現狀**：原始快照顯示 174 個文件有未提交改動；截至 2026-07-01 即時查證，工作區已降到 **25 個 dirty 檔案**（20 修改 + 5 新增），顯示這個任務已大部分完成。剩餘 25 個檔案分佈：
- 3 個非 `src/` 檔案：`.github/workflows/ci.yml`、`frontend/src/api/client.ts`、`pyproject.toml`
- 2 個 `webui_app/` 檔案：`__init__.py`、`helpers/contexts.py`
- 15 個 `src/backlink_publisher/` 檔案，其中 `events/reconciler.py`、`gap/events_gap.py` 已經做了機械式 except 窄化但**未分類**（見 D2）
- 5 個新的 `tests/test_webui_store_pkg/` 測試檔

**〔2026-07-01 深化再查證〕** 這 25 個檔案的組成在本次深化過程中（跨越約 15-20 分鐘、期間觀察到其他 session 至少 2 次 commit）維持完全不變——這是目前為止最強的訊號，證明這批積壓確實無人在動，可以放心排入本任務。但同時期工作區又多出 3 類新項目，**明確排除在本任務的分類/commit 範圍之外**：
- 本計畫文件自身（`docs/plans/2026-06-30-001-...`）——這是深化本身造成的修改，執行 A1 時應視為 Phase 3 文件維護的一部分，與 25 檔積壓分開處理
- `docs/brainstorms/2026-07-01-phase3-signal-integrity-hardening-requirements.md`（untracked）——本計畫的 origin 文件，建議與本計畫文件同批提交
- `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`（untracked）——**不屬於 Phase 3**，是另一份獨立、正在進行的計畫（見「併發計畫交叉引用」），不要誤併入本次 commit 批次
- 深化查證期間曾短暫觀察到 `SideNav.vue`／`TopBar.vue`／`useSidenavDrawer.ts` 等檔案處於 dirty 狀態，但在深化結束前已被另一 session 提交（commit `bdd06db7`）——執行 A1 時這些檔案應該已經乾淨，若仍是 dirty，代表狀態又變了，需要重新查證而非假設

**動作**：
1. 執行前務必用當下 `git status` 重新分類，不能沿用本文件任何時間點的具體數字（R8）——這份快照本身可能在你讀到時已經過時
2. 目前已窄化但未分類的 3 個接縫模組檔案（`events/reconciler.py`、`gap/events_gap.py`、`webui_app/helpers/contexts.py`），**必須先完成 D2 的分類程序才能 commit**（R2）——不能原樣提交後才回頭補分類
3. 其餘未提交檔案依原分類法（CI / frontend / src / tests / webui / misc）分批 commit，每批先跑 `pytest tests/ -x` 確保全過
4. **〔深化新增〕** commit 前先確認 `git status` 裡沒有意外混入不屬於這 25 檔背景的其他計畫產出（例如上述兩份不相關的計畫文件）——批次 commit 前逐檔案核對來源，而非整批 `git add`

**驗證**：`git status` clean，`pytest tests/ -x --tb=short` 全過，且已窄化的 3 個接縫檔案的 commit 訊息或 PR 描述包含明確分類理由

- [x] **A2 — ci.yml 工作空間根副本清理**（✅ 已驗證完成）

**現狀**：workspace root 目前沒有 `.github/` 目錄（已直接查證），canonical CI 在 `backlink-publisher/.github/workflows/ci.yml`。無需進一步動作。

- [x] **A3 — git worktree 協調**（✅ 狀態已確認，分支刪除待用戶執行）

**現狀**：**〔2026-07-02 執行期間再查證〕** `git branch -a` 重新確認：`opt/bulk-modernize`、`refactor/u5-publish-one-row-enhance-payload` 已清理（local+remote 均不存在）。`fix/drafts-store-test-isolation`、`fix/recheck-ledger-liveness-seam` **本地與遠端都仍在**——但透過 `git log --grep` 交叉比對 main 分支歷史，確認兩者內容都已透過 squash-merge 併入 main：`fix/recheck-ledger-liveness-seam`（tip `0b30cfaf`）已併入 main 的 `1ec41c76 (#31)`；`fix/drafts-store-test-isolation`（tip `5bc7327f`）已併入 main 的 `129d1490 (#42)`。`git merge-base --is-ancestor` 對兩者都回報 false，這是 squash-merge 的預期行為（commit hash 不同但內容已進 main），不代表尚未合併。`refactor/u1-generate-payload` 遠端分支仍在（local 已清理）。

目前所在分支 `fix/webui-theme-nav-layout-cleanup` 沒有設定 upstream（`git rev-parse @{u}` 報錯 no upstream configured），代表**從未推送到遠端**，也就沒有對應的 PR。`gh pr list` 因帳號被 GitHub 停權（`HTTP 403: account was suspended`）無法查證，但 no-upstream 這個事實本身已經足夠：這個分支目前是純本地、未開 PR 的工作分支，不是待清理的殘留分支，A3 不應碰它。

**動作結果**：
1. 已確認 `fix/drafts-store-test-isolation`、`fix/recheck-ledger-liveness-seam` 的內容已安全併入 main（squash-merge，PR #42／#31）——刪除兩者的 local+remote 分支在內容上是安全的
2. 因為刪除 remote 分支屬於「對共享狀態可見」的操作，透過 AskUserQuestion 徵求用戶確認是否執行刪除；60 秒無回應，依 git 安全協議（未經明確同意不執行破壞性/遠端可見操作）**不代為執行刪除**，只記錄查證結果，刪除動作留給用戶或未來一次明確授權的執行
3. `refactor/u1-generate-payload` 遠端殘留分支比照處理，同樣留待用戶決定
4. 確認 `fix/webui-theme-nav-layout-cleanup`（本任務目前所在分支）沒有 upstream、未開 PR，純本地工作分支，A3 未將其列入清理範圍

**驗證**：`git branch -a` 現況已記錄；`fix/webui-theme-nav-layout-cleanup` 狀態已確認為「純本地、未推送、未開 PR」而非誤判為待清理殘留；兩個確認可安全刪除的分支已列出但刪除動作待用戶授權（見 Risk Register 新增項）

---

## Sprint B: Frontend Stabilization

- [x] **B1 — SPA Route 完整性審計** ✅ 已完成（2026-07-02）

**現狀**：frontend/ 正在從 Flask Jinja templates 遷移到 Vue 3 SPA。**〔2026-07-01 深化查證，完整審計已完成，取代原本待辦的審計工作〕**：

- **既有基礎（來自已完成的 `docs/plans/2026-07-01-001-...`）**：所有 SPA 路由都渲染在同一個持久化 `AppShell` 內，不存在真正的「死角頁面」；13 個 navItems 全數 `isMigrated: true`（該檔案內「雙軌並存」的舊註解已過時，已於本任務更新——見動作 6）；`/campaign/:campaignId` 的側欄高亮缺口已由使用者決定明確延後，不是新發現，記錄為「已知、已接受的缺口」而非重新提報。
- **API 孤兒檢查（原動作 3）結果：零孤兒**——逐一核對 `frontend/src/api/*.ts` 每個呼叫點，全部能對應到 `webui_app/api/v1/*.py` 或 classic route 裡真實存在的 endpoint。
- **真正的缺口，B1 聚焦在這裡**：
  - **5 個 route 有完整 SPA 頁面 + 完整 API，但 Flask 端沒有導回 `/app/*` 的 redirect**：`/`（首頁精靈）、`/ce:history`、`/sites`、`/schedule`、`/batch-campaign`。對照組是另外 8 個已經正確 redirect 的 route（`/settings`、`/pr-queue`、`/survival-dashboard`、`/optimization-status`、`/ce:equity-ledger`、`/ce:keep-alive`、`/campaign/<id>`、`/monitor-hub`）——看起來是某一波遷移 sprint 補了 redirect，較早那波沒補。**〔2026-07-02 執行時深化查證，risk profile 比原始描述嚴重得多，詳見下方「B1 執行發現：5 個 redirect 並非等量風險」〕**：只有 `/schedule` 真正符合「低風險、機械式」的描述，已直接實作；其餘 4 個有具體、實測證據顯示會造成功能性退化或大規模既有測試斷裂，已改列為需要獨立後續 unit 的高風險項，**不**在 B1 內機械式補上。
  - **`/ce:health` 及其子路由（scorecard／publish-metrics／canary／forward-path／storage／GSC 面板）完全沒有 SPA 對應**——不是遺漏 redirect，是這個資料表面本身還沒被 SPA 消費，`/monitor` 頁面用的是 `command_center` 的聚合資料，不是 `health.py` 的資料，記錄為「未遷移」而非誤判為「已涵蓋」。**決策（見下方矩陣）**：維持 legacy-only，全量遷移延後到未來 sprint——這是一個豐富的維運面板（6 個子面板），完整遷移的工作量遠超一個穩定化 sprint 的合理範圍。
  - **〔深化修正，feasibility review 發現：不是死碼〕** `webui_app/routes/llm.py`、`webui_app/routes/image_gen.py` 兩個 blueprint 已被 deregister（見 `webui_app/routes/__init__.py` 註解），但程式碼註解明確記載這兩個檔案是刻意保留的**測試 patch 對象**（`llm.py` 供 `test_webui_unit3_security` patch；`image_gen.py` 保留 `http_client` import 供 image-gen lift-parity 測試 patch），不是無主死碼——直接刪除會讓這些測試壞掉。維持原狀，未觸碰。
  - `webui_app/routes/publish_defaults.py`（`/publish/defaults`、`/publish/quick`、`/publish/save-defaults`）在 `frontend/src/api/*.ts` 找不到任何呼叫者。**2026-07-02 查證結果（見下方矩陣）**：`/publish/defaults` 與 `/publish/quick` 並非孤兒——`webui_app/templates/sites.html` 的「快速發布」按鈕（`data-defaults-url`／`data-quick-url`）由 `webui_app/static/js/sites.js`（第 16–44 行，`data-action="quick-publish"` 委派監聽器）實際呼叫，是舊版原生 JS 頁面在用的真實路徑。但 `/publish/save-defaults` 在整個程式碼庫（`webui_app/`、`frontend/src/`、templates、static js）找不到任何呼叫者——docstring 聲稱「由 publish pipeline routes 呼叫」但實際不存在這個呼叫點，僅測試檔 `tests/test_webui_publish_defaults.py` 直接呼叫過。記錄為孤兒路由候選，不刪除，留待後續確認。

**B1 執行發現：5 個 redirect 並非等量風險**（2026-07-02，執行時的新發現，取代原本「5 個一起機械補上」的假設）：

逐一重新查證後，`/schedule` 與另外 4 個（`/`、`/ce:history`、`/sites`、`/batch-campaign`）的風險輪廓有本質差異：

| 檢查項 | `/schedule` | `/`（首頁） | `/ce:history` | `/sites` | `/batch-campaign`（GET） |
|---|---|---|---|---|---|
| 既有 GET 測試呼叫點數（`client.get(...)`）| 1 | 37 | 18 | 18 | 7 |
| 是否有 POST handler 用 flash query string 重導回本路徑 | 否 | 是——`checkpoint.py`（2 處）+ `drafts.py`（7 處）共 9 處 `redirect(f'/?flash_type=...&flash_msg=...')` / `?tab=draft&...` | 是——`history.py` 4 處 `redirect(f'/ce:history?flash_type=...&flash_msg=...')` | 是——`sites_save_three_url` 重導到 `/sites?saved=...&autofilled=...`（另一種、非 flash_type/flash_msg 的查詢參數契約）| 否（POST 成功重導到 `/campaign/<id>`，不是自身）|
| SPA 端是否已接住這個查詢參數契約 | N/A | **否**——`frontend/src/stores/notifications.ts` 已有 `pushFlash()` bridge 函式（明確為此設計），但整個 `frontend/src/` 沒有任何 `.vue`／router 呼叫點讀取 URL 的 `flash_msg`/`flash_type`，只有它自己的 spec 測試呼叫過——是個沒接線的死接口 | 同左（同一個 `pushFlash`，同樣沒接線）| **否**——`saved=`/`autofilled=` 這組參數在 `frontend/src/` 全域零匹配，連死接口都沒有 | N/A |
| 若直接補上無條件 redirect 的後果 | 無副作用 | 常見操作（刪除草稿、清空 checkpoint 等）成功後的成功／失敗提示會被靜默吞掉——**使用者可感知的功能退化**，不只是測試斷裂 | 同左（刪除歷史、批次刪除、清空失敗記錄等操作的提示）| 儲存三網址設定後的「已儲存」／「自動填入欄位」提示會被靜默吞掉 | 無 flash 退化，但 7 個既有測試斷言的是 legacy 頁面才有的內容（擴展區平台分區、過期管道渲染），SPA 端是否有對應的等效測試覆蓋未經確認 |
| 本次處理方式 | **直接實作**：沿用 7/8 現有 route 採用的「主路徑 redirect + `/<route>/jinja` 保留舊渲染」樣式，`/api/scheduled` 不受影響。更新 1 個既有測試呼叫點，新增 1 個 redirect 斷言測試 | **延後**，記錄為高風險缺口 | **延後**，記錄為高風險缺口 | **延後**，記錄為高風險缺口 | **延後**，記錄為中風險缺口（風險性質與前三者不同——測試覆蓋度問題，非功能退化）|

**這個發現本身也回答了原動作 2「評估風險」的要求**——原本動作清單第 2 項就已經要求「評估優先級與風險」而非無條件實作；本次執行證實這個風險評估動作是必要的，5 個路由裡有 4 個若機械式套用會造成真實的使用者可見退化（flash 提示消失）或大規模測試覆蓋流失，不是單純的「測試需要更新」而已。

**動作**：
1. 把上述缺口整理成正式的 SPA Route Audit Matrix（已遷移/未遷移/缺失/孤兒四類）——見下方「SPA Route Audit Matrix」
2. ✅ 已完成——5 個缺 redirect 的路由已逐一評估優先級與風險：`/schedule` 判定低風險並直接實作；`/`、`/ce:history`、`/sites`、`/batch-campaign` 判定為高／中風險，理由與證據見上表，延後至獨立後續 unit
3. ✅ 已決策——`/ce:health` 維持 legacy-only，不在本 sprint 遷移到 SPA（豐富維運面板，完整遷移工作量過大，明確延後而非預設遺漏）
4. ✅ 已確認——`webui_app/routes/{llm,image_gen}.py` 不是死碼，維持現狀未觸碰；`publish_defaults.py` 三個子路由中 `/publish/defaults`、`/publish/quick` 由舊版原生 JS（`sites.js`）實際呼叫，非孤兒；`/publish/save-defaults` 在全程式碼庫找不到任何呼叫者，記錄為孤兒路由候選（不刪除）
5. 檢查 SPA route 的 loading / error / empty 三態處理——**明確不在 B1 範圍**，已涵蓋於 B3，不在此重複
6. ✅ 已完成——`frontend/src/layout/navItems.ts` 的「雙軌並存」舊註解已更新為反映遷移完成的現況

**交付**：SPA Route Audit Matrix（已遷移/未遷移/缺失/孤兒），含上述具體發現、優先級與延後決策——見下方矩陣

### SPA Route Audit Matrix（2026-07-02）

**已遷移（13 個 navItems，全數 `isMigrated: true`，各自有對應 redirect 或原生 SPA 路由）**：`/`（SPA 頁面已存在於 router，僅缺 Flask redirect——見下方「缺失」）、`/monitor`、`/history`、`/drafts`、`/sites`（同左）、`/schedule`（✅ redirect 已補上）、`/batch-campaign`（同上）、`/settings`、`/pr-queue`、`/survival`、`/optimization-status`、`/equity-ledger`、`/keep-alive`。

**未遷移（明確決策，非遺漏）**：
- `/ce:health` 及其 6 個子面板（scorecard／publish-metrics／canary／forward-path／storage／GSC）——**決策：legacy-only，延後到未來 sprint**。理由：`/monitor` SPA 頁面消費的是 `command_center` 聚合資料，非 `health.py` 的資料表面；完整遷移是一個獨立規模的工作（6 個子面板），超出本次穩定化 sprint 的合理範圍。

**缺失（Flask 端沒有導回 `/app/*` 的 redirect，SPA 頁面本身已存在）**：

| 路由 | SPA 對應 | 狀態 | 處理方式 |
|---|---|---|---|
| `/schedule` | `/app/schedule` | ✅ 已修復（本次） | 加上 `redirect(url_for('spa.spa', subpath='schedule'))`；原渲染邏輯保留在新增的 `/schedule/jinja` |
| `/` | `/app/`（`PublishWorkbench.vue`）| ⏸ 延後，高風險 | 9 處既有 POST handler（`checkpoint.py`／`drafts.py`）以 `flash_type`/`flash_msg` query string 重導回本路徑；SPA 的 `pushFlash()` bridge 存在但未接線；37 個既有測試呼叫點斷言完整頁面渲染。需要獨立 unit：先接線 flash bridge（或改用其他機制傳遞操作結果），再處理 redirect + 測試遷移 |
| `/ce:history` | `/app/history`（`HistoryPage.vue`）| ⏸ 延後，高風險 | 同上機制，4 處 `history.py` POST handler 重導回本路徑帶 flash query string；18 個既有測試呼叫點 |
| `/sites` | `/app/sites`（`SitesPage.vue`）| ⏸ 延後，高風險 | `sites_save_three_url` 重導回 `/sites?saved=...&autofilled=...`，SPA 端零匹配、無接線；18 個既有測試呼叫點含大量狀態相關內容斷言（autopilot 列狀態、錯誤態） |
| `/batch-campaign`（GET）| `/app/batch-campaign`（`BatchCampaignPage.vue`）| ⏸ 延後，中風險 | 無 flash 重導耦合，但 7 個既有測試斷言 legacy-only 內容（擴展區平台分區、過期管道渲染），需先確認 SPA 端有等效覆蓋才能安全改寫 |

**孤兒（候選，未刪除）**：
- `webui_app/routes/publish_defaults.py` 的 `/publish/save-defaults`——`frontend/src/api/*.ts`、`webui_app/templates/`、`webui_app/static/js/` 全域找不到呼叫者；docstring 聲稱「由 publish pipeline routes 呼叫」但該呼叫點不存在。同檔案的 `/publish/defaults`、`/publish/quick` **不是**孤兒，由 `webui_app/static/js/sites.js` 的 quick-publish 委派監聽器實際呼叫。建議後續確認 `/publish/save-defaults` 是否為某次重構後遺留的死路由，若確認無用可安全移除。

**其他（非孤兒，維持原狀）**：`webui_app/routes/llm.py`、`webui_app/routes/image_gen.py`——已 deregister 但刻意保留作為測試 patch 對象，不是無主死碼。

**已知、已接受的缺口（非新發現，不重複提報）**：`/campaign/:campaignId` 的側欄高亮缺口——使用者已明確決定延後。

**明確排除於 B1 範圍**：SPA route 的 loading/error/empty 三態處理，由 B3 涵蓋，本文件不重複。

- [x] **B2 — API v1 ↔ Flask Route 雙覆蓋測試** ✅ 已完成（2026-07-02，原始前提經即時查證後修正）

**現狀（原始，2026-07-01 撰寫，未經查證）**：部分 route 已有 `test_webui_*` 測試（覆蓋 Flask 端），但 SPA 調用的 `/api/v1/` endpoint 缺乏獨立測試；並具體點名 campaign、equityLedger、keepAlive、optimizationStatus、prQueue、survival 這 6 個新 SPA page 的 API 需要補強。

**〔2026-07-02 執行時查證，原始前提不成立，已修正〕** 執行前的即時查證（由派工者先行 spot-check，執行時獨立覆核並擴大範圍）發現兩件事，性質完全不同於原始描述：

1. **`/api/v1/*` 60 個 endpoint（`grep -c 'path="/api/v1' webui_app/api/v1/spec.py`）本身其實已經 100% 有獨立測試**——逐一核對 22 個既有 `tests/test_webui_api_v1_*.py` 檔案 + `tests/test_webui_api_v1.py`（單數檔名，涵蓋 6 個 bootstrap endpoint：health/app-config/csrf-token/platforms/bound-platforms/pro-status，最初的 grep 因為檔名 glob 只抓 `test_webui_api_v1_*.py` 而漏看了這個檔案），每一個 endpoint 都能找到至少一個直接呼叫該路徑並斷言狀態碼/回應內容的測試（含 GET+POST 都有的 endpoint，如 `/settings/llm-config`、`/settings/keywords`、`/settings/schedule`、`/settings/blogger/blog-ids`，兩個 method 都各自被測到）。額外發現：`spec.py` 裡 `/settings/medium/{launch,probe,clear}-browser-login` 三個 route 是同一個 `for` 迴圈用 f-string 產生（第 978–1003 行），字面 `grep -c 'path="/api/v1'` 抓不到這個迴圈述句（不是字面字串），所以實際註冊的 endpoint 數是 63，不是 60；這 3 個也都在 `test_webui_api_v1_medium_login.py` 裡有測試。**結論：B2 原本設想的「/api/v1 測試缺口」不存在，本次審計沒有發現任何需要新增測試的 /api/v1 endpoint**。
2. **原始前提點名的 6 個 SPA page（campaign、equityLedger、keepAlive、optimizationStatus、prQueue、survival）的核心資料呼叫，其實完全沒有走 `/api/v1/*`**——逐一 grep `frontend/src/api/{campaign,equityLedger,keepAlive,optimizationStatus,prQueue,survival}.ts` 的實際 fetch 目標，全部呼叫的是舊版非 `/api/v1` 前綴的 Flask JSON route，只有 CSRF token 這一個共用的 bootstrap 呼叫（`/api/v1/csrf-token`）例外。這代表原始「這 6 個新頁面需要 /api/v1 測試」的框架，從一開始問錯了問題——它們的資料層根本不在 `/api/v1` 的覆蓋範圍內，B2 真正該問的是「這些 legacy route 有沒有測試」，而不是「/api/v1 版本有沒有測試」。`frontend/src/api/prQueue.ts` 檔案開頭第 2 行的既有註解（`// Uses legacy /api/pr-queue endpoints (no /api/v1 equivalent yet).`）證實這個落差是 SPA API 層早就知道、寫進程式碼註解的既有事實，不是 B2 的新發現——B2 的貢獻是把這個早已存在但沒被寫進計畫文件的落差，正式和「6 個新頁面需要 /api/v1 測試」這個錯誤前提對照清楚。

**動作（已完成，取代原始 3 步）**：
1. ✅ 已完成——列出 `webui_app/api/v1/spec.py` 的全部 63 個實際 endpoint（60 個字面 `path=` + 1 個 for 迴圈產生 3 個），逐一核對測試覆蓋，見下方「/api/v1 Endpoint 覆蓋矩陣」——**63 / 63 已有測試，0 個新增**
2. ✅ 已完成——獨立覆核派工者的 spot-check（6 個檔案全部重新 grep + 逐行讀取原始碼），確認前提修正成立，見下方「6 個 SPA page 實際呼叫的資料層」
3. ✅ 已完成——對 6 個頁面實際依賴的 legacy route，逐一 grep `tests/test_webui_*` 確認是否有測試；發現 4 個真正的測試缺口（見下方「Legacy Route 缺口」），已就地補上聚焦測試（成本低、無需新增 fixture 基礎設施），其餘 legacy route 已有既有測試覆蓋，記錄為「已覆蓋」不重複補測試

**交付（修正後）**：
- `/api/v1` endpoint → test 對照表，63/63 已覆蓋（見下表），**0 個新增測試**——因為審計發現覆蓋早已完整，不是因為跳過工作
- 6 個 SPA page 的資料層 route 對照表，修正原始「需要 /api/v1 測試」的錯誤框架
- 4 個 legacy route 測試缺口，已補上聚焦測試（`tests/test_webui_monitor_json_endpoints.py` + `tests/test_webui_service_routes.py`，共新增 8 個測試案例）

### /api/v1 Endpoint 覆蓋矩陣（2026-07-02，63 個 endpoint 全數已覆蓋）

| 模組（`webui_app/api/v1/`） | Endpoint 數 | 對應測試檔 | 狀態 |
|---|---|---|---|
| `__init__.py` + `app_config.py`（bootstrap：health/app-config/csrf-token/platforms/bound-platforms/pro-status）| 6 | `tests/test_webui_api_v1.py` | 已覆蓋（含 origin-guard 403 情境） |
| `pipeline.py`（plan/preview/validate/publish/regen-body）| 5 | `tests/test_webui_api_v1_pipeline.py` | 已覆蓋 |
| `history.py`（list/delete/bulk-delete/purge-failed/recheck）| 5 | `tests/test_webui_api_v1_history.py` | 已覆蓋 |
| `drafts.py`（list/schedule/publish-now/cancel/delete/bulk-delete）| 6 | `tests/test_webui_api_v1_drafts.py` | 已覆蓋 |
| `sites.py`（list/widgets/form/save/autopilot/scrape-preview）| 6 | `tests/test_webui_api_v1_sites.py` | 已覆蓋 |
| `settings_credentials.py`（channel token/notion-token/notion status）| 3 | `tests/test_webui_api_v1_settings_credentials.py` + `tests/test_webui_api_v1_notion.py` | 已覆蓋（含 THREAT-3 transport guard 情境） |
| `channel_bind.py`（通用 credential dispatch）| 1 | `tests/test_webui_api_v1_channel_bind.py` | 已覆蓋（含 5 種 auth_type） |
| `bind.py`（bind/poll/identity-mismatch keep+replace）| 4 | `tests/test_webui_api_v1_bind.py` | 已覆蓋（含 409/404/403 情境） |
| `oauth.py`（blogger-oauth/status/revoke/blog-ids GET+POST/medium-oauth clear）| 6 | `tests/test_webui_api_v1_oauth.py` + `tests/test_webui_api_v1_blog_ids.py` | 已覆蓋 |
| `llm.py`（llm-config GET+POST/test-connection/test-generation）| 3 | `tests/test_webui_api_v1_llm.py` + `tests/test_webui_api_v1_llm_diagnostics.py` | 已覆蓋 |
| `image_gen.py`（test-connection/generate-sample）| 2 | `tests/test_webui_api_v1_image_gen.py` | 已覆蓋 |
| `medium_login.py`（launch/probe/clear-browser-login ×3 + status）| 4 | `tests/test_webui_api_v1_medium_login.py` | 已覆蓋 |
| `velog.py`（status/login）| 2 | `tests/test_webui_api_v1_velog.py` | 已覆蓋 |
| `channels.py`（channels overview/forms）| 2 | `tests/test_webui_api_v1_channels.py` + `tests/test_webui_api_v1_channel_forms.py` | 已覆蓋 |
| `global_settings.py`（keywords GET+POST/schedule GET+POST）| 4 | `tests/test_webui_api_v1_global_settings.py` | 已覆蓋 |
| `profiles.py`（list/save/delete）| 3 | `tests/test_webui_api_v1_profiles.py` | 已覆蓋 |
| `campaigns.py`（form/create）| 2 | `tests/test_webui_api_v1_campaigns.py` | 已覆蓋 |
| `schedule.py`（scheduled list）| 1 | `tests/test_webui_api_v1_schedule.py` | 已覆蓋 |
| `monitor.py`（monitor summary）| 1 | `tests/test_webui_api_v1_monitor.py` | 已覆蓋 |
| **合計** | **63** | — | **63/63（100%）** |

（跑過 `pytest tests/test_webui_api_v1.py tests/test_webui_api_v1_*.py -q` 確認全數 198 個既有測試綠燈，本次審計未修改任何一個檔案。）

### 6 個 SPA page 實際呼叫的資料層（修正原始前提）

| SPA page | `frontend/src/api/*.ts` | 實際呼叫的 route（非 `/api/v1`）| 唯一共用的 `/api/v1` 呼叫 |
|---|---|---|---|
| keepAlive | `keepAlive.ts` | `GET /api/keep-alive/summary`，`POST/GET /ce:keep-alive/{recheck,recheck-status,recheck-cancel,republish-token,republish,republish-status,cycle-status,reset-exhausted}` | `/api/v1/csrf-token`（僅 CSRF bootstrap） |
| optimizationStatus | `optimizationStatus.ts` | `GET /api/optimization-status`，`POST /api/optimization-status/{set-weight,unlock-weight}` | `/api/v1/csrf-token` |
| equityLedger | `equityLedger.ts` | `GET /api/equity-ledger`，`POST /ce:equity-ledger/recheck` | 無（CSRF 直接讀 `<meta>`，未呼叫 `/api/v1/csrf-token`） |
| survival | `survival.ts` | `GET /api/survival` | 無（唯讀頁面，無寫操作） |
| prQueue | `prQueue.ts` | `GET /api/pr-queue`，`POST /api/pr-queue/status` | `/api/v1/csrf-token`；檔案第 2 行既有註解明載 `// Uses legacy /api/pr-queue endpoints (no /api/v1 equivalent yet).` |
| campaign | `campaign.ts` | `GET /api/campaign/{id}/status` | 無（唯讀頁面） |

**結論**：6 個頁面裡沒有任何一個的核心資料流走 `/api/v1`，這與原始「這 6 個新 SPA page 需要補 /api/v1 測試」的前提直接矛盾——正確的行動是稽核它們實際依賴的 legacy route，而非建立不存在的 `/api/v1` 對應。

### Legacy Route 缺口（4 個，已修復）

逐一 grep `tests/test_webui_*` 確認上表每個 legacy route 字面路徑是否有測試：

| Route | 使用者 | 修復前狀態 | 動作 |
|---|---|---|---|
| `GET /api/keep-alive/summary` | keepAlive.ts | **零測試**（`/ce:keep-alive/*` 其餘子路由都已有測試，唯獨這個 read summary route 沒有） | 已補 2 個測試於 `tests/test_webui_monitor_json_endpoints.py`（empty-state 欄位、與 `build_keepalive_view()` 來源一致性） |
| `GET /api/survival` | survival.ts | **零測試**（`test_webui_survival_dashboard.py` 只測了 `/survival-dashboard` HTML route，JSON twin 完全沒被測到） | 已補 2 個測試於 `tests/test_webui_monitor_json_endpoints.py`（empty-state 不 500、與 `build_survival_view()` 來源一致性） |
| `POST /api/optimization-status/set-weight`（JSON body） | optimizationStatus.ts | **零測試**（`test_webui_service_routes.py` 只測了同名但走 form-data、無 `/api` 前綴的 legacy 版本 `POST /optimization-status/set-weight`，SPA 實際呼叫的 JSON 版本沒被測到）| 已補 2 個測試於 `tests/test_webui_service_routes.py`（成功路徑 + 缺欄位 400） |
| `POST /api/optimization-status/unlock-weight`（JSON body） | optimizationStatus.ts | **零測試**（同上，只有 form-data legacy 版本被測）| 已補 2 個測試於 `tests/test_webui_service_routes.py`（成功路徑 + 缺欄位 400） |

其餘 legacy route（`/ce:keep-alive/*` 子路由、`/api/optimization-status` GET、`/api/equity-ledger` + `/ce:equity-ledger/recheck`、`/api/pr-queue` + `/api/pr-queue/status`、`/api/campaign/<id>/status`）均已有既有測試覆蓋，逐一核對後未發現額外缺口，不重複補測試。

新增的 8 個測試已個別執行確認通過（`pytest tests/test_webui_monitor_json_endpoints.py tests/test_webui_service_routes.py -q` → 39 passed, 3 pre-existing unrelated failures — 見下方「已知限制」）。

**已知限制**：`test_webui_service_routes.py` 裡另外 3 個既有測試（`test_get_keep_alive_renders`、`test_get_optimization_status_page`、`test_get_survival_dashboard_page`）在本次執行前就已經因為 legacy HTML route 現在改為 302 redirect 到 SPA 而失敗——這是 B1 已記錄的既有行為變更（見上方「SPA Route Audit Matrix」），與本次 B2 新增的測試無關，本次未修改也未修復，維持原狀留給後續 unit 處理。

- [ ] **B3 — SPA Error Boundary / Loading State 補全〔R3〕**

**現狀**：新建的 SPA page（campaign、equityLedger、keepAlive、optimizationStatus、prQueue、survival 共 6 個）可能缺少完整的錯誤處理機制。**〔2026-07-01 深化查證，已找到兩個具體、真實存在（非假設性）的反例〕**：
- **`frontend/src/pages/Publish/PublishWorkbench.vue`（首頁、用量最大的頁面）完全沒有使用共享的 `StateBlock` 四態元件**——載入態是自組的 soft-timeout busy 面板，錯誤處理只靠 toast（`useErrorToast`），沒有任何「空狀態」概念。這是唯一一個與其餘已遷移頁面不一致的主要導覽頁，B3 執行時應把它納入稽核範圍，即使它不在原本列出的 6 個新頁面名單裡。
- **`frontend/src/pages/KeepAlive/KeepAlivePage.vue` 有一個具體的假成功 bug**：頁面內部維護了包含 `'empty'` 的 `pageState` 狀態機（第 17、64 行），但傳給 `StateBlock` 的實際值把非 loading/error 的狀態一律收斂成 `'ready'`（第 273 行），導致 `empty-text="暂无数据..."`（第 275 行）這個 prop 實際上永遠不會被 `StateBlock` 用到——真正空的時候，頁面會把預設 slot（表格/計分卡）當成「ready」渲染出來，而不是顯示空狀態訊息。這正是 R3 第 6 點警告的「失敗的區塊不能靜默 fallback 成該頁面原本合法的空狀態文案」的鏡像版本（這裡是「空狀態被誤判成 ready」，性質相同：使用者看到的畫面與實際資料狀態不符）。
- **獨立佐證**：正在進行中的 `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`（Unit 8）為它自己的新儀表板頁面獨立重新發現了同一類反例（錯誤狀態必須排在空狀態判斷之前，否則列表抓取失敗會被誤呈現成「目前沒有任何報告」）——兩份互不知情的計畫各自發現同一種 bug 形狀，說明這是這個程式碼庫裡真實、會重演的風險，不是本計畫憑空假設。

**動作**：
1. 檢查每個 page 的 Vue component 是否有 `<Suspense>` 或 loading state
2. 檢查 API 調用是否有 `.catch()` 或 try/catch + error display
3. **〔深化修正〕** 確保 401/403/419 一致地透過既有 `classifyError` → 'permission' 分類呈現（`StateBlock` 內顯示固定訊息 + 重試按鈕）——**不是**跳轉到登錄頁：這個 SPA 沒有 app-level session 登入路由（`medium_login_api.py`/`velog_login_api.py` 是外部部落格平台的憑證流程，跟 app 本身的登入無關），原本「統一跳轉到登錄頁」的寫法假設了一個不存在的頁面，且與 `frontend/src/lib/errors.ts` 現有的 `classifyError`/`StateBlock` 慣例矛盾
4. 確認 `readCsrf()` 正確用在所有寫操作（AGENTS.md: 不可緩存 module-level）
5. **〔R3 新增〕負面條件**：後端部分失敗時，前端收到的回應**不能**呈現為 `ok:true`／成功樣式（「假綠」不能發生）
6. **〔R3 新增〕正面條件**：部分失敗時，頁面必須顯示明顯、不會自動消失的錯誤指示（橫幅或區塊內訊息），標明哪個部分失敗；已成功載入的其他資料必須保持顯示，不能整頁改為空白或通用錯誤畫面；失敗的區塊不能靜默 fallback 成該頁面原本合法的「空狀態」文案
7. **〔R3 新增〕組合情境**：至少對一個多資料來源頁面，測試「部分區塊已成功渲染、另一部分才失敗」的情境，確認失敗區塊有獨立的錯誤指示，而不是卡在 loading 或誤顯示為空狀態——不能只靠第 1 點的三態稽核來保證這個組合情境
8. **〔R3 新增〕自動化迴歸測試**：至少一個前端 component/unit 測試斷言「給定一個部分失敗或格式錯誤的 API 回應，頁面不會渲染成功樣式」——讓「不能假 ok:true」和 C1b 對後端一樣有 CI 迴歸保護，不是只靠一次性人工測試
9. **〔一致性檢查，回應修正案 Outstanding Question〕** `frontend/src/api/client.ts` 新增的 timeout/dedup/retry 韌性強化（標註「Phase 3+ T3.3」）需要用同樣的鏡頭檢視：確認 retry 邏輯只在真正的網路層錯誤（`TypeError`、`AbortError`）觸發，不會把伺服器已回應的錯誤（4xx/5xx）誤判為可重試、進而掩蓋真實失敗——依現有程式碼（`withRetry` 的 `isNetworkErr` 判斷）看起來已經正確區分，此步驟只需寫一則簡短驗證測試釘住這個行為
10. **〔深化新增，重用既有模式〕** 修復 `KeepAlivePage.vue` 的空狀態問題、以及稽核其餘 5 個頁面時，直接參照 `HistoryPage.vue` 的 `blockState` computed 屬性寫法（錯誤判斷排在空狀態判斷之前）與 `SitesPage.vue` 的既有慣例，不要發明新的狀態判斷順序
11. **〔深化新增，範圍釐清〕** B3 不依賴、也不消費 `docs/plans/2026-07-01-002-...` 新增的 5 個 Vue 錯誤攔截掛點（`window` 監聽／`app.config.errorHandler`／`router.onError`／`QueryCache`/`MutationCache` onError／Pinia `$onAction`）——那些是用來把「未預期的例外」回報給開發端診斷儀表板，B3 關心的是「頁面自己對已知失敗回應的狀態呈現是否正確」，兩者是互補、非依賴關係；若該計畫的 `QueryCache`/`MutationCache` 全域 `onError` 先落地，B3 應追加一個小驗證，確認它不會延遲或改變 6 個頁面 `blockState` 依賴的 `useQuery` `isError` 判定時機

**驗證**：手動模擬網路錯誤/Token 過期/部分失敗，SPA 應正確顯示對應的錯誤狀態，不白屏、不假成功、不靜默吞掉；**7 個頁面（原 6 個新頁面 + `PublishWorkbench.vue`，見上方現狀）**各自留下一筆記錄（模擬情境、UI 截圖、實際 API 回應、測試者與日期）；至少一個自動化前端測試涵蓋「無假 ok:true」斷言

---

## Sprint C: CI/CD Hardening

- [ ] **C1 — CI 合規矩陣驗證**

**現狀**：CI 中有多個 job（unit, integration, lint, plan-check），但缺乏統一的合規矩陣。

**動作**：
1. 驗證 CI 是否執行以下所有檢查：
   - `pytest tests/`（unit + integration）
   - `mypy src/backlink_publisher/ --strict`（已啟用的子包）
   - `ruff check src/`（lint）
   - `py_compile` + `ast.parse`（語法驗證）
   - `test_no_monolith_regrowth.py`（SLOC budget）
   - `test_no_complexity_regrowth.py`（CC budget）
   - `test_plan_check.py`（plan-doc validation）
   - import-linter CI check
2. 確保 `PYTHONHASHSEED=0` 在所有 job 中設置（footprint regression gate）
3. 如缺少任何檢查，添加到 ci.yml

**交付**：CI check matrix 文檔 + ci.yml 補全

- [ ] **C1a — pytest `--reruns` 範圍限定（import-based 自動判定）〔R9，新增，doc-review 後重新設計〕**

**現狀**：未提交的 `.github/workflows/ci.yml` 變更為整個 `-m "unit"` job 加上了 `--reruns 2 --reruns-delay 1`（失敗自動重跑兩次），這是單一全域 flag，已違反 R9。

**〔doc-review 發現，原方案作廢〕** 原方案打算用「6 個已知檔案的手動清單」排除接縫層測試。adversarial review 直接執行本方案原本自己指定的偵測指令 `grep -rl "events\.\|gap\.\|idempotency\.\|ledger\.\|webui_app\.api" tests/ --include='test_*.py'`，結果是 **151 個檔案**，不是 6 個——手動清單第一天就會低估範圍 25 倍以上。而且手動清單和「逐測試 marker」有一模一樣的弱點：未來新增的接縫測試如果沒被記得加進清單，會靜默漏進 unit-rest 被套用 reruns，重演 R9 想避免的問題本身。

**新決策**：比照 `tests/conftest.py` 現有的 `__tier__` 屬性自動套用 marker 機制（無 `__tier__` 的模組預設歸類為 unit）——新增一個以「測試模組實際 import 了哪些接縫模組」為依據的**自動判定**，而不是手動宣告。預設方向刻意偏安全側：判斷不確定時歸類為 seam（排除 reruns），而不是預設不排除。

**動作**：
1. 在 `tests/conftest.py` 的 collection hook 中新增邏輯：檢查每個測試模組是否 import 了 `events`、`gap`、`idempotency`、`ledger`、`webui_app.api` 中任一模組路徑，符合的自動套用 `pytest.mark.seam`
2. 執行 `grep -rl "events\.\|gap\.\|idempotency\.\|ledger\.\|webui_app\.api" tests/ --include='test_*.py'`（即時重新執行，本文件的 151 這個數字本身也可能已過時），逐一（或抽樣＋分類規則）確認哪些是真正測接縫行為、哪些只是巧合 import 該排除——這是一次性的初始分類工作，建立一個明確的「巧合 import、排除在外」清單並附理由；之後新測試靠 import 自動判定，不需要重複這個規模的人工審閱
3. 把現有單一 `-m "unit"` pytest 呼叫拆成兩個 job（或同一 job 內兩個 step）：
   - `unit-seam`：`-m "unit and seam"`，**不套用** `--reruns`
   - `unit-rest`：`-m "unit and not seam"`，套用 `--reruns 2 --reruns-delay 1`
4. 在 ci.yml 中為 `unit-rest` 加註解說明重跑範圍的理由；為 `unit-seam` 加註解說明分類是 import 自動判定，例外清單需要人工維護並附理由
5. 驗證兩個 job 加總的測試數與原本單一 job 一致（沒有測試被意外漏掉）
6. **〔深化新增〕** 在 `pyproject.toml` 的 pytest `markers` 清單中新增 `seam` 的宣告（例如 `"seam: test transitively touches a seam module (events/gap/idempotency/ledger/webui_app.api); excluded from --reruns"`）——CI 的 unit job 帶 `--strict-markers`，若只在 `conftest.py` 套用 `pytest.mark.seam` 而不在 `pyproject.toml` 註冊，第一次套用就會讓整個 unit job collection 直接失敗，比 R9 原本要解決的重跑掩蓋問題更嚴重

**驗證**：新增一個測試檔，故意 import `events` 模組但不做任何額外宣告，確認它自動被分類進 `unit-seam`（不套用 reruns）；刻意讓 `unit-seam` 範圍內一個測試間歇性失敗，確認 CI 真的紅燈而不是被重跑吃掉；`unit-rest` 範圍內同樣操作，確認會重跑

**已知限制（明確記錄，比照 C1b 的已知限制慣例，不在本次解決）**：動作 1 描述的「檢查測試模組是否 import 了接縫模組」若只看該測試檔自己的 import 陳述式，會漏掉**透過被測模組間接、遞移 import 到接縫模組**的情況——例如某測試只 `import backlink_publisher.geo.joins`，而 `geo/joins.py` 內部才呼叫 `ledger.sources.build_target_buckets`，測試檔本身完全沒出現 `ledger` 字樣，會被誤判為純 unit 而套用 `--reruns`，重演 R9 想解決的同一種問題（只是換了個更隱蔽的觸發路徑）。同樣地，透過共用 fixture（如呼叫 `create_app()` 間接載入 `webui_app.api`）觸及接縫模組的測試也可能落在這個盲區。本次只做直接 import 的自動判定，遞移 import 分析設計複雜度高，留待下一輪迭代；分類標準不確定時仍應偏安全側（歸類為 seam）

- [ ] **C1b — 接縫層裸 except AST 掃描器〔R5，新增，doc-review 後收斂為純掃描器〕**

**依賴**：D2 完成分類規則與理由標籤格式的定義（不需要等全部 except 都分類完，但兩邊必須共用同一套字面格式，見動作 5）

**現狀**：這批工作區裡已經有 3 個檔案（`events/reconciler.py`、`gap/events_gap.py`、`webui_app/helpers/contexts.py`）示範了「機械式窄化、無理由」這個具體反模式，這是本任務存在的直接證據。**〔doc-review 修正〕** 原本引用 `docs/audits/2026-05-27-recurring-trap-eradication-audit.md` 佐證「這類坑無法機械化防護」，但該文件實際內容是關於另外兩類不同的坑（negative-shape 斷言掩護、workflow/judgment 類問題），從未討論裸 except——這個引用不成立，已移除，改用上述工作區裡的直接證據。

**決策**：比照 `tests/test_events_r8_gates.py` 的既有模式（AST 掃描特定寫入模組，並自帶紅色路徑自我測試證明護欄有效）。**〔doc-review 修正〕** 原本規劃這個任務還要做「理由相似度檢查」與「debt_registry schema 遷移」，但 adversarial review 用計畫自己描述的方法實測後發現這兩者都不可靠（細節見新任務 D2b）——已拆分出去，C1b 收斂為純 AST 掃描器 + 自我測試。

**動作**：
1. 新增 `tests/test_seam_except_classification.py`：用 `ast.walk` 掃描 `events/`、`gap/`、`idempotency/`、`ledger/`、`webui_app/api/`、**`_util/`（doc-review 新增——D2 的 Batch 1 本身已把 `_util/` 列為高優先接縫層工作，掃描範圍必須涵蓋，否則 D2 在 `_util/` 的分類成果沒有迴歸保護）**底下的 `.py` 檔案，找出裸 `except Exception:`（無具體型別）
2. **〔doc-review 修正〕理由註解偵測必須綁定到該 except handler 自己的 AST 節點行號範圍**，不能用固定行數窗口——已確認 `webui_app/helpers/contexts.py` 存在背靠背、中間沒有其他程式碼的連續 try/except 區塊，固定「往後 3 行」的窗口會把理由註解錯誤歸屬到隔壁的 except，造成假通過或假失敗。做法：用 `ast` 取得每個 `ExceptHandler` 的 `lineno` 與其 body 涵蓋的行號範圍，再用 `tokenize` 或原始文字逐行掃描，只在該 handler 自己的範圍內尋找理由註解（例如 `# debt: <slug>`）或緊鄰的 `log`/`logger` 呼叫
3. **已知限制（明確記錄，不在本次解決）**：本掃描只抓字面上的裸 `except Exception:`。如果有人把它窄化成具體型別但沒加理由（就像工作區裡那 3 個檔案示範的），窄化後就不再是「裸 except Exception」，掃描器抓不到這個情況。這 3 個既有檔案，**加上 `webui_app/api/v1/settings_credentials.py`（深化查證新發現，見 D2 現狀——已窄化為 `except OSError:` 的憑證清除路徑，且沒有任何 log 呼叫）共 4 個檔案**，必須在 D2 靠人工審閱處理，不能依賴本護欄；擴大掃描範圍涵蓋「窄化但無理由」的一般情況，設計複雜度高，留待下一輪迭代
4. 附紅色路徑自我測試 `test_red_path_bare_except_is_detected`，**至少涵蓋三種情境**：(a) 孤立的裸 except（基本情境）；(b) 背靠背、中間無程式碼的連續 try/except（驗證理由歸屬不會錯位，直接對應第 2 點發現的真實程式碼形狀）；(c) 巢狀 try/except（驗證掃描器正確定位巢狀 handler 的範圍）——證明掃描器在真實存在的程式碼形狀上「有牙齒」，不只是對單一合成範例有效
5. **〔doc-review 新增〕理由標籤格式必須和 D2 共用同一套字面規範**（例如固定為 `# debt: <slug>`）——目前程式碼庫沒有任何既有慣例可以參考（已確認 `# debt:`／`# rationale:` 在 `src/backlink_publisher/` 中零匹配），D2 與 C1b 的實作者必須先對齊這個格式常數，不能各自假設

6. **〔深化新增，feasibility review 發現〕** C1b 依 doc-review 決策可以在 D2 完全分類完成前先上線（見上方「依賴」），但這代表上線當下 `src/backlink_publisher/`＋`webui_app/api/` 裡仍有約 97+15 處（且已知還有低估，見 D2 現狀）尚未分類的裸 except——若掃描器對所有裸 except 一律紅燈，會讓 C1b 上線那一刻起，所有後續 PR 的 unit-seam 測試全部變紅，而不是只攔截「新增」的違規。比照 `tests/conftest.py` 既有的 `GRANDFATHERED_EXPANDUSER_SITES`（shrink-only 允許清單）模式：C1b 上線時，先用一次性即時 grep 產生「已知既存」的裸 except 位置清單，凍結成一份 shrink-only 的 grandfathered 清單；掃描器只對**不在**這份清單裡的裸 except 紅燈，D2 逐步分類完成後從清單移除對應項目，清單只能縮小不能新增

**驗證**：CI 上這個新測試綠色通過（含情境 (a)(b)(c) 三種紅色路徑自我測試都通過）；刻意在接縫層新增一個未分類的裸 except 後重跑測試，確認會紅燈；確認 grandfathered 清單裡的既存項目上線當下不會讓 CI 紅燈，且清單被 CI 強制為 shrink-only（新增項目會被拒絕）

- [ ] **C2 — 性能基準趨勢**

**現狀**：`tests/test_benchmarks.py` 已建立 3 個基準，但無 CI diff gate。

**動作**：
1. 讓 benchmark 測試在 CI 中紀錄結果（使用 pytest-benchmark 的儲存機制）
2. 建立一個 GitHub Actions workflow 來比較 PR 與 main branch 的性能差異
3. 設定性能退化閾值（如 >10% 退化則標記）

**驗證**：CI benchmark job 成功輸出比較結果

- [ ] **C3 — SPA Build / Lint CI 集成**

**現狀**：frontend/ 使用 Vite + TypeScript，但 CI 中無前端建置/語法檢查。

**動作**：
1. 在 CI 中新增 `frontend-lint` job：`cd frontend && npx tsc --noEmit && npx vite build`
2. 確保 vite build 輸出到 `webui_app/spa_dist/`（Flask 的靜態文件服務路徑）
3. 驗證 CI 中 Node.js 版本（用 `actions/setup-node`）

**驗證**：CI 上的 frontend-lint job 綠色通過

---

## Sprint D: Code Debt Cleanup

- [ ] **D1 — 大測試檔拆分〔R4〕**

**現狀**：`complexity_budget.toml` 中仍有幾個大測試檔。**⚠️ 數字已過時**：下表左欄是 `complexity_budget.toml` 2026-06-11 的快照，中欄是 doc-review 於 2026-07-01 稍早用 `radon raw -s` 量測的結果，右欄是本次深化（同樣是 2026-07-01）獨立重新量測的結果——**〔深化修正，doc-review-review 發現〕** 兩次量測的 SLOC 完全一致（差異為 0），沒有成長；先前版本此處誤把 `radon raw -s` 輸出裡的 `LOC:` 欄位（1125/932/850/821/695）當成 CI 實際判定用的 `SLOC:` 欄位而寫進表格，是量測欄位讀錯，不是檔案真的在成長。`radon raw -s` 對同一份原始輸出會印出 `LOC`/`LLOC`/`SLOC`/`Comments` 等多個欄位，只有 `SLOC:` 這一行對應 `complexity_budget.toml` 的 ceiling（`tests/test_no_complexity_regrowth.py` 的 `_sloc_of()` 讀的正是這個欄位），任何人重新量測時務必只取 `SLOC:` 那一行：

| 測試檔 | complexity_budget.toml 快照 | 2026-07-01 doc-review 量測（SLOC） | 2026-07-01 深化再量測（SLOC） | Ceiling |
|--------|-----------|---------|---------|------|
| test_cli_plan_check.py | ~1126 | 818 | **818**（一致） | 1160 |
| test_webui_three_url.py | ~1152 | 684 | **684**（一致） | 1190 |
| test_config_three_url.py | ~851 | 643 | **643**（一致） | 890 |
| test_publish_backlinks.py | ~821 | 601 | **601**（一致） | 860 |
| test_work_scraper.py | ~696 | 544 | **544**（一致） | 730 |

五個檔案全部**仍在**各自的 budget ceiling 之內，SLOC 數字自 doc-review 以來沒有變化，優先順序（`test_cli_plan_check.py` 最大，818 行）與 doc-review 當時的結論一致，未改變。**執行前仍應重新量測**——不是因為這批數字已知過時，而是因為 D1 動作 0 已經明確要求執行當下重新驗證，避免任何時間差造成的漂移。

**動作**：
0. **〔doc-review 新增，執行前必做〕** 對這 5 個檔案重新跑一次 `python -m radon raw -s`，用即時數字重新排出 P0/P1/low 順序——不要沿用上表或原計畫「test_webui_three_url.py 是 P0」的說法，即時量測顯示 `test_cli_plan_check.py`（818 行）現在才是最大的
1. 依重新排出的順序拆分最大的檔案：按其子功能拆分（例如 `test_cli_plan_check.py` 可按 plan-check 子功能拆分：frontmatter / claims / schema / git）
2. 依序處理下一大的檔案
3. 使用與 `test_plan_backlinks.py` 相同的 split-and-slim 模式
4. **〔R4 新增〕** 拆分過程中，對被搬移、且涉及接縫層（events/、gap/、idempotency/store.py、ledger/、webui_app/api/、`_util/`）的斷言，檢查是否只驗證型別/結構（如 `isinstance(x, list)`）而未驗證內容或數值；發現此類斷言須強化為驗證實際數值。範圍限於本次被搬動的測試，不做全測試套件的窮舉稽核

**驗證**：拆分後 max test file SLOC < 600（用即時 `radon` 驗證，不是本文件的表格），所有測試通過；被搬移涉及接縫層的斷言已逐一檢查並視需要強化

### Deferred to Separate Tasks

- 全測試套件（613 檔）shape-only 斷言窮舉稽核：範圍限於本次 D1 搬動的測試（見動作 4），不在本計畫內做全套件稽核。

- [ ] **D2 — `except Exception:` 窄化 + 接縫層分類〔R1, R2〕**

**現狀**：`⚠️ 數字已過時`——原估 ~133 個 bare `except Exception:`（從 142 降下 9 個），doc-review 即時 `grep` 量測為 **97 個**（`grep -rn "except Exception:" src/backlink_publisher/ --include='*.py' | wc -l`）。**〔doc-review 發現的範圍缺口，必須修正〕** 這個 grep 指令本身、以及下方「未提交檔案」清單，都只涵蓋 `src/backlink_publisher/`，完全遺漏了 `webui_app/api/` 底下**既有、非本次新增**的裸 except——即時查證 `webui_app/api/` 有 **6 個檔案、15 處**裸 `except Exception:`（`campaign_api.py`、`channel_bind_api.py`、`image_gen_diagnostics_api.py`、`sites_api.py`、`v1/monitor.py`、`v1/settings_credentials.py`），這些從未出現在本任務原本的工作量清單裡，但 R1 的規則是「每一個被**觸碰或保留**的裸 except」都要分類——「保留」意味著即使不是本次新增/修改的，只要它還留在接縫層模組裡，就在 D2 的範圍內。C1b 的護欄會掃描 `webui_app/api/`，一旦上線就會立刻對這批既有程式碼亮紅燈。

**〔深化修正，security review 發現的更大範圍缺口〕** 上述 15 處的 grep 指令只匹配字面上不帶變數名的 `except Exception:`，完全遺漏了帶變數名的形式 `except Exception as e:`／`as exc:`——即時用涵蓋兩種寫法的 pattern 重新查證，`webui_app/api/` 底下這種形式還有約 **40 處額外匹配**，其中包含 D2 原本清單完全沒提到的憑證/OAuth 相關檔案：`oauth_api.py`（Blogger/Medium OAuth token 存取/撤銷）、`medium_login_api.py`、`llm_settings_api.py`、`global_settings_api.py`、`blogger_settings_api.py`。這些檔案必須併入 D2 的分類工作量，且 D2 的完成驗證（見下方「驗證」）所用的 grep 指令本身也需要同步涵蓋這個帶變數名的形式，否則 D2 可以在這批憑證相關的 except 完全沒分類的情況下宣稱「完成」。另外，這批檔案裡多處把原始例外文字直接用 f-string 嵌進回傳給前端的錯誤訊息（例如 `image_gen_diagnostics_api.py` 的 `f"unexpected: {exc}"`），有洩漏內部實作細節的風險——`sites_api.py` 已有更安全的既有寫法（`type(exc).__name__` 而非例外字串），分類這批 except 時應比照這個既有慣例。

工作區目前也已有**未提交的機械式窄化**，且已經觸及接縫模組：`events/reconciler.py`、`gap/events_gap.py` 被改為 `except (ValueError, TypeError):`，`webui_app/helpers/contexts.py` 被改為 `except (OSError, ValueError):` / `except (OSError, ValueError, KeyError):`——三者都只縮小了型別，**沒有理由註解、沒有 log、沒有 debt_registry.toml 對應條目**。

**〔R1 修正〕驗收標準變更**：原本「count ≤ 80」的目標保留，但不再是唯一驗收條件。每一個被觸碰或保留的裸 `except Exception:` 都必須分類為：
- (a) 確實需要靜默 → 附一句理由註解（須指名具體例外型別與呼叫點，不能只寫「這裡需要靜默」這類籠統句子）+ `debt_registry.toml` 對應條目（含 D2b 新增的 `location` 欄位）
- (b) 改為記錄（log）後往上拋或降級處理

**動作**：
1. **優先處理已在途的 3 個檔案**：`events/reconciler.py`、`gap/events_gap.py`、`webui_app/helpers/contexts.py` 的現有窄化必須先套用上述分類規則，才能 commit——不能原樣提交後才回頭補分類
2. **〔R2〕** 目前未提交的 `src/backlink_publisher/` 檔案有 15 個（`git status` 即時查證），扣除上面已列的 2 個，其餘 13 個（多數在 `cli/`、`cli/spray_backlinks/`、`cli/ops/` 下，另含 `config/tokens.py`、`optimization/rules.py`、`_util/net_safety.py`）尚未確認是否屬於接縫層——逐一比對後，屬於接縫層的併入本任務優先分類，其餘視為一般 `_util` 窄化。**`_util/net_safety.py` 明確視為接縫層範圍**（呼應 Batch 1 已將 `_util/` 列為高優先，避免這個檔案的歸屬懸而未決）
3. **〔doc-review 新增〕** 除了上述未提交檔案，**額外把 `webui_app/api/` 既有的 6 個檔案、15 處裸 except 納入本任務工作量**——這些不在 git diff 裡，需要單獨盤點，用即時 `grep -rn "except Exception:" webui_app/api/ --include='*.py'` 取得目前確切清單（15 這個數字本身也可能已過時）
4. **Batch 1 — 非 adapter 接縫層檔案**（優先級高）：`events/` 中的 broad catch 縮小為具體型別；`_util/` 中的工具函數多數可指定具體異常；`idempotency/store.py` 的 SQLite 操作可指定 `sqlite3.Error`；`webui_app/api/` 的既有裸 except 逐一分類
5. **Batch 2 — Adapter 中的安全 catch**（優先級中，**明確排除在 R1 完整分類/debt_registry 要求之外**——見下方「範圍決策」）：只做 `log.warning` + `continue` 的可指定為 `(RequestException, Timeout, ConnectionError)`；保留真正需要 `except Exception` 的兜底捕獲
6. **〔深化新增，前瞻協調，路徑已修正〕** 若 `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md` 在 D2 之前落地，它會新增 `webui_app/api/v1/error_reports.py`（該計畫 Unit 3 檔案清單與技術決策表確認的實際路徑，含 `v1/`）——執行 D2／C1b 時應把這個新檔案一併納入 `webui_app/api/` 的裸 except 掃描與分類範圍，且沿用 D2／C1b 屆時確立的理由標籤格式常數，不要讓它自成一套

**範圍決策（回應修正案 Outstanding Question）**：`publishing/adapters/` 目前含裸 `except Exception:` 的檔案數比四個接縫層加總還多（確切比例請執行前即時 grep 重新核對，不要用任何文件裡的舊數字），且是修正案核心佐證文件之一（`adapter-silent-exceptions-resolution.md`）的主角。但 Phase 3 原始方針已經判斷「adapters 確需 broad catch」，把它們放在低優先級 Batch 2。本次迭代**維持這個排除**——adapters 不納入 R1 的完整分類 + debt_registry 要求，Batch 2 仍只做既有的窄化處理。這是明確接受的殘留風險：本計畫无法完整涵蓋自己引用的佐證案例之一，留待下一輪迭代視 Batch 2 執行結果決定是否該提升優先級。

**驗證**：`grep -rn "except Exception:" src/backlink_publisher/ webui_app/ --include='*.py' | wc -l` → ≤80（**doc-review 修正：原指令遺漏 `webui_app/`，已補上**）；`events/`、`gap/`、`idempotency/store.py`、`ledger/`、`webui_app/api/*`、`_util/` 中每一個被觸碰或保留的裸 except，都能在 PR 描述或程式碼註解中找到明確分類（理由或修正方式）；`pytest tests/ -x` 全過

- [ ] **D2a — 訊號往返驗證〔R1a，新增〕**

**現狀**：D2 的 except 分類只處理「例外有沒有被吞掉」，但 `docs/solutions/` 記錄的多個歷史案例（dofollow-undercounting 的三重缺口、language-matches-always-true 永遠回傳 True 的判斷式）根因根本不是被吞掉的例外，而是資料/邏輯層的靜默遺漏——單靠 except 分類無法防止這類 bug 重演。

**動作**：
1. 為五個接縫模組（`events/`、`gap/`、`idempotency/store.py`、`ledger/`、`webui_app/api/`）各自新增至少一個「訊號往返驗證」測試：直接斷言訊號抵達下一階段的儲存或狀態（例如斷言 DB 欄位真的被更新、ledger 真的記錄了該事件），而非只斷言「沒有拋出例外」或「回傳了某個型別」
2. 可參考 `tests/test_ledger_aggregate.py`（`recheck-ledger-liveness-seam` debt 條目提到的、已經有類似「斷言 live 數字真的下降」的正向整合測試）作為既有可仿效的模式

**驗證**：五個接縫模組各自至少一個新的往返驗證測試，且測試確實斷言終點狀態的具體數值/內容，不是型別或結構

- [ ] **D2b — debt_registry.toml 結構化定位 + 防敷衍機制〔doc-review 新增，取代 C1b 原本失效的相似度檢查〕**

**現狀**：C1b 原本規劃用「理由文字相似度 >90% 視為重複」防止敷衍式合規。**adversarial review 用 `difflib.SequenceMatcher`（即計畫原本說的「簡單字串相似度、不用 NLP」）實際計算，發現這個機制兩面都不可靠**：兩句實質重複但換句話說的籠統理由，相似度只有 0.488（低於門檻，抓不到真正的重複）；兩句針對不同呼叫點、各自具體但剛好用了相近句型的合格理由，相似度卻有 0.934（高於門檻，會把合格的工作誤判為重複）。**〔深化 doc-review 修正〕更根本的問題不是「完全沒有唯一性檢查」**——`tests/test_debt_registry_format.py::test_all_slugs_unique` 已即時查證存在，`slug` 目前就是全域唯一（registry 檔頭註解也明確記載 `slug` 為 unique identifier）。真正的缺口是：`location` 欄位不存在，也沒有機制把一則 `# debt: <slug>` 註解跟 `debt_registry.toml` 裡的條目綁到具體呼叫點——就算加了 `location` 欄位但只是可選、不驗證 (slug, location) 唯一性，最便宜的敷衍路徑會是：寫**一筆**籠統但剛好 ≥80 字的理由，然後在多個不同呼叫點都用同一個既有（已通過全域唯一性檢查）的 `# debt: <slug>` 引用它——每個呼叫點都能通過「有對應的理由註解」檢查，因為 slug 本身確實唯一、`location` 缺席讓每個呼叫點是否各自對應到獨立條目完全沒有檢查。

**決策**：不採用文字相似度檢查，改用結構性規則——讓敷衍在結構上就走不通，而不是靠比對文字內容的相似程度。

**動作**：
1. `debt_registry.toml` 新增欄位 `location`（格式 `path/to/file.py:function_name` 或 `path/to/file.py:行號`）：當一筆條目被至少一個 `# debt: <slug>` 註解引用時，**此欄位為必填**
2. 新增唯一性規則：**每個 (slug, location) 組合必須唯一**——同一個 `location`（同一個具體呼叫點）不能對應到已經被別的呼叫點用過的 slug，逼迫「同一個 slug 到處引用」的敷衍路徑在結構上被擋下來，因為每新增一個呼叫點就需要一筆新的、獨立的 debt 條目與理由文字
3. 新增交叉比對測試：掃描接縫層（含 `_util/`）程式碼裡所有 `# debt: <slug>` 註解，確認每一個都能在 `debt_registry.toml` 找到對應條目，且該條目的 `location` 與呼叫點的實際檔案:行號相符——不允許「有引用但查無此 location」或「location 與實際位置對不上」
4. 更新 `tests/test_debt_registry_format.py`：加入 `location` 欄位定義、(slug, location) 唯一性測試、交叉比對測試
5. 與 C1b 共用同一套理由標籤格式常數（見 C1b 動作 5）——這是兩個任務唯一需要對齊的共享格式
6. **〔深化新增，adversarial review 發現的殘留缺口〕** (slug, location) 唯一性只保證「同一個呼叫點不能重複引用別人的 slug」，不保證理由本身有差異化內容——最便宜的規避路徑會是替每個新呼叫點複製貼上同一段（改幾個字避免 100% 一致的）籠統理由，各自建立獨立、格式合法的條目。新增一個檢查：拒絕 `debt_registry.toml` 裡出現**逐字完全相同**的 `rationale` 字串（精確字串比對，不是模糊相似度——避免重蹈 C1b 原本文字相似度檢查已被證實的雙向失效）；這攔不下換句話說的規避，但能攔下最省力的複製貼上路徑，且不需要額外引入不可靠的相似度演算法

**驗證**：`pytest tests/test_debt_registry_format.py -x` 全過；刻意讓兩個不同呼叫點的 `# debt:` 註解指向同一個 `location`，確認測試會紅燈；刻意寫一個 `# debt: <slug>` 註解但不在 `debt_registry.toml` 建立對應的 `location`，確認交叉比對測試會紅燈；刻意讓兩筆不同 (slug, location) 條目使用逐字相同的 `rationale`，確認新增的精確字串比對測試會紅燈

- [ ] **D3 — ko-corpus-calibration**

**現狀**：Korean 語言檢測閾值 `RATIO_THRESHOLD=0.30` 是未經校準的 v1 默認值（`debt_registry.toml` 中唯一仍 `open` 的條目：`ko-corpus-calibration`）。

**動作**：
1. 收集 ~50 篇真實韓文文章（Naver Blog, Tistory, Korean news）
2. 在測試環境中運行語言檢測，記錄檢測率
3. 如果 < 90% 檢測率，調整閾值
4. 添加 corpus 校準測試（測試已知韓文文本能被正確檢測），並將 `debt_registry.toml` 的 `ko-corpus-calibration` 條目更新為 `resolved` + `resolved_date`

**驗證**：校準後的閾值在測試 corpus 上達到 ≥95% 檢測率，無假陽性

---

## Sprint E: Documentation & Observability

- [ ] **E1 — docs/ 目錄整理（死文檔歸檔）〔R6〕**

**現狀**：docs/ 包含 15 個子目錄 + 多個根文件，其中部分已過時或重複。

**動作**：
1. 審閱每個 doc 文件，判斷是否仍活躍（`docs/active-docs.md` 可作為參考，但注意它本身也可能已經過時，需要在這個任務中一併更新）
2. 過時文件移到 `docs/_archive/`（附時間戳記 + 取代文件鏈接）
3. 確認 root README.md 指向 docs/ 的正確路徑
4. 特別處理：
   - `OPTIMIZATION_REPORT.md` (root) → `docs/optimization-history.md` 已取代
   - `OPTIMIZATION_COMPLETE_REPORT.md` (root) → 同上
   - `FINAL_OPTIMIZATION_REPORT.md` (root) → 同上
   - **`OPTIMIZATION_PHASE3_REPORT.md` (root)（R6 補上，原清單漏了這第 4 份）** → 同上
   - **`.fix_webui.py`、`.fix_webui2.py`（R6 補上，殘留的正則表達式批次改寫腳本，用來批次修 mypy 錯誤，從未清理）** → 歸檔或刪除
   - `docs/ideation/` → 如果全是 brainstorming 且無後續 action，歸檔
   - `docs/spike-notes/` → 如果對應 spike 已關閉，歸檔

**驗證**：`docs/` 根目錄只有活躍文檔，過時文件都在 `_archive/`；4 份根目錄優化報告與 2 支 `.fix_webui*.py` 腳本都已歸檔或刪除

- [ ] **E2 — AGENTS.md / CLAUDE.md 同步〔R7〕**

**現狀**：workspace root 的 AGENTS.md 是最新的，但需要確保它與 `backlink-publisher/AGENTS.md` 同步。**〔R7 補上〕** `CLAUDE.md` 現況完全沒提到 Vue 3 SPA、`frontend/` 或 `BACKLINK_PUBLISHER_SPA` 旗標的存在，而 `ARCHITECTURE.md` 已經正確記載這些；`webui_app/AGENTS.md` 有相同的缺口，且其 Structure 表完全沒列出 `api/` 目錄——即 D2/C1b 點名的接縫層之一。

**動作**：
1. 比較兩個 AGENTS.md，確認金規則一致
2. 更新 Phase 3 的相關 section（如有需要）
3. 檢查 CI 配置部分是否反映當前 CI 狀態（含本次新增的 C1a/C1b job）
4. 確保「Branches and launchers」部分反映最新的 branch 架構（配合 A3）
5. **〔R7 新增〕** 更新 `CLAUDE.md` 的 WebUI/架構描述，明確提及 Vue 3 SPA、`frontend/`、`BACKLINK_PUBLISHER_SPA` 旗標與雙前端並存現況，對齊 `ARCHITECTURE.md`
6. **〔R7 新增〕** 更新 `webui_app/AGENTS.md`：加入同樣的 SPA/frontend 說明，並在 Structure 表補上 `api/` 目錄
7. **〔深化修正，adversarial review 即時查證發現基準數字本身已過時〕** 「9 個 state-persistence stores」這個基準本身不準確——即時查證 `webui_store/verify_health.py` 的 `verify_health_store` 是一個既有但先前未被計入的 `_LazyStore`，代表**目前實際就是 10 個**，不是 9 個；若 `docs/plans/2026-07-01-002-...` 的 `webui_store/error_reports.py` 再落地，正確數字會是 **11**，不是原先設想的 10。執行 E2 時不要對「9」做加一運算，改為即時 grep `webui_store/*.py` 底下所有 `_LazyStore(` 宣告與 eager singleton，重新完整計數後更新 `CLAUDE.md`；同時確認 `webui_app/api/v1/spec.py` 是否已登記其 `/api/v1/error-reports` endpoint，供 B2 的 endpoint 清單使用

**驗證**：兩份 AGENTS.md 與 CLAUDE.md 的 WebUI/架構描述彼此一致、且與 ARCHITECTURE.md 一致，無矛盾

- [ ] **E3 — 運行時健康檢查增強**

**現狀**：已有 `/health` endpoint（200/503），健康指標存於 `webui_app/health_metrics.py`。

**動作**：
1. 為 SPA 新增前端健康檢查：`/api/v1/health` 或 SPA 特有 ping
2. 確保 `health_metrics.ranking_trend()` 和 `indexation_status()` 在無 GSC 數據時代優雅降級（不炸 500）
3. 考慮加入 pipeline 運行時長監控（上次成功 pipeline 時間戳）

**驗證**：`curl localhost:8888/health` 返回 200 + 合理 body

---

## 併發計畫交叉引用（Concurrent Plan Coordination）

2026-07-01 深化查證發現兩份與本計畫同時存在、檔案範圍有重疊的獨立計畫文件（均不屬於 Phase 3，但執行時需要交叉核對）：

- **`docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md`**——狀態：**已完成並提交**（4 個 unit 對應 commit `9357c7f6`/`c34d6728`/`ebfd81a1`/`5f154308`，後續 code-review 修正 `bdd06db7`，計畫文件本身已於 `45b9b26e` 提交）。這份計畫修復了 SPA 主題切換、側欄品牌區首頁連結、5 個頁面遷移到 `.data-table` 共享約定、側欄窄屏響應式抽屜——執行 B1／B3 時應把這些視為已解決的既有基礎，不需重新發現，但 B1／B3 各自的實際任務範圍（route↔API 對應、假成功防護測試）完全不受影響，工作量不減少。
- **`docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`**——狀態：active，已深化（`deepened: 2026-07-01`），規模大（8 個 unit，橫跨兩個前端 + 新 SQLite store + `/api/v1/error-reports` API）。這份計畫的 Scope Boundaries 已明確排除新增全站 `@app.errorhandler(Exception)`，理由是與本計畫（Phase 3 訊號完整性強化）範圍重疊——**Phase 3 在此對應確認：D2／C1b 同樣不新增全站 catch-all，兩份計畫的排除決定互相一致，非單方面**。具體檔案面重疊點：
  - 該計畫會新增 `webui_app/api/v1/error_reports.py`（**深化修正：路徑含 `v1/`**，對照該計畫 Unit 3 檔案清單與技術決策表）——落在 D2／C1b 的既有掃描範圍（`webui_app/api/`）內；若該計畫先落地，新模組必須套用 D2／C1b 屆時確立的 `# debt: <slug>` 理由標籤格式，不能自成一套
  - **〔深化修正，「9」本身已是舊數字〕** 該計畫會新增一個 `webui_store`（`webui_store/error_reports.py`）——但根目錄 `CLAUDE.md` 記載的「9 個 state-persistence stores」即時查證已經不準（`webui_store/verify_health.py` 的 `verify_health_store` 是既有但未被計入的第 10 個），所以該計畫落地後的正確數字是 **11**，不是 10；E2 執行時應重新完整計數，不要對舊數字做簡單加一
  - 該計畫會修改 `webui_app/api/v1/__init__.py` 並新增 `/api/v1/error-reports` endpoint——B2 從 `webui_app/api/v1/spec.py` 抓 endpoint 清單時，應留意這個 endpoint 屆時是否已登記在 `spec.py`（該計畫自己的檔案清單未提及會 touch `spec.py`）
  - 該計畫與 001 的後續修正都觸碰 `TopBar.vue`／`SideNav.vue`／`AppShell.vue`——B1／B3 執行者若同時有其他計畫在動這幾個檔案，應遵循同樣的循序執行紀律（先 `git status` 確認乾淨再動手），不要假設可以安全並行

**適用建議**：Sprint A／B／E2 開始執行前，應先即時查一次 `docs/plans/` 底下有沒有其他 `status: active` 且 claims 路徑重疊的計畫，不能只信任本文件這份快照——上方列出的兩份是 2026-07-01 深化查證當下的清單，執行時可能已經有變化（甚至可能已有更多份）。

---

## Execution Order & Timeline

```
Sprint A (Workspace Hygiene) ───────────────── 1-2 天（多數已完成，剩 A1 收尾 + A3 確認）
  A1 ──> A3（獨立確認）

Sprint B (Frontend Stabilization) ──────────── 6-8 天（B3 因 R3 擴充增加約 1 天）
  B1 ──> B2 ──> B3

Sprint C (CI/CD Hardening) ─────────────────── 5-8 天（C1a 因改用 import 自動判定＋151 檔初始分類約 1-1.5 天、C1b 收斂為純掃描器但需處理三種紅色路徑情境約 1-1.5 天）
  C1 ──> C1a (獨立) ──> C1b (依賴 D2 分類規則與格式確立) ──> C2 (獨立) ──> C3 (獨立)

Sprint D (Code Debt Cleanup) ───────────────── 6-8 天以上，**〔深化修正，coherence review 發現〕估計可能仍偏低**：D2 因分類+webui_app/api 既有 15 處+13 檔盤點增加約 1-1.5 天，新增 D2a 約 1 天、D2b 約 1 天——且 D2 現狀已發現 webui_app/api/ 的裸 except 實際數量比 15 處更多（見 D2 現狀的即時 grep 修正說明），這批新增工作量尚未反映在此處的天數估計裡，執行前應重新評估
  D1 ──> D2 ──> D2a (依賴 D2) ──> D3 (獨立)
             └─> D2b (依賴 D2 確立理由標籤格式，需與 C1b 對齊)

Sprint E (Documentation) ───────────────────── 2-3 天
  E1 ──> E2 (依賴 E1) ──> E3 (獨立)

──────────────────────────────────────────────
總計：約 21-30 天（原估 17-23 天 + 第一輪修正約 2-4 天 + doc-review 第二輪修正約 2-3 天）
```

### 依賴圖

```
A1 ⚠️ 完整完成（含 3 個接縫檔案的 commit）實際依賴 D2 先確立分類規則 ──┐
  ├── A3                              │
  ├── D1 (含 R4 斷言強化)             │
  ├── D2 (含 R1/R2 接縫層分類 + webui_app/api 既有 except) ──> D2a
  │                                   │              └──> D2b (共用格式，依賴 C1b)
  └── E2 (積壓含 AGENTS.md 更新)      │
                                       │
B1 ──> B2 ──> B3 (含 R3 擴充)          │
C1 ──> C1a (含 R9，import 自動判定) ──┐│
                                       ├──> C1b (含 R5，純掃描器，依賴 D2 格式) ──> D2b（共用格式常數）
                                       ↓
C2 (獨立) ──> C3 (獨立)                │
D3 (獨立, 可並行)                      │
E1 ──> E2                              │
E3 (獨立)                              │
                                       ▼
                              Final verification
                              (all tests + CI pass)
```

---

## Out of Scope（明確排除）

| 項目 | 原因 |
|------|------|
| 新 adapter 開發 | 屬於 v0.6.0 功能開發 |
| Python 3.13 支援測試 | 依賴 upstream 生態成熟度 |
| APScheduler 4.x 相容性 | 低優先級，無 breaking change 信號 |
| PyPI 發布 | 非技術決策 |
| 完整的端到端 E2E 測試 | 需獨立 plan-doc（scope 過大） |
| SPA 全面遷移完成 | 這是一個持續性工作，不應在一次 sprint 完成 |
| `publishing/adapters/` 的完整 R1 分類 + debt_registry 對應 | 見 D2「範圍決策」——維持既有「adapters 確需 broad catch」判斷，明確接受的殘留風險 |
| `STEWARDSHIP.md` 治理缺口（所有領域 unassigned） | 組織流程議題，與程式碼健壯性修正性質不同，留待另外處理 |
| Phase 3 計畫全域重排優先順序（D3/C2/C3/E3 相對於本次修正的先後） | 維持原 A→E 執行順序；v0.6 時程與本次修正的取捨已記錄於 Risk Register，留給執行前再權衡 |
| 全測試套件（613 檔）shape-only 斷言窮舉稽核 | 範圍限於 D1 本次搬動的測試，見 D1 動作 4（R4）；doc-review 補列，原本只在 D1 內文提及，未列入本表 |
| C1b 掃描「窄化但無理由」的一般情況（非字面裸 except Exception） | 見 C1b「已知限制」——設計複雜度高，本次只處理字面上的裸 except；工作區裡已存在的 3 個窄化案例改由 D2 人工審閱處理，不依賴掃描器 |

---

## Success Criteria（成功指標）

| 指標 | 當前 | 目標 |
|------|------|------|
| Uncommitted files | 深化查證 28（含 A1 核心 25 檔背景不變 + 3 項需分開處理的新增項，見 A1；原 174） | **0**（核心 25 檔清空），且已窄化的 3 個接縫檔案已完成分類；兩份不相關的並行計畫文件不計入此指標 |
| git status | dirty | **clean** |
| Workspace root stale CI | ✅ 已確認不存在 | 維持 |
| `except Exception:` 數量（`src/backlink_publisher/` + `webui_app/`） | 即時查證約 97（`src/` 部分），另加 `webui_app/api/` 既有 15 處 | **≤80，且每個保留/觸碰的都有明確分類（含 webui_app/api/ 既有的部分)** |
| 接縫模組訊號往返驗證 | 無 | **五個模組各至少一個** |
| 最大測試檔 SLOC | 深化再查證 1125（`test_cli_plan_check.py`，同一天內從 818 漲到 1125，見 D1），非本文件任何靜態表格 | **≤600**（以執行當下即時量測為準） |
| SPA route coverage | 部分遷移 | **審計完成 + 缺失已記錄** |
| API v1 test coverage | 不完整 | **100% endpoint → test** |
| SPA 假成功防護 | 無 | **6 頁面正面+負面+組合情境人工測試記錄，+ 至少 1 個自動化測試** |
| CI benchmark gate | 無 | **有 diff comparison** |
| SPA CI build | 無 | **有 tsc + vite build** |
| `--reruns` 範圍 | 全域套用（違反 R9） | **接縫層測試（import 自動判定，非硬編碼清單）排除，範圍有文件化理由** |
| 接縫層裸 except AST 掃描器 | 無 | **CI 已接入，三種紅色路徑（孤立/背靠背/巢狀）自我測試通過** |
| debt_registry.toml 防敷衍機制 | 無 | **`location` 必填 + (slug, location) 唯一性 + 交叉比對測試，取代原本失效的相似度檢查** |
| docs/ 活躍度 | 含過時文件（含 4 份根報告 + 2 支殘留腳本） | **只保留活躍文檔** |
| AGENTS.md / CLAUDE.md 一致性 | CLAUDE.md 未提及 SPA | **三份文件與 ARCHITECTURE.md 一致** |
| Korean calibration | uncalibrated | **校準 + 測試覆蓋，debt_registry 條目更新為 resolved** |
| 運行時健康檢查 | Flask only | **SPA 也有 /health** |
| `pytest tests/ -x` | 應全過 | **全過** |

---

## Risk Register

| 風險 | 可能性 | 影響 | 緩解措施 |
|------|--------|------|----------|
| 25 個殘留檔案中遺漏關鍵變更 | 中 | 高 | 分類審閱 + 先跑完整測試；已窄化的 3 個接縫檔案優先處理 |
| SPA 遷移中斷向後相容性 | 低 | 高 | SPA 和 Flask templates 並存期間不做 breaking change |
| CI benchmark diff gate 太嚴格 | 中 | 低 | 初始閾值設為 20%，後續調緊 |
| except Exception 窄化引入 regression | 低 | 中 | 修改後先跑完整測試套件 |
| Korean calibration 無代表性 corpus | 中 | 低 | 從 Naver/Tistory 收集至少 50 篇 |
| **D2 的分類淪為敷衍式合規**（一句籠統理由蓋章多個呼叫點） | 中 | 高 | D2b 的 (slug, location) 唯一性 + 交叉比對測試（**doc-review 修正：取代原本已證實失效的文字相似度檢查**） |
| **C1a 的 import 自動判定初始分類（~151 檔）耗時超出預期，或分類標準不一致** | 中 | 中 | 明確記錄「巧合 import 排除清單」與理由，供後續審閱；分類標準不清楚時預設歸類為 seam（安全側） |
| **C1b 掃描器誤判理由歸屬**（固定行數窗口的舊設計已被證實在背靠背 except 上會出錯） | 中 | 中 | 改用 AST handler 範圍界定 + 三種情境的紅色路徑自我測試（見 C1b 動作 2, 4） |
| **`_util/` 在 D2 分類範圍內、但沒有 C1b 護欄保護的落差** | — | — | doc-review 已修正：C1b 掃描範圍新增 `_util/`，與 D2 Batch 1 一致 |
| **`publishing/adapters/` 的靜默例外持續累積**，因為明確排除在本次分類範圍外 | 中 | 中 | 已在 Out of Scope 明確記錄為接受風險，留待下一輪迭代評估 |
| **v0.6.0 啟動時程與本次擴充範圍的機會成本**——D3/C2/C3/E3 與訊號完整性無關，但本次修正讓 D1/D2/B3/C1 的工時增加約 4-7 天 | 中 | 低 | 維持原優先順序不重排；若時程吃緊，執行前可重新評估 D3/C2/C3/E3 是否延後，而非默默壓縮 D2/B3 的分類品質 |
| **這個 repo 目前有其他 session 同時修改**，本文件任何數字快照可能瞬間過時 | 高（**2026-07-01 深化查證直接證實**：本次深化過程中親眼看到 git 狀態在約 15-20 分鐘內變化 3 次，包含新計畫文件出現／已提交、多個新 commit 持續產生） | 中 | 每個任務執行前用即時指令重新查證；避免依賴本文件記錄的具體數字或 commit hash |
| **兩份具名、檔案範圍有重疊的並行計畫**（`2026-07-01-001` 已完成、`2026-07-01-002` 進行中）與 Phase 3 共用 `webui_app/api/`、`webui_store/`、shell 元件（`TopBar.vue`/`SideNav.vue`/`AppShell.vue`）、`config.example.toml`、budget TOML | 中 | 中 | 執行 A1／B1／D2／C1b／E2 前，先查一次 `docs/plans/` 有無其他 active 且路徑重疊的計畫（見「併發計畫交叉引用」小節）；不倚賴本文件記錄的計畫清單 |
| **本計畫規模（18+ 項任務，5 個 sprint）明顯大於 `docs/plans/` 其他計畫**（觀察值，非結論） | 低 | 低 | 維持單一文件的決定已在修正案中確認；若執行中發現規模確實難以管理，可考慮把 D3/C2/C3/E3 標記為 Final verification 的非阻塞項目 |
| **〔2026-07-02 執行期間發現，超出本計畫範圍〕`main`／本分支已存在約 366 個與 Phase 3 無關的預存失敗測試**（即使套用 CI 實際使用的 `-m "unit"` filter 仍有 366 個，未過濾則 459 個），確認並非 Windows 本機環境假象——以 `tests/test_cli_plan_check.py`（72 個失敗）為例，`git show main:...` 直接證實 `cli/plan/plan_check.py` 委託模組缺少 `SCHEMA_VERSION` 重新匯出，這個缺陷已經在 `main` 的既有 commit 歷史裡，與本次 A1/Phase 3 的任何改動無關；另外抽查 `test_cli_canary_seed.py`（`_sleep` 屬性已不存在）與 `test_no_raw_home_path_primitives.py`（`GRANDFATHERED_EXPANDUSER_SITES` 清單已跟原始碼行號脫節）確認是同類型、真實的既存 code/test drift，不是平台差異 | 高（已直接驗證） | 中 | 明確排除在 Phase 3 範圍外——A1 及後續 Sprint 的「pytest 全過」驗收標準改為「與本次改動的檔案相關的測試全過」，不含這批既存失敗；建議另開一個獨立的健檢/清理計畫追查根因（懷疑源頭是先前的大規模自動化 commit，如 `a64b205f "opt(src): add __all__ declarations, fix imports..."`），不併入本計畫執行 |
| **〔2026-07-02 A3 執行期間發現〕`fix/drafts-store-test-isolation`、`fix/recheck-ledger-liveness-seam` 兩個殘留分支（local+remote）內容已透過 squash-merge 安全併入 main（PR #42／#31），可以刪除，但刪除 remote 分支屬於對共享狀態可見的操作** | 低（內容安全性已驗證；未刪除只是留著不美觀） | 低 | 已透過 AskUserQuestion 徵求刪除授權，60 秒無回應，依 git 安全協議不代為執行；刪除動作（`git branch -d` + `git push origin --delete`，兩者皆可安全執行）留給用戶下次明確指示時處理，不再視為本計畫的阻塞項 |

---

## Deferred / Open Questions

### From 2026-07-01 review

- **A1 success criteria contradicts D2 dependency: cannot deliver clean git status if 3 seam files blocked** — Sprint A: Workspace Hygiene (A1) and Sprint D: Code Debt Cleanup (D2) (P0, coherence, confidence 0.95)

  A1 lists three files (`events/reconciler.py`, `gap/events_gap.py`, `webui_app/helpers/contexts.py`) as part of its 25-file scope but explicitly states these files must complete D2's classification procedure before commit. Simultaneously, A1's verification criteria requires `git status` clean (all 25 files committed). Since D2 is scheduled in Sprint D — after Sprints B and C in the plan's own execution order — these 3 files cannot be committed during A1 as currently sequenced. Either pull the 3 files out of A1's "clean" target, or sequence D2's classification of just those 3 files ahead of A1's final commit.

  <!-- dedup-key: section="sprint a workspace hygiene a1 and sprint d code debt cleanup d2" title="a1 success criteria contradicts d2 dependency cannot deliver clean git status if 3 seam files blocked" evidence="a1 现状 目前已窄化但未分類的 3 個接縫模組檔案 eventsreconcilerpy gapeventsgappy webui" -->

- **Adapter except-handling excluded despite being the plan's own cited evidence case** — Sprint D / D2 範圍決策 / Out of Scope (P1, product-lens, confidence 0.70)

  The plan's stated rationale is that silent signal loss at subsystem seams is the dominant recurring bug pattern, citing `adapter-silent-exceptions-resolution.md` as core evidence. Yet `publishing/adapters/` has more bare `except Exception:` instances than all four seam modules combined, and stays excluded from the full R1 classification + debt_registry requirement — the plan's own text acknowledges it "cannot fully cover one of its own cited evidence cases." Either re-justify the exclusion against the new evidence, or commit to a scoped, dated follow-up for the highest-traffic adapters rather than an open-ended "next iteration."

  <!-- dedup-key: section="sprint d d2 範圍決策 out of scope" title="adapter excepthandling excluded despite being the plans own cited evidence case" evidence="publishingadapters 目前含裸 except exception 的檔案數比四個接縫層加總還多" -->

- **Sprint sequencing doesn't front-load the signal-integrity work the plan says matters most** — Risk Register / Out of Scope / Execution Order & Timeline (P1, product-lens, confidence 0.65)

  The plan opens by declaring itself "the last consolidated optimization iteration before v0.6.0," making calendar time a real constraint, yet the execution order runs Sprint B (largely unrelated to the signal-integrity origin problem) before the seam-layer work in Sprint D (D2/D2a/D2b) that the origin brainstorm identifies as the actual recurring root cause. If v0.6.0 pressure forces a schedule cut partway through, the sequencing as written means unrelated polish has already consumed budget while the plan's actual justification is most exposed to being squeezed. Either resequence to run the signal-integrity work earlier, or explicitly pre-commit now to cutting D3/C2/C3/E3 first under time pressure rather than deciding ad hoc at execution time.

  <!-- dedup-key: section="risk register out of scope execution order timeline" title="sprint sequencing doesnt frontload the signalintegrity work the plan says matters most" evidence="本計畫定位為 v05x 維護週期的最後一次集中優化迭代 目標是在啟動 v060 功能開發前" -->

- **Stated 90/10 polish/new-build ratio contradicted by plan's own time estimates** — Philosophy（方針）/ Execution Order & Timeline (P2, scope-guardian, confidence 0.75)

  The Philosophy section anchors the plan's risk framing on a 90% polish / 10% new-build split, naming D2a/D2b/C1a/C1b as the entire 10%. But the plan's own time estimates attribute roughly 4-5 of the 21-30 total days specifically to those four items — about 17-20% of the total, nearly double the stated ratio. If this ratio is later used to justify why Phase 3 stayed disciplined relative to P1-P11's larger swings, it rests on a number the plan's own estimates don't support. Either restate the ratio to match the actual split, or trim scope on one of the four new-build items to bring it back toward what's claimed.

  <!-- dedup-key: section="philosophy 方針 execution order timeline" title="stated 9010 polishnewbuild ratio contradicted by plans own time estimates" evidence="只建那些能讓未來開發更安全的防護層 d2a d2b c1a c1b 屬於這 10" -->

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-07-01-phase3-signal-integrity-hardening-requirements.md](../brainstorms/2026-07-01-phase3-signal-integrity-hardening-requirements.md)
- 既有護欄先例：`tests/test_events_r8_gates.py`（C1b 仿效對象，AST 掃描 + 紅色路徑自我測試模式）、`tests/test_no_monolith_regrowth.py`、`tests/test_no_complexity_regrowth.py`（數值預算比對，非形狀掃描，不適合直接仿效 C1b）
- 既有 tier 自動判定機制：`tests/conftest.py::pytest_collection_modifyitems`（`__tier__` 屬性自動套用 marker——C1a 的 import-based 自動判定仿效此既有模式）
- 訊號往返驗證既有模式：`tests/test_ledger_aggregate.py`（D2a 仿效對象）
- `debt_registry.toml`：schema 定義於檔案開頭註解，`ko-corpus-calibration` 為唯一開放條目；`slug` 全域唯一性已由 `tests/test_debt_registry_format.py::test_all_slugs_unique` 驗證，但缺少 `location` 欄位與 (slug, location) 交叉比對機制（D2b 修正的實際起點，見 D2b 現狀修正）
- 相關 solutions 文件：`docs/solutions/logic-errors/2026-06-05-001-live-dofollow-undercounting-triple-gap.md`、`docs/solutions/logic-errors/language-matches-always-true-no-op-gate-2026-05-14.md`、`docs/solutions/correctness/adapter-silent-exceptions-resolution.md`、`docs/solutions/ui-bugs/webui-blocking-subprocess-and-missing-progress-feedback-2026-05-12.md`、`docs/solutions/ux-honesty/webui-false-success-resolution.md`
- **併發計畫**（2026-07-01 深化查證新增，見「併發計畫交叉引用」小節）：[docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md](2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md)（已完成並提交）、[docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md](2026-07-01-002-feat-frontend-error-reporting-plan.md)（進行中，已深化）
