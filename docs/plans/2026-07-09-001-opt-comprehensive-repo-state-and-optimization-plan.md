---
title: "opt: 全面專案狀態收斂與優化計畫（落地已完成工作 + 倉庫衛生 + 填補缺口）"
type: optimization
status: proposed
date: 2026-07-09
priority: high
claims: {}
---

# opt: 全面專案狀態收斂與優化計畫

## Overview

本計畫回應使用者要求「分析專案庫狀況，提出全面優化建議計畫」。這是**第二次**提出相同請求：
第一次（2026-07-07）產出了 `2026-07-07-003-opt-backend-code-health-optimization-plan.md`
並執行為 `opt/backend-code-health` 分支，**該分支已標記 completed 但尚未合併進 main**。

重新盤點（2026-07-09 即時快照）後，本計畫的核心論點是：

> **當前最大的「優化」槓桿不是寫新程式碼，而是（1）落地已經做完但沒合併的優化分支，
> （2）清理混亂的本地倉庫狀態，使其開發迴圈乾淨可控，然後（3）填補真正仍開放的缺口
> （效能基準、剩餘複雜度熱點、Windows 開發機型別摩擦）。**

本計畫刻意**不重複**既有 active 計畫已認領的範圍（見下方交叉參照表）。

## Current Repo State Snapshot（2026-07-09 即時量測）

### A. 已完成但未落地的優化工作
- `opt/backend-code-health` 分支：**12 commits ahead / 9 behind main**，最後 commit 為
  `ede41baf docs(plans): mark backend code-health plan completed, all 7 units done`。
  - 已處理：`_dispatch_router/routing.py::route`(D28)、`_util/http_probe.py::_triage`(D23)、
    `scorecard/engine.py::build_channel_scorecard`(D22)、`scorecard/reliability_readiness.py::channel_readiness`(D21)
    四個 D 級熱點降複雜度；cookie-refresh 寫入失敗補 log；測試 env 隔離防護；debt registry 時效 triage（43 項全有效）。
  - **未動 `monolith_budget.toml` / `complexity_budget.toml`**（預算保持綠燈），改動均為重構且 ruff 通過。

### B. 倉庫衛生問題（造成開發迴圈噪音與風險）
1. **`main` 上有 13 筆未提交改動**（coherent 的「per-row 結構化錯誤」功能：
   `sdk/api.py` + `webui_app/api/v1/errors.py` + `webui_app/routes/command_center.py` 的
   `/error-reports` 重導 + 前端 `errors.ts/.spec.ts` + `PublishWorkbench.vue` + 2 個測試 + 1 份 plan doc）。
   ruff 對這些 Python 檔**全過**。這是落在 `main` 上的 WIP，不屬於任何分支（已確認無分支含此改動）。
2. **6 個 `egg-info` 檔被追蹤**：`src/backlink_publisher.egg-info/{PKG-INFO,SOURCES.txt,
   dependency_links.txt,entry_points.txt,requires.txt,top_level.txt}`，儘管 `.gitignore` 已有 `*.egg-info/`。
   每次 build/install 都改動工作樹（即上述 13 筆中的 3 筆純屬此噪音）。
3. **缺 `.gitattributes`** → 多檔出現 `LF will be replaced by CRLF` 警告
   （`.gitignore`、`egg-info/SOURCES.txt`、`requires.txt`、測試檔），跨平台換行造成無謂 churn。
4. **過期 worktree**：`bp-w8-shell`（已合併）、`bp-wsgi-prod`（已合併）、
   `.worktrees/feat/windows-portable-package`（內容經 PR #88 已合併）三者仍被 `git worktree list` 註冊。
5. **孤兒目錄 `bp-fix-main-mypy/`**：存在於 workspace 但**不在** `git worktree list` 中（未註冊的殘留 checkout）。
6. **根目錄雜物**：`nul`（Windows 裝置檔，已加進 `.gitignore` 但仍實體存在）、`mypy_full.txt`（326 行 dump，未忽略）、
   `ANALYSIS_REPORT_2026-07-08.md`（在 workspace 根，依 AGENTS.md 屬「dead docs 區」，應移入 `backlink-publisher/docs/`）。

### C. 效能 / 品質缺口（來自 2026-07-08 分析報告，仍開放）
- **效能基準缺口（最高優先）**：`.benchmarks/` 目錄存在但為空；程式碼有 `cProfile` 埋點但無連續基準，
  任何速度優化都無法被守護。
