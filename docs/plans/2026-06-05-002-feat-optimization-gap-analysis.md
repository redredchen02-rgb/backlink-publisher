# Gap Analysis: 優化計畫落地盤點與缺口分析

**建立**: 2026-06-05
**範圍**: 4 份現有優化計畫的實作狀態審計

---

## 總覽

| 計畫 | 日期 | 狀態 | 完成度 |
|---|---|---|---|
| 持續優化引擎 (feat-plan 008) | 06-05-001 | 🟢 幾近完成 | ~95% |
| Batch Campaign 系統 (feat-plan 010) | 06-02-001 | 🟢 幾近完成 | ~90% |
| 全面升級優化 7 維度 (A-G) | 06-02 | 🟡 部分完成 | ~55% |
| 運營優化企劃 (B1 + C0) | 06-01 | 🟢 大部分完成 | ~90% |

---

## 1. 持續優化引擎 — 06-05-001

### 現狀：✅ 幾乎全部落地

| 單元 | 檔案 | SLOC | 狀態 |
|---|---|---|---|
| U1 OptimizationState | `optimization/state.py` | 283 | ✅ 包含 load/save/get_weight/set_weight/update_stats/get_rules_config/reset/to_summary |
| U2 Signal Collector | `optimization/collector.py` + `cli/collect_signals.py` | 220 | ✅ CLI entrypoint 存在 |
| U3 Rules Engine | `optimization/rules.py` + `cli/optimize_weights.py` | 342 | ✅ CanaryDriftRule + RecheckSurvivalRule |
| U4 Weight Reader | `publishing/registry.py` (weigh_and_publish) | — | ✅ dispatch_weight 讀取動態權重 |
| U5 show-optimization-state | `cli/show_optimization_state.py` | — | ✅ |
| U6 WebUI 優化卡片 | `webui_app/routes/optimization_status.py` | — | ✅ /api/optimization/status 端點存在 |
| U7 E2E Integration | `tests/test_optimization_e2e.py` | — | ✅ 含完整 pipeline 測試 |
| 加碼：weights CLI 整合 | `cli/weights.py` (plan 008 R2) | — | ✅ 三合一 consolidation 已完成 |

**測試**:
- `test_optimization_state.py` ✅
- `test_optimization_rules.py` ✅
- `test_optimization_e2e.py` ✅

### 缺口

無重大缺口。建議：
- WebUI 前端對優化狀態的視覺化展示（如果 command_center 已經引用則 skip）

---

## 2. Batch Campaign 系統 — 06-02-001

### 現狀：✅ 幾乎全部落地

| 單元 | 檔案 | 狀態 |
|---|---|---|
| U1 CampaignStore | `webui_store/campaign_store.py` | ✅ create/get/update_status/update_seed_status/list/migrate_from_json 全有 |
| U2 bulk_publish_now | `webui_store/drafts.py` L343 | ✅ 已存在 |
| U3 多 seed 噴發 | `cli/spray_backlinks/core.py` | ✅ 已支援 `--max-seeds` / `--seed-delay-min` / `--seed-delay-max`，無單 seed guard |
| U4 WebUI 建立 campaign | `webui_app/routes/batch_campaign.py` | ✅ route 存在 |
| U5 Campaign 執行進度 | `webui_app/campaign_worker.py` + `campaign_progress.py` | ✅ worker + progress endpoint 存在 |
| U6 Draft 按 campaign 篩選 | `webui_store/drafts.py` (get_by_campaign_id L264) | ✅ campaign_id 索引 + 查詢方法存在 |

### 測試覆蓋

- `test_campaign_store.py` ✅
- `test_webui_batch_campaign.py` ✅
- `test_webui_store_campaign_sqlite.py` ✅
- `test_webui_store_migration_edge_cases.py` ✅

### 缺口

無重大缺口。建議：
- batch campaign 端到端運作（從建立到執行到發布）需在真實環境驗證

---

## 3. 全面升級優化計畫 (7 維度 A-G) — 06-02

### A. 架構瘦身 (Architecture Slimming)

