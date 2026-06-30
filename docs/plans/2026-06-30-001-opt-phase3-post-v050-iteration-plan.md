---
title: "Optimization Phase 3: Post-v0.5.0 全面優化迭代計畫"
date: 2026-06-30
status: draft
type: optimization
priority: high
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
  shas: []
---

# Optimization Phase 3: Post-v0.5.0 全面優化迭代計畫

## Overview（概覽）

v0.5.0 已正式發布，歷經 11 階段優化（P1–P11）+ 代碼解耦重構（Phase 2），當前指標：

| 指標 | 數值 |
|------|------|
| Source files | 439 |
| Test files | 613 |
| Mypy errors | **0**（395 source files） |
| `# noqa: C901` | **0**（all CC < 30 backstop） |
| `__all__` | **43/43 子包已加** |
| Import-linter CI | ✅ enforced |
| Dependabot | ✅ pip weekly + GHA monthly |
| Docker prod build | ✅ multi-stage, no dev-deps |
| Performance benchmarks | ✅ 3 baselines |
| 未提交變更 | ⚠️ **174 files**（+1106 / -2993） |

本計畫定位為 **v0.5.x 維護週期的最後一次集中優化迭代**，目標是在啟動 v0.6.0 功能開發前，將代碼庫推向「下一個穩定基線」。

---

## Philosophy（方針）

不同於 P1–P11 的「大刀闊斧」，Phase 3 遵循 **90/10 原則**：

- **90% 打磨**：提交積壓、補全遺漏、硬化現有機制
- **10% 新建**：只建那些能讓未來開發更安全的防護層

> 「不要為了優化而優化——只優化那些能降低未來維護成本的東西。」

---

## Phase 3 架構

```
Phase 3 ─┬─ Sprint A: Workspace Hygiene（工作區清理）
          │   A1: 174-file 積壓提交
          │   A2: ci.yml canonical 化
          │   A3: git worktree 協調
          │
          ├─ Sprint B: Frontend Stabilization（前端穩定）
          │   B1: SPA route 完整性審計
          │   B2: API v1 ↔ Flask 路由雙覆蓋測試
          │   B3: SPA error boundary / loading state
          │
          ├─ Sprint C: CI/CD Hardening（持續整合強化）
          │   C1: CI 合規矩陣驗證
          │   C2: 性能基準趨勢 (benchmark diff gate)
          │   C3: SPA build / lint CI 集成
          │
          ├─ Sprint D: Code Debt Cleanup（代碼債務清理）
          │   D1: 大測試檔拆分（目標 batch 2）
          │   D2: except Exception 縮域（目標再降 40%）
          │   D3: ko-corpus-calibration
          │
          └─ Sprint E: Documentation & Observability（文檔與可觀測性）
              E1: docs/ 目錄整理（死文檔歸檔）
              E2: AGENTS.md 同步
              E3: 運行時健康檢查增強
```

---

## Sprint A: Workspace Hygiene

### A1 — 174-file 積壓提交

**現狀**：`git status` 顯示 174 個文件有未提交改動（+1106 / -2993），包含：
- CI 配置改動（`.github/workflows/ci.yml`, `.dockerignore`, `Dockerfile`）
- 前端 SPA 頁面新增（6 個新目錄 + router/navItems）
- 大量 `__all__` / import / type annotation 修復
- 測試檔案刪減（`test_plan_backlinks.py` -1040 lines, `test_webui_three_url.py` -235）
- `webui_app/routes/` 改動（pipeline_dashboard.py 刪除, optimization_status.py 大幅改動）

**動作**：
1. 分類審閱：將 174 文件分為 CI / frontend / src / tests / webui / misc 六類
2. 驗證每類變更無遺漏依賴（先 `pytest tests/ -x` 確保全過）
3. 分批 commit（每批一個獨立語義），最後一次性 push

**驗證**：`git status` clean, `pytest tests/ -x --tb=short` 全過

### A2 — ci.yml 工作空間根副本清理

**現狀**：AGENTS.md 指出 workspace root 有一個 stale CI 副本（`./.github/workflows/ci.yml`），引用 `core/` + `|| true`，應忽略。

**動作**：
1. 確認 workspace root 的 `.github/workflows/ci.yml` 確實是過時副本
2. 如果存在，刪除它（只在 workspace root，不在 backlink-publisher/ 內）
3. 確保 canonical CI 在 `backlink-publisher/.github/workflows/ci.yml`

