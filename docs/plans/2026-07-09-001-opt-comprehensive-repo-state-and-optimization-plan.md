---
title: "opt: 全面專案狀態收斂與優化計畫（落地已完成工作 + 倉庫衛生 + 填補缺口）"
type: optimization
status: active
date: 2026-07-09
updated: 2026-07-13
priority: high
claims: {}
---

# opt: 全面專案狀態收斂與優化計畫

## Overview

本計畫回應使用者要求「分析專案庫狀況，提出全面優化建議計畫」。這是**第三次**提出相同請求：
- 第一次（2026-07-07）產出 `2026-07-07-003-opt-backend-code-health-optimization-plan.md`，已執行並合併。
- 第二次（2026-07-09）產出本計畫初版。
- 第三次（2026-07-13）重新盤點後**就地更新本計畫**：Phase A/B/C 的多數項目已在
  2026-07-09 當天透過 `chore/repo-state-cleanup` 分支執行並合併（merge commit `587ddfe2`），
  但計畫文件未同步勾選。本次更新標記已完成項、以 2026-07-13 即時量測修訂仍開放項，並加入新發現。

核心論點（更新後仍成立，對象換了一批）：

> **當前最大的優化槓桿依然是「落地與收斂」而非寫新程式碼：（1）把又一次攤在 `main` 上的
> WIP（operation-progress + error-bug-report，含兩份未追蹤的 active 計畫文件）分流到分支，
> （2）清掉殘餘的分支/worktree/死目錄，（3）修復 Windows 本地 mypy 的 cp950 crash
> （新退化，比錯誤數量問題更根本），然後才是剩餘 29 個複雜度熱點與 SQLite 連線複用。**

## Current Repo State Snapshot（2026-07-13 即時量測）

### A. 上一輪（2026-07-09 初版）已落地的項目
- `opt/backend-code-health` 已以 `--no-ff` 合併（`93365059`），分支 0 ahead，可刪。
- 倉庫衛生：egg-info 取消追蹤（`954812db`）、`.gitattributes` eol=lf（`33c2ccf4`）、
  根目錄 dump/報告已收整（`52de9b8b`）、`bp-wsgi-prod` 與 `.worktrees/feat/windows-portable-package`
  已 prune。
- 效能：routing 效能基準落地（`d25a89d3`，`.benchmarks/Windows-CPython-3.11-64bit/` 已有基線）、
  `http_form_post` per-host `requests.Session` pool（`2269b14e`）、LLM HTTP session 複用 +
  mypy 改以 Linux platform 檢查（`cf656fab`）。
- 舊 per-row-errors WIP 已提交為 baseline（`9591b43e`，注：直接進了 `main` 而非分支——與
  計畫 A2 的原設計不同，屬既成事實）。
- `fix/production-wsgi-entrypoint`（#87）、`feat/windows-portable-package`（#88）已合併。

### B. 仍開放 / 新出現的問題（2026-07-13 實測）
1. **`main` 又有新一批未提交 WIP**：25 個已修改檔（+226/−214，前端 Vue/CSS/模板）加約 20 個
   未追蹤檔（`webui_store/operation_store.py`、`webui_app/api/v1/operations.py`、
   `webui_app/services/operation_worker.py`、`frontend/src/pages/Operations/`、
   `src/backlink_publisher/cli/report_bug/`、`webui_app/api/v1/error_report_bundle.py` + 6 個測試檔）。
   分屬兩份 **active 但本身未追蹤** 的計畫文件：
   `docs/plans/2026-07-09-webui-operation-progress-plan.md` 與
   `docs/plans/2026-07-09-002-feat-error-bug-report-system-plan.md`。計畫文件不在版控中，有遺失風險。
2. **Windows 本地 mypy 完全無法執行（新退化）**：`mypy.ini` 含非 ASCII 字元，
   `configparser` 在 cp950（繁中 Windows）locale 下讀取即拋
   `UnicodeDecodeError: 'cp950' codec can't decode byte 0xe2`。`cf656fab` 的 Linux-platform
   對策被此問題整個蓋掉——不是錯誤數量問題，是跑不起來。