- **發布核心順序執行（H1）**：`cli/publish_backlinks/_engine.py`(635 SLOC) 為順序發佈，I/O-bound 下吞吐受限。
  ⚠️ 注意 `2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md` 已認領「per-platform-lane 平行發佈引擎」——
  **本計畫不重複，改為追蹤/協助其落地**。
- **SQLite 連線複用（H2）**、`http_form_post.py` 等 4 處裸 `requests`→`Session`（H3）。
- **剩餘複雜度熱點**：radon 顯示 31 個 CC≥21 函式；`opt/backend-code-health` 修掉 4 個 D 級後約 **27 個仍 ≥21**
  （含 `events/history_query.py::_build_history_item` CC30、`cli/plan_backlinks/core.py::main` CC30、
  `publishing/adapters/catalog/catalog_schema.py::validate_entry` CC28、`config/loader.py::load_config` CC28 等）。
- **Windows 開發機 mypy 摩擦**：`mypy src/backlink_publisher` 報 58 錯誤（19 檔），幾乎全是 `fcntl` 跨平台誤報；
  Linux CI 實際通過，但本地 `make type-check` 紅燈，拖慢開發迴圈。另有約 5 處 `Unused "type: ignore"`。

## 與既有計畫的交叉參照（避免重複認領）

| 既有計畫 | 狀態 | 本計畫的關係 |
|---|---|---|
| `2026-07-07-003-opt-backend-code-health` | completed（分支未合併） | **落地它**（Phase A1），不重做其內容 |
| `2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan` | active | 平行發佈引擎（H1）由其認領；本計畫只追蹤/協助 |
| `2026-07-06-005-opt-webui-uiux-comprehensive` | active | WebUI 層由其認領；本計畫不碰 |
| `2026-07-06-006-opt-master-convergence` | completed | 分支/worktree 處置方法論沿用；本計畫執行其遺留的殘留項 |
| `2026-07-07-002-fix-production-wsgi-entrypoint` | completed | 已合併；其 worktree `bp-wsgi-prod` 待 prune |

## Implementation Plan（分四階段，依賴順序執行）

### Phase A — 落地已完成的工作（最高 ROI / 最低風險）
- [ ] **A1: 審查並合併 `opt/backend-code-health`**
  - 動作：在 worktree 中 `git checkout opt/backend-code-health` → 跑 `make test -m unit` +
    `ruff check` + 比對 `monolith_budget.toml`/`complexity_budget.toml` → 以 `--no-ff` 合併進 main（保留分支語意）。
  - 為何：12 commits 的優化已 done 卻未生效，是當前最大的「已投入未產出」。
  - 風險：低（預算綠、ruff 綠）；注意 9 behind 須先 `git merge main` 解衝突再合併。
- [ ] **A2: 將 `main` 上的 WIP 移到專屬分支並開 PR**
  - 動作：`git stash` → `git checkout -b feat/webui-per-row-errors` → `git stash pop` →
    提交（排除 egg-info 噪音）→ 開 PR。含 `sdk/api.py` 的 `PipeResult.errors` 欄、WebUI `ApiProblem.errors` 陣列、
    `/error-reports` 重導、前端 `errors.ts` + 測試。
  - 為何：不要把 coherent 功能工作長期攤在 `main` 上（多 session 併發教訓見 `docs/solutions/`）。

### Phase B — 倉庫衛生（解鎖乾淨開發迴圈）
- [ ] **B1: 取消追蹤 egg-info**：`git rm --cached -r src/backlink_publisher.egg-info`（`.gitignore` 已覆蓋，不再回潮）。
- [ ] **B2: 新增 `.gitattributes`**：加入 `* text=auto eol=lf`（或針對 `.py`/`.ts`/`Makefile` 顯式規則），
  消滅 CRLF 警告與跨平台 churn；對已提交檔視需要 `git add --renormalize .` 一次性正規化。
- [ ] **B3: 修剪過期 worktree**：`git worktree remove ../bp-w8-shell ../bp-wsgi-prod` 與
  `git worktree remove .worktrees/feat/windows-portable-package`（皆已合併，安全）；
  對孤兒 `bp-fix-main-mypy/` 先確認無未提交改動再 `rm -rf`（未註冊，不在 worktree 鎖內）。