**驗證**：workspace root 無 `.github/workflows/`，或該文件僅是重定向註釋

### A3 — git worktree 協調

**現狀**：目前只有 `main` 分支的一個 worktree。多個 feature branch 在 remote 但無對應 worktree。

**動作**：
1. 確認所有已合併 branch 可安全刪除：
   - `fix/drafts-store-test-isolation` → check merged
   - `fix/recheck-ledger-liveness-seam` → check merged
   - `opt/bulk-modernize` → check merged
   - `refactor/u1-generate-payload` → check merged
   - `refactor/u5-publish-one-row-enhance-payload` → check merged
2. 遠端已 merged 的 branch 一併清理
3. 更新 AGENTS.md 中的 branch 列表

**驗證**：`git branch -a` 顯示合理且乾淨的 branch 列表

---

## Sprint B: Frontend Stabilization

### B1 — SPA Route 完整性審計

**現狀**：frontend/ 正在從 Flask Jinja templates 遷移到 Vue 3 SPA。router/index.ts 新增 36 行，navItems.ts 新增 5 行，6 個新 page 目錄已建立。

**動作**：
1. 對照 `webui_app/routes/` 現有所有 Flask route，列出已遷移 vs 未遷移的 SPA route
2. 為每個未遷移 route 評估遷移優先級（高：用戶常用頁面；低：admin 頁面）
3. 確保已遷移的 SPA route 與 Flask API endpoint 一一對應（無孤立 route）
4. 檢查 SPA route 的 loading / error / empty 三態處理

**交付**：SPA Route Audit Matrix（已遷移/未遷移/缺失）

### B2 — API v1 ↔ Flask Route 雙覆蓋測試

**現狀**：部分 route 已有 `test_webui_*` 測試（覆蓋 Flask 端），但 SPA 調用的 `/api/v1/` endpoint 缺乏獨立測試。

**動作**：
1. 識別所有 `/api/v1/` endpoint（從 `webui_app/api/v1/spec.py`）
2. 為每個 endpoint 確認有測試：如果 Flask route 測試已覆蓋，為 API v1 建立 alias 測試
3. 特別注意：campaign、equityLedger、keepAlive、optimizationStatus、prQueue、survival 這些新 SPA page 的 API

**交付**：API v1 endpoint → test mapping table，覆蓋率 100%

### B3 — SPA Error Boundary / Loading State 補全

**現狀**：新建的 SPA page（6 個）可能缺少完整的錯誤處理機制。

**動作**：
1. 檢查每個 page 的 Vue component 是否有 `<Suspense>` 或 loading state
2. 檢查 API 調用是否有 `.catch()` 或 try/catch + error display
3. 確保 401/403 統一跳轉到登錄頁
4. 確認 `readCsrf()` 正確用在所有寫操作（AGENTS.md: 不可緩存 module-level）

**驗證**：手動模擬網路錯誤/Token 過期，SPA 應顯示友好錯誤而非白屏

---

## Sprint C: CI/CD Hardening

### C1 — CI 合規矩陣驗證

**現狀**：CI 中有多個 job（unit, integration, lint, plan-check），但缺乏統一的合規矩陣。

**動作**：
1. 驗證 CI 是否執行以下所有檢查：
   - `pytest tests/` (unit + integration)
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

### C2 — 性能基準趨勢

**現狀**：`tests/test_benchmarks.py` 已建立 3 個基準，但無 CI diff gate。

**動作**：
1. 讓 benchmark 測試在 CI 中紀錄結果（使用 pytest-benchmark 的儲存機制）
2. 建立一個 GitHub Actions workflow 來比較 PR 與 main branch 的性能差異
3. 設定性能退化閾值（如 >10% 退化則標記）

**驗證**：CI benchmark job 成功輸出比較結果

### C3 — SPA Build / Lint CI 集成

**現狀**：frontend/ 使用 Vite + TypeScript，但 CI 中無前端建置/語法檢查。

**動作**：
1. 在 CI 中新增 `frontend-lint` job：`cd frontend && npx tsc --noEmit && npx vite build`
2. 確保 vite build 輸出到 `webui_app/spa_dist/`（Flask 的靜態文件服務路徑）
3. 驗證 CI 中 Node.js 版本（用 `actions/setup-node`）

**驗證**：CI 上的 frontend-lint job 綠色通過