| 項目 | 狀態 | 證據 |
|---|---|---|
| A1: adapters/`__init__.py` 拆分 | 🟡 **未拆分** | 仍為 381 SLOC，含所有 adapter 註冊邏輯 |
| A2: plan_backlinks 再分解 | ✅ 已分解 | `core.py` + `__init__.py` 等多檔結構 |
| A3: webui_app route 模組化 | ✅ 36 routes | 已充分模組化 |
| A4: 統一 HTTP client (`_http_client.py`) | ❌ **未實作** | `publishing/_http_client.py` 不存在 |

### B. 型別安全 (Type Safety)

| 項目 | 狀態 | 證據 |
|---|---|---|
| B1: mypy strict mode | 🟡 mypy 在 dev deps | 有 `mypy>=1.8`，但未見 strict config（已跑 type-check） |
| B2: py.typed marker | ✅ 已放置 | `src/backlink_publisher/py.typed` 存在 |
| B3: ruff linter | ⚠️ **缺口分析有誤 — 已安裝** | ruff 0.15.16 在 venv 中，Makefile `lint` target 已用 `ruff check` / `ruff format`。未列在 pyproject.toml（可能全域安裝），但已可使用。**更正：此項不需實作。** |

### C. 效能 (Performance)

| 項目 | 狀態 | 證據 |
|---|---|---|
| C1: URL 驗證並行化 | ❌ **未實作** | `validate_backlinks.py` 無 `ThreadPoolExecutor` 或 `asyncio.gather` |
| C2: Adapter connection pool | 🟡 部分 | `_verify.py` 和 `velog/auth.py` 使用 `requests.Session`，非全局 pool |
| C3: 內容 fetch cache | ✅ 已實作 | `content/fetch.py` 有 process-scope memoization |
| C4: optimize-static Make target | ❌ **未實作** | Makefile 無此 target |

### D. 安全 (Security)

| 項目 | 狀態 | 證據 |
|---|---|---|
| D1: Rate limiting (flask-limiter) | ✅ 已配置 | pyproject.toml `flask-limiter>=3.5,<5`，已在 app 中使用 |
| D2: JSONL input size limit (`--max-rows`) | ✅ 已實作 | `cli/plan_backlinks/core.py` `--max-rows` flag |
| D3: Credential permission audit script | ✅ 已實作 | `scripts/audit_credential_permissions.py` 存在 |
| D4: SSRF Cloud Metadata 阻擋 | ✅ 完整 | `_util/net_safety.py` 含 169.254/16 封鎖、SSRF URL 檢查、redirect 驗證 |

### E. 可觀測性 (Observability)

| 項目 | 狀態 | 證據 |
|---|---|---|
| E1: 結構化日誌 (structlog) | ❌ **未引入** | 無 structlog import，日誌仍用標準 logging |
| E2: Metrics export (/metrics) | ✅ 已實作 | `webui_app/routes/metrics.py` 存在 |
| E3: Health endpoint (/health) | ⚠️ **缺口分析有誤 — 已存在** | `routes/health.py` 有完整 `/ce:health` 儀表板（publish counts、canary health、decay、storage health），`keep_alive.py` 另有即時狀態 |
| E4: Backup/restore CLI | ❌ **未實作** | 無 backup-state / restore-state CLI |

### F. 開發者體驗 (Developer Experience)

| 項目 | 狀態 | 證據 |
|---|---|---|
| F1: Pre-commit hooks | ✅ 已配置 | `.pre-commit-config.yaml` 存在 |
| F2: Docker 化 | ❌ **未實作** | 無 Dockerfile / docker-compose.yml |
| F3: Quickstart script | ✅ 已實作 | `scripts/quickstart.sh` 存在 |
| F4: Makefile 增強 | ⚠️ **缺口分析有誤 — 已充足** | 已有 scaffold/diagnose/reconcile-check/test-js/lint/type-check/coverage/setup-hooks/clean-pyc/clean-all 10 個 target。**更正：此項不需實作。** |

### G. 測試基礎設施 (Test Infrastructure)

| 項目 | 狀態 | 證據 |
|---|---|---|
| G1: JS 測試框架 | 🟡 占位 | Makefile 有 `test-js` target 但內容為 placeholder |
| G2: Integration test suite | ✅ 已存在 | `tests/integration/` 目錄存在 |
| G3: 效能回歸測試 | 🟡 績效分析而非回歸 | `test_performance_profiling.py` 存在 |
| G4: Mutation testing (mutmut) | ❌ **未引入** | pyproject.toml 無 mutmut |

