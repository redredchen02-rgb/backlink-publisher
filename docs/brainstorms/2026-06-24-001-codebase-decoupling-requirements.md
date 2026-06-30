---
date: 2026-06-24
topic: codebase-decoupling
---

# Codebase Decoupling & Maintainability

## Problem Frame

修改一個 bug 容易連帶破壞其他地方，發生在全部區域、無時不在。根本原因是**結構性耦合**，不是某個文件的問題：

- **巨型函數**：最高達 36 個分支（`_run_spray()`），這類函數被多處依賴，改動必然波及多點
- **CLI 作為垃圾桶**：`cli/` 目錄塞了 65 個文件，業務邏輯和 I/O 混在一起，邊界不清
- **模組合約隱形**：沒有 `__all__`，任何模組都能直接 import 任何內部符號，耦合悄悄滋長

**影響**：開發信心低、修 bug 需要大範圍人工追蹤影響面、PR review 困難。

---

## 診斷數據（從 codebase 掃描取得）

| 指標 | 現狀 |
|---|---|
| 總行數 | ~75,000 行 Python |
| 子包數 | 50+ |
| `cli/` 文件數 | 65 個文件 |
| 最高複雜度函數 | `_run_spray()` — 36 branches |
| >20 branches 函數數 | 9 個（見下表） |
| 最大文件 | `idempotency/store.py` 758 行 |

**Top 高複雜度目標（優先順序）：**

| 優先 | 文件 | 函數 | 分支數 |
|---|---|---|---|
| P1 | `cli/spray_backlinks/_engine.py:210` | `_run_spray()` | 36 |
| P1 | `keepalive/chain.py:240` | `run_cycle()` | 29 |
| P1 | `cli/plan_backlinks/_payload.py:73` | `_generate_payload()` | 29 |
| P1 | `cli/plan_backlinks/core.py:66` | `main()` | 26 |
| P2 | `cli/_seal_init.py:56` | `_handle_init()` | 26 |
| P2 | `publishing/adapters/medium_browser.py:222` | `publish()` | 25 |
| P2 | `cli/publish_backlinks/_engine.py:264` | `_publish_one_row()` | 24 |
| P3 | `publishing/session/provider.py:287` | `_load_velog_cookies()` | 24 |
| P3 | `cli/canary_seed.py:147` | `main()` | 22 |

---

## Requirements

**Phase 1 — 複雜度削減（解決最直接的耦合根源）**

- R1. 所有 P1 函數（>= 26 branches）必須拆分為職責單一的子函數，每個子函數 < 15 branches
- R2. 拆分前必須確認既有測試覆蓋該函數，拆分後測試套件零回歸（10,000+ tests 全綠）
- R3. 每個拆分動作為獨立 PR，包含：原函數的舊複雜度 vs 新複雜度說明
- R4. 更新 `complexity_budget.toml`：隨每次拆分降低對應文件的上限（不允許原地維持舊上限）
- R5. P2 函數在 Phase 1 結束後緊跟進行，驗收標準同 R1-R4

**Phase 2 — 模組邊界強化（讓耦合變得可見）**

- R6. 每個 subpackage 的 `__init__.py` 必須聲明 `__all__`，明確列出公開 API
- R7. 包內部符號（名稱以 `_` 開頭）不得被包外直接 import；現有違規在此 phase 內修復
- R8. 依賴方向須符合單向流：`cli/` → domain subpackages → `_util/`；不得出現反向依賴
- R9. 違規 import（跨層 import 內部符號）必須能被 CI 靜態偵測（可用 `import-linter` 或等效工具）

**Phase 3 — CLI 目錄重組（讓「找東西」變容易）**

- R10. `cli/` 內 65 個文件按職責分組進子目錄（建議分組：`plan/`、`publish/`、`spray/`、`admin/`、`reporting/`）
- R11. 屬於 domain 邏輯（不需要 Click/argparse 的業務邏輯）的代碼從 `cli/` 移到對應 domain subpackage
- R12. CLI 入口保持向後相容（現有命令名稱、參數、輸出格式不變）
- R13. 重組後 `cli/` 每個子目錄文件數 ≤ 15 個

---

## Success Criteria

- Top 9 個高複雜度函數全部降至 < 15 branches
- 全測試套件（10,000+ tests）Phase 1/2/3 各結束時零回歸
- `complexity_budget.toml` 上限隨拆分同步下調（可驗證的持續改進）
- CI 能靜態攔截新增的跨層 import 違規
- `cli/` 目錄文件數從 65 降到 ≤ 40（剩餘由子目錄承載）

---

## Scope Boundaries

- **不改** 任何 CLI 命令的公開接口（名稱、參數、輸出格式）
- **不改** pipeline 架構（seeds → plan → validate → publish 流程不動）
- **不加** 新功能
- **不動** WebUI（webui_app/、webui_store/ 不在本次範圍）
- Phase 3 的 import path 遷移不觸動 `tests/`（測試導入路徑一併更新，但測試邏輯不動）

---

## Key Decisions

- **拆函數優先於重組目錄**：函數複雜度是耦合根源；重組目錄只解決「找不到」，不解決「改不動」
- **Phase 順序不可反**：先有安全網（R2 測試確認）才拆函數，先有模組合約（R6-R9）才重組目錄
- **`complexity_budget.toml` 必須同步下調**：否則拆了又長回去，CI 失去約束力

---

## Dependencies / Assumptions

- 當前有兩個 **未 push** 分支：`refactor/webui-api-v1`（SDK extraction）、`perf/parallel-safe-lanes`（並行優化）；本計劃工作在這兩者 merge 到 main 之後再開始，避免 cherry-pick 衝突
- `complexity_budget.toml` 和 `monolith_budget.toml` 已存在且由 CI 強制執行 ✓

---

## Outstanding Questions

### Deferred to Planning

- [Affects R9][Needs research] `import-linter` 是否已在 CI 中，還是需要新增？有無更輕量替代方案？
- [Affects R10][Technical] CLI 子目錄重組是否需要更新 `pyproject.toml` 的 console_scripts 入口？
- [Affects R11][Technical] 哪些 `cli/` 中的函數屬於 domain 邏輯（移走）vs orchestration 邏輯（留下）的判斷標準？

---

## Next Steps

→ `/ce:plan` 進行 Phase 1 的詳細實作規劃（從 P1 高複雜度函數拆分開始）