---

## Sprint D: Code Debt Cleanup

### D1 — 大測試檔拆分（Batch 2）

**現狀**：complexity_budget.toml 中仍有幾個大測試檔：

| 測試檔 | 當前 SLOC | Ceiling | 優先級 |
|--------|-----------|---------|--------|
| test_webui_three_url.py | ~1152 | 1190 | medium |
| test_cli_plan_check.py | ~1126 | 1160 | medium |
| test_config_three_url.py | ~851 | 890 | low |
| test_publish_backlinks.py | ~821 | 860 | low |
| test_work_scraper.py | ~696 | 730 | low |

**動作**：
1. P0: 拆分 `test_webui_three_url.py`（最大殘留大測試檔）：
   - 按 URL 類型拆分（valid URLs / invalid URLs / edge cases）
   - 或按路由拆分（sites_save_three_url / merge / migration）
2. P1: 拆分 `test_cli_plan_check.py`：
   - 按 plan-check 子功能拆分（frontmatter / claims / schema / git）
3. 使用與 `test_plan_backlinks.py` 相同的 split-and-slim 模式

**驗證**：拆分後 max test file SLOC < 600，所有測試通過

### D2 — `except Exception:` 縮域（Target: 再降 40%）

**現狀**：~133 個 bare `except Exception:`（從 142 降下 9 個）。

**策略**：不追求消滅全部（adapters 確需 broad catch），而是針對高價值目標：

1. **Batch 1 — 非 adapter 文件**（優先級高）：
   - `events/` 中的 broad catch：可縮小為 `except (ValueError, KeyError):`
   - `_util/` 中的工具函數：多數可指定具體異常
   - `idempotency/store.py`：SQLite 操作可指定 `sqlite3.Error`

2. **Batch 2 — Adapter 中的安全 catch**（優先級中）：
   - 那些只做 `log.warning` + `continue` 的：可指定為 `(RequestException, Timeout, ConnectionError)`
   - 保留真正需要 `except Exception` 的兜底捕獲

**驗證**：`grep -rn "except Exception:" src/backlink_publisher/ --include='*.py' | wc -l` → ≤80

### D3 — ko-corpus-calibration

**現狀**：Korean 語言檢測閾值 `RATIO_THRESHOLD=0.30` 是未經校準的 v1 默認值。

**動作**：
1. 收集 ~50 篇真實韓文文章（Naver Blog, Tistory, Korean news）
2. 在測試環境中運行語言檢測，記錄檢測率
3. 如果 < 90% 檢測率，調整閾值
4. 添加 corpus 校準測試（測試已知韓文文本能被正確檢測）

**驗證**：校準後的閾值在測試 corpus 上達到 ≥95% 檢測率，無假陽性

---

## Sprint E: Documentation & Observability

### E1 — docs/ 目錄整理（死文檔歸檔）

**現狀**：docs/ 包含 15 個子目錄 + 多個根文件，其中部分已過時或重複。

**動作**：
1. 審閱每個 doc 文件，判斷是否仍活躍（active-docs.md 可作為參考）
2. 過時文件移到 `docs/_archive/`（附時間戳記 + 取代文件鏈接）
3. 確認 root README.md 指向 docs/ 的正確路徑
4. 特別處理：
   - `OPTIMIZATION_REPORT.md` (root) → `docs/optimization-history.md` 已取代
   - `OPTIMIZATION_COMPLETE_REPORT.md` (root) → 同上
   - `FINAL_OPTIMIZATION_REPORT.md` (root) → 同上
   - `docs/ideation/` → 如果全是 brainstorming 且無後續 action，歸檔
   - `docs/spike-notes/` → 如果對應 spike 已關閉，歸檔

**驗證**：`docs/` 根目錄只有活躍文檔，過時文件都在 `_archive/`

### E2 — AGENTS.md 同步

**現狀**：workspace root 的 AGENTS.md 是最新的，但需要確保它與 `backlink-publisher/AGENTS.md` 同步。

**動作**：
1. 比較兩個 AGENTS.md，確認金規則一致
2. 更新 Phase 3 的相關 section（如有需要）
3. 檢查 CI 配置部分是否反映當前 CI 狀態
4. 確保「Branches and launchers」部分反映最新的 branch 架構

**驗證**：兩個 AGENTS.md 關鍵內容一致，無矛盾

### E3 — 運行時健康檢查增強