3. **已合併分支未刪**：`opt/backend-code-health`、`fix/production-wsgi-entrypoint`、
   `feat/w8-spa-shell-upgrade`（已 merged 但仍被 `bp-w8-shell` worktree 掛著）。
   `feat/windows-portable-package` 內容經 #88 進入 main（squash，需確認後刪）。
4. **殘餘死目錄**：`bp-fix-main-mypy/` 已不是有效 git checkout（worktree metadata 已 prune，
   `git status` 直接 fatal），純死目錄；`nul` 裝置檔仍實體存在於 workspace 根。
5. **複雜度熱點**：radon 實測 **29 個函式 CC≥21**（其中 2 個在未追蹤的 `report_bug` 新碼）。
   Top：`cli/plan_backlinks/core.py::main` D30、`config/loader.py::load_config` D28、
   `cli/report_bug/_build.py::render_markdown` D28、`cli/_seal_init.py::_handle_init` D27、
   `cli/spray/canary_seed.py::main` D27、`gap/engine.py::plan_gap` D26、
   `cli/publish_backlinks/__init__.py::_prepare_publish_rows` D26、
   `cli/plan_backlinks/_zh_short.py::_plan_zh_short_row` D26。
6. **SQLite 每操作新連線（H2）仍普遍**：`events/store.py`、`idempotency/store.py`、
   `publishing/_throttle.py` 等 10+ 處 `sqlite3.connect` per-call。尚無量測證明它是瓶頸。
7. **平行發佈引擎（H1/C2）未落地**：`cli/publish_backlinks/` 無任何並發原語，
   仍歸 `2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`（active）認領。

## 與既有計畫的交叉參照（避免重複認領）

| 既有計畫 | 狀態 | 本計畫的關係 |
|---|---|---|
| `2026-07-07-003-opt-backend-code-health` | completed（已合併） | 已落地，無後續 |
| `2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan` | active | 平行發佈引擎（H1）由其認領；本計畫只追蹤 |
| `2026-07-06-005-opt-webui-uiux-comprehensive` | active | WebUI 層由其認領；本計畫不碰 |
| `2026-07-09-webui-operation-progress-plan` | active（**未追蹤**） | 其 WIP 攤在 main 上——本計畫 A3 負責分流，不做其內容 |
| `2026-07-09-002-feat-error-bug-report-system-plan` | active（**未追蹤**） | 同上（A3） |

## Implementation Plan（分四階段，依賴順序執行）

### Phase A — 落地已完成的工作（最高 ROI / 最低風險）
- [x] **A1: 審查並合併 `opt/backend-code-health`** — 已於 2026-07-09 完成（`93365059`，`--no-ff`）。
- [x] **A2: 將 `main` 上的 WIP 移出** — 以變體形式完成：per-row-errors WIP 直接提交為
  baseline（`9591b43e`）。偏離原設計（未走分支），記錄為既成事實。
- [x] **A3: 分流新一批 `main` WIP（operation-progress + error-bug-report）** —
  完成（2026-07-13）。實際分流為**三**個分支（歸屬盤點發現 25 個修改檔屬 wave-2 W3 token 清掃，
  而非兩功能）：`feat/error-bug-report`（+blueprint 註冊修復，25/25 測試綠）、
  `feat/operation-progress`（+`operation_store` _LazyStore 門面與 blueprint 註冊修復，17/17 測試綠）、
  `opt/webui-uiux-wave2-tokens`（+修復 4 處殘留 `var(--radius)` 消費者）。main 工作樹已淨空。
  - 動作：
    1. 先單獨提交三份純文件（兩份 plan doc + `docs/solutions/ui-bugs/notifications-js-*.md`）
       到 `main`——純文件、零風險，消除計畫文件遺失風險。
    2. 把 operation-progress 功能檔（`operation_store.py`、`operations.py`、`operation_worker.py`、
       `frontend/src/{api/operations.ts,components/OperationProgress.vue,components/StatusBadge.vue,composables/useOperation.ts,stores/operations.ts,pages/Operations/}`、
       3 個 operation 測試）移到 `feat/operation-progress` 分支。
    3. 把 error-bug-report 功能檔（`cli/report_bug/`、`error_report_bundle.py`、3 個 report_bug 測試）
       移到 `feat/error-bug-report` 分支。
    4. 25 個已修改的前端/CSS/模板檔逐一歸屬（多數應屬 operation-progress 的 UI 接線；
       執行時以 `git diff` 逐檔判斷，混合改動用 `git add -p` 拆分）。
  - 為何：多 session 併發環境下把功能工作攤在 `main` 是已記錄的教訓（`docs/solutions/`）；
    兩份 active 計畫文件甚至不在版控中。
  - 風險：檔案歸屬判斷錯誤 → 以測試檔綠燈驗證每個分支自洽（分支上 `pytest` 對應測試檔須過）。