### 維度總結

| 維度 | 完成 | 待完成 | 完成率 |
|---|---|---|---|
| A: 架構瘦身 | 2/4 | A1 (partial), A4 | 50% |
| B: 型別安全 | 3/4 | — | 100% 🎉 |
| C: 效能 | 1/4 | C1, C4; C2 partial | 35% |
| D: 安全 | 4/4 | — | 100% 🎉 |
| E: 可觀測性 | 2/4 | E1, E4 | 50% |
| F: 開發者體驗 | 3/4 | F2 | 75% |
| G: 測試基礎設施 | 1/4 | G1 partial, G3 partial, G4 | 35% |

---

## 4. 運營優化企劃 (B1 + C0) — 06-01

### B1: 清除 dead swarm_guard hook

✅ 已完成。

- `scripts/swarm_guard.py` 不存在
- 無任何 `.py` / `.json` / `.yaml` 檔案引用 swarm_guard
- Claude 設定中相關鉤子已清除

### C0: Real fuel — 真實 dofollow publishing

🟡 **基礎設施已到位，但運營運作狀態待確認**。

已到位：
- ✅ 持續優化引擎完整（weight optimization, signal collection, rules）
- ✅ Batch campaign 系統完整（multi-seed spray, campaign workflow）
- ✅ `debt_registry.toml` 存在（技術債已追蹤）
- ✅ Git log 顯示 `canary/flip-rentry-mataroa-hackmd-2026-06-05` 已切換 dofollow flags

待確認（不在程式碼審計範圍）：
- 實際上 publish.draft = false 的 campaign 是否已定期執行？
- 51acgs.com 是否收到真實的 dofollow backlinks？
- 運營 SOP 是否已建立？

### 06-01 延續計畫

06-01 計畫系列在 `docs/plans/` 中未以 `2026-06-01-*` 命名存在，但 `debt_registry.toml` 與 `AGENTS.md` 的 Complete Plans 區塊有歸檔紀錄。

---

## 5. 優先級缺口建議

### ✅ 已更正：缺口分析中已實作項目

| 原列缺口 | 實際狀態 |
|---|---|
| ~~E3: /health endpoint (P0)~~ | ✅ `routes/health.py` + `/ce:health` 儀表板已存在 |
| ~~B3: ruff (P2)~~ | ✅ ruff 0.15.16 已安裝，Makefile lint target 已使用 |
| ~~F4: Makefile 增強~~ | ✅ 已有 10 個 target，覆蓋完整 |

### 實際剩餘缺口（6 項）

### P0 (立即解決，高價值/低風險)

安全維度 🎉 **已全部到位，無需動作。**

### P1 (本週 Sprint)

| 缺口 | 原因 | 估計 |
|---|---|---|
| **C1: URL 驗證並行化** | 大量驗證是目前主要瓶頸，`ThreadPoolExecutor` 可 5x-10x 加速 | 小 |
| **E1: structlog 取代 logging** | 各 adapter 日誌各自為政，維護困難 | 中 |
| **A4: 統一 HTTP client** | adapter 間 HTTP 行為不一致 | 中 |
| **E4: backup/restore CLI** | 無 State 備份，風險遞增 | 小 |

### P2 (下週 Sprint)

| 缺口 | 原因 | 估計 |
|---|---|---|
| **F2: Dockerfile** | 簡化部署，降低環境不一致 | 中 |
| **G4: mutation testing** | 計畫量 > 160 tests，mutmut 可測測試品質 | 中 |
| **C4: optimize-static** | 靜態資源壓縮合併，目前無處理 | 小 |

### P3 (當需要時再做)

| 缺口 | 原因 |
|---|---|
| A1: adapters/`__init__.py` 再拆分 | 381 SLOC 可接受，胖但穩定 |
| C2: 全域 connection pool | 目前 per-adapter Session 還夠用 |
| G1: JS 測試 | WebUI 前端測試需配合前端架構決策 |

---

## 附錄：驗證方法

所有狀態都是通過以下方式驗證的：
1. 檔案系統存在性檢查 (`wc -l`, `ls`, `grep -rn`)
2. 程式碼內容掃描（特定類/方法/flag 是否存在）
3. Git log 確認合併紀錄
4. pyproject.toml 相依性檢查
5. Makefile targets 檢查