**現狀**：已有 `/health` endpoint（200/503），健康指標存於 `webui_app/health_metrics.py`。

**動作**：
1. 為 SPA 新增前端健康檢查：`/api/v1/health` 或 SPA 特有 ping
2. 確保 `health_metrics.ranking_trend()` 和 `indexation_status()` 在無 GSC 數據時代優雅降級（不炸 500）
3. 考慮加入 pipeline 運行時長監控（上次成功 pipeline 時間戳）

**驗證**：`curl localhost:8888/health` 返回 200 + 合理 body

---

## Execution Order & Timeline

```
Sprint A (Workspace Hygiene) ───────────────── 3-4 天
  A1 ──> A2 (獨立) ──> A3 (依賴 A1 完成後驗證)

Sprint B (Frontend Stabilization) ──────────── 5-7 天
  B1 ──> B2 ──> B3

Sprint C (CI/CD Hardening) ─────────────────── 3-4 天
  C1 ──> C2 (獨立) ──> C3 (獨立)

Sprint D (Code Debt Cleanup) ───────────────── 4-5 天
  D1 ──> D2 (獨立) ──> D3 (獨立)

Sprint E (Documentation) ───────────────────── 2-3 天
  E1 ──> E2 (依賴 E1) ──> E3 (獨立)

──────────────────────────────────────────────
總計：約 17-23 天
```

### 依賴圖

```
A1 ──────────────────────────────────┐
  ├── A3                              │
  ├── D1 (積壓含大檔拆分)              │
  ├── D2 (積壓含 exception 修復)      │
  └── E2 (積壓含 AGENTS.md 更新)      │
                                       │
B1 ──> B2 ──> B3                       │
C1 ──> C2 ──> C3                       │
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

---

## Success Criteria（成功指標）

| 指標 | 當前 | 目標 |
|------|------|------|
| Uncommitted files | 174 | **0** |
| git status | dirty | **clean** |
| Workspace root stale CI | 可能存在 | **deleted** |
| `except Exception:` 數量 | ~133 | **≤80** |
| 最大測試檔 SLOC | ~1152 | **≤600** |
| SPA route coverage | 部分遷移 | **審計完成 + 缺失已記錄** |
| API v1 test coverage | 不完整 | **100% endpoint → test** |
| CI benchmark gate | 無 | **有 diff comparison** |
| SPA CI build | 無 | **有 tsc + vite build** |
| docs/ 活躍度 | 含過時文件 | **只保留活躍文檔** |
| Korean calibration | uncalibrated | **校準 + 測試覆蓋** |
| 運行時健康檢查 | Flask only | **SPA 也有 /health** |
| `pytest tests/ -x` | 應全過 | **全過** |

---

## Risk Register

| 風險 | 可能性 | 影響 | 緩解措施 |
|------|--------|------|----------|
| 174 文件積壓中遺漏關鍵變更 | 中 | 高 | 分類審閱 + 先跑完整測試 |
| SPA 遷移中斷向後相容性 | 低 | 高 | SPA 和 Flask templates 並存期間不做 breaking change |
| CI benchmark diff gate 太嚴格 | 中 | 低 | 初始閾值設為 20%，後續調緊 |
| except Exception 縮域引入 regression | 低 | 中 | 修改後先跑完整測試套件 |
| Korean calibration 無代表性 corpus | 中 | 低 | 從 Naver/Tistory 收集至少 50 篇 |

---

## Appendix A: 174-file 分類一覽（初步）

| 類別 | 文件數 | 代表性變更 |
|------|--------|-----------|
| CI/Docker | 4 | ci.yml, Dockerfile, .dockerignore, pyproject.toml |
| Frontend SPA | ~8 | router/index.ts, navItems.ts, 6 新 page dirs |
| `src/` (__all__ + import) | ~60 | 43 子包加 __all__, import 重新排序 |
| `src/` (bugfix/refactor) | ~30 | checkpoint.py, config/loader.py, events/reconcile.py |
| tests/ | ~15 | test_plan_backlinks 拆分, test_webui_three_url 瘦身 |
| webui_app/ | ~12 | pipeline_dashboard.py 刪除, routes 優化 |
| webui_store/ | ~3 | channel_status.py, sqlite_base.py |
| docs + AGENTS | ~5 | ARCHITECTURE.md, CHANGELOG.md, optimization-history.md |
| **Total** | **~174** | |