### Phase B — 倉庫衛生（解鎖乾淨開發迴圈）
- [x] **B1: 取消追蹤 egg-info** — 完成（`954812db`）。
- [x] **B2: 新增 `.gitattributes`（eol=lf）** — 完成（`33c2ccf4`）。工作樹仍有 CRLF 殘留檔屬
  過渡期正常；可選在某次乾淨工作樹時 `git add --renormalize .` 一次收尾。
- [x] **B3: 修剪過期 worktree（第一批）** — `bp-wsgi-prod`、`.worktrees/feat/windows-portable-package`
  已移除。
- [x] **B3': 殘餘 worktree / 死目錄收尾** — 完成（2026-07-13）。
  `bp-w8-shell` 內發現 4 檔未提交 WIP（+176/−18，2026-07-07 停更）→ 先提交到
  `feat/w8-spa-shell-upgrade`（`ed482165`，該分支現有 1 個未合併 commit，**保留分支**）再移除 worktree；
  `bp-fix-main-mypy/` 實為空目錄，已刪。
- [x] **B4': 根目錄與分支收尾** — 完成（2026-07-13）。
  已刪分支：`opt/backend-code-health`、`fix/production-wsgi-entrypoint`、
  `feat/windows-portable-package`（以 `git diff main <branch> -- <packaging paths>` 驗證零差異後 `-D`）。
  `nul` 已刪（PowerShell `\\?\` 擴展路徑語法）；workspace 根 `__pycache__/` 已刪。

### Phase C — 效能地基（讓後續優化可被守護）
- [x] **C1: 建立效能回歸基準（第一塊）** — routing benchmark 已落地（`d25a89d3`），
  `pytest-benchmark` 已入 dev deps，`.benchmarks/` 有基線。
- [x] **C1': 擴充基準涵蓋面** — 完成（2026-07-13）。盤點發現 `tests/test_benchmarks.py`
  已有 plan（單 row + 100 row）、publish dry-run（50 row）、JSONL、webui_store 熱路徑、
  link-attr verifier 基線；本輪補上缺的 `sdk/api`（`PipelineAPI.plan()` seam 開銷,
  與 kernel 基線分離使退化可歸因）。10 個基準全綠。
- [ ] **C2: 追蹤平行發佈引擎落地**（歸 `v060-uiux-pipeline-upgrade-plan` 認領，本計畫不動手）——
  實測確認 `_engine.py` 仍為順序執行；H1 假說仍須 cProfile 實測證實後再動。
- [x] **C3: 連線複用小優化** — `http_form_post` per-host Session pool（`2269b14e`）+
  LLM HTTP session 複用（`cf656fab`）完成。
- [x] **C4（原 H2）: SQLite 連線複用評估** — 已量測，**決定不做**（2026-07-13）。
  微基準（1000-row 表，200 次/項）：connect_only 0.079ms、connect+query 0.192ms vs
  query_reused 0.027ms、connect+write 0.227ms vs write_reused 0.052ms。
  每操作省 ~0.15ms，比管線每 row 的網路/LLM 呼叫低 3-4 個數量級；引入連線快取的
  跨執行緒/鎖生命週期/_refresh_paths 複雜度風險不對稱。依「量測證明值得才改」守則收案。

### Phase D — 殘餘品質債
- [ ] **D1: 29 個 CC≥21 熱點（2026-07-13 實測）** — 小步萃取重構，先攻 Top 8（見 Snapshot B5）。
  每改一處同步核對 `complexity_budget.toml`；調 ceiling 須同 PR 附 ≥80 字 rationale。
  ⚠️ 2026-07-13 暫緩：另一 session 正於 `fix/audit-batch1` / `fix/windows-test-suite-triage`
  修 adapters/events 等區域的 bug——與 D1 目標檔高度重疊，等其落地後再開工以免重構壓修復。
- [x] **D2': 修復 mypy cp950 crash** — 完成（2026-07-13，`7edd7326` + CI 引用修正 `0d01d2d9`，
  已合併 main）。採方案 (a) 遷入 `pyproject.toml [tool.mypy]` 並刪 `mypy.ini`；同步修掉 INI 引號
  `platform = "linux"` 的字面值問題與 `ci.yml`/`AGENTS.md` 的 `--config-file mypy.ini` 引用。
  驗證：本地 `python -m mypy src/backlink_publisher` → **Success: no issues found in 457 source files**。
- [x] **D3: 清 `Unused "type: ignore"`** — 隨 D2' 歸零：`warn_unused_ignores = true` 之下 mypy
  全綠、零警告（先前的 ~5 處已在 `cf656fab` 輪清掉）。
- [ ] **D4: 維持 debt_registry 時效**（持續性原則，不設完成點）。

## Execution Safeguards（沿用 `docs/solutions/` 制度性教訓）

- **每個 unit 開工前**：`git -C backlink-publisher status --short` + `git worktree list` 確認乾淨、
  無其他 session 活躍（本 workspace 有共用目錄併發 session 的已知風險）。
- **A3 完成前不得開始任何會碰工作樹的 unit**——當前 `main` 上的 WIP 是活的功能工作，
  任何 checkout/stash 操作都可能干擾另一個 session。
- **一律使用 worktree 隔離**，絕不在 `main` 上直接做修改性工作。
- **所有數字（CC 熱點數、檔案清單）皆為 2026-07-13 快照**，執行前務必重新量測。
- **預算守護**：任何 SLOC/CC 改動即核對 `monolith_budget.toml`/`complexity_budget.toml`。

## Sequencing / Dependencies

```
A3 (WIP 分流) ──→ B3'/B4' (衛生收尾) ──→ D1 (複雜度熱點)
     │
     └──→ D2' (mypy crash 修復) ──→ D3 (unused ignores)