- [ ] **B4: 根目錄雜物收尾**：`mypy_full.txt` 加進 `.gitignore` 並 `rm`；`nul` 已忽略可刪；
  將 `ANALYSIS_REPORT_2026-07-08.md` 移入 `backlink-publisher/docs/`（或轉為本計畫附錄），清掉 dead docs 區。

### Phase C — 效能地基（讓後續優化可被守護）
- [ ] **C1: 建立效能回歸基準（P0）**：填補 `.benchmarks/`，採 `pytest-benchmark` 或固化 `cProfile` 輸出為基線；
  先對 `publish_backlinks`、`plan_backlinks/core`、`sdk/api` 建基線，使 C2/C3 的優化可回歸守護。
- [ ] **C2: 追蹤/協助平行發佈引擎落地**：與 `v060-uiux-pipeline-upgrade-plan` 協調，確認 per-platform-lane 並發
  設計（H1 假說須以 cProfile 實測單次 vs 批量 wall-time 證實後再動手）。
- [ ] **C3: 連線複用小優化**：確認 SQLite 是否每次操作開新連線（H2）；`http_form_post.py` 等 4 處裸 `requests`→`Session`（H3）。

### Phase D — 殘餘品質債
- [ ] **D1: 剩餘 ~27 個 CC≥21 熱點**：小步萃取重構（先攻 Top 15：`history_query`、`plan_backlinks/core`、
  `catalog_schema::validate_entry`、`config/loader::load_config`、`medium_brave::publish`、`phase0/validation`、
  `spray/canary_seed::main`、`_seal_init::_handle_init`、`gap/engine::plan_gap`、`_engine::_prepare_publish_rows` 等）。
  每改一處同步更新 `complexity_budget.toml`（若增監控），遵守「同 PR 調 ceiling 附 ≥80 字 rationale」。
- [ ] **D2: 修 Windows 本地 mypy**：在 `fcntl` 使用處加 `sys.platform` 守衛或 mypy `platform` override，使本地 `make type-check` 綠燈。
- [ ] **D3: 清 ~5 處 `Unused "type: ignore"`**。
- [ ] **D4: 維持 debt_registry 時效**：`opt/backend-code-health` 已 triage 43 項全有效；後續新增債務須即時登記。

## Execution Safeguards（沿用 `docs/solutions/` 制度性教訓）

- **每個 unit 開工前**：`git -C backlink-publisher status --short` + `git worktree list` 確認乾淨、無其他 session 活躍。
- **一律使用 worktree 隔離**，絕不在 `main` 上直接做具修改工作（本次 `main` WIP 正是反面教材）。
- **所有數字（SLOC、CC、mypy 錯誤數）皆為 2026-07-09 快照**，執行前務必即時重新量測；本計畫不假設靜態不變。
- **預算守護**：任何 SLOC/CC 改動即跑 `monolith_budget.toml`/`complexity_budget.toml` 比對；超標須同 PR 調高 ceiling 附 rationale。

## Sequencing / Dependencies

```
A1 (合併 backend-code-health) ──┐
A2 (WIP→分支) ──────────────────┤
B1..B4 (衛生) ──────────────────┼─→ C1 (基準，守護後續) ─→ C2/C3 (效能) ─→ D1..D4 (品質債)
B3 (prune worktree) ────────────┘
```
- A 與 B 可並行（不同 worktree）；C 依賴 A 落地後的穩定基底；D 可與 C 並行。
- 優先順序：A1 > A2 ≈ B1/B2/B3 > C1 > B4 > C2/C3 > D1 > D2/D3/D4。

## Open Questions / Decisions Needed

1. `opt/backend-code-health` 合併方式：`--no-ff` merge（保留分支史）vs. rebase+squash？建議 `--no-ff`。
2. `main` 上的 per-row errors WIP 是否獨立成 `feat/webui-per-row-errors` PR，或併入某個 UIUX 計畫的分支？
3. `.gitattributes` 採 `eol=lf` 全局統一，或對 `Makefile`/`*.bat` 保留 CRLF？建議全局 `lf`（CI/Linux 為主）。
4. 剩餘 27 個 CC≥21 熱點是否全部納入本計畫，或另開專屬「complexity-reduction」計畫分批？