C1' (基準擴充) ──→ C4 (SQLite 量測後決策)；C2 僅追蹤
```
- **A3 是唯一的硬前置**：工作樹不乾淨之前，B/D 的任何檔案操作都有風險。
- 優先順序：A3 > D2'（開發迴圈紅燈）> B3'/B4' > C1' > D1 > C4 > D3。

## Open Questions / Decisions Needed

### Resolved During Planning（2026-07-13 更新輪）
- 合併方式：已採 `--no-ff`（既成事實，`93365059`、`587ddfe2`）。
- `.gitattributes` 策略：已採全局 `eol=lf`（`33c2ccf4`）。
- mypy 修法方向:建議遷 `pyproject.toml [tool.mypy]`(見 D2')。

### Deferred to Implementation
1. A3 的 25 個已修改檔逐一歸屬（operation-progress vs error-bug-report vs 無主雜項）——
   須執行時 `git diff` 逐檔判斷，計畫階段不預判。
2. `bp-w8-shell` 是否仍有進行中的 wave-2 工作（`opt/webui-uiux-wave2` 分支存在）——
   remove 前現場確認。
3. C4 是否動手取決於 C1' 量測結果——量測前不承諾。
4. 剩餘 CC 熱點是否全數納入本計畫或分批另開——先攻 Top 8 後視進度決定。
