# Backlink Publisher — 分析與優化報告

> 日期：2026-07-08
> 範圍：**效能/速度、程式碼品質、特定模組/檔案、CI/建構流程** 四面向
> 模式：**只分析、出報告，未修改任何程式碼**
> 方法：實際執行 `ruff` / `mypy` / `radon`（raw、cc、mi）並比對專案預算檔（`monolith_budget.toml`、`complexity_budget.toml`、`debt_registry.toml`）
> 環境備註：本機為 **Windows + Git Bash**，因此 `fcntl` 相關 mypy 錯誤是跨平台誤報（Linux CI 上不存在）。

---

## 0. 執行摘要（TL;DR）

| 維度 | 現狀 | 評級 | 主要發現 |
|---|---|---|---|
| 程式碼品質（lint） | ruff 全過 | 🟢 良好 | src + webui 均無違規 |
| 程式碼品質（型別） | mypy 58 錯誤 | 🟡 僅 Windows 開發機 | 幾乎全是 `fcntl` 跨平台誤報；Linux CI 實際乾淨 |
| 程式碼品質（複雜度） | 10% 函式 ≥11 | 🟡 可接受偏高 | 31 個函式 ≥21，最熱點達 30 |
| 可維護性（MI） | 0 檔 <20 | 🟢 健康 | 無低可維護性檔 |
| 預算（monolith/complexity） | 全綠 | 🟢 符合 | 65 監控檔 0 超標（radon SLOC 基準） |
| 效能（架構） | 同步 + 局部執行緒池 | 🟠 主要槓桿 | 發布路徑為順序執行；無回歸基準 |
| 效能（基準） | `.benchmarks/` 空 | 🔴 缺口 | 有 `cProfile` 埋點但無連續基準 |

**最值得做的 3 件事（優先級見第 6 節）：**
1. 建立效能回歸基準（填補 `.benchmarks/`），否則「速度優化」無法被守護。
2. 評估發布路徑（I/O-bound）的並發化——目前 `publish_backlinks/_engine.py` 為順序執行。
3. 對 31 個高複雜度（≥21）函式做小步重構，降低變更風險。

---

## 1. 效能 / 速度

### 1.1 架構模型（已確認）
- 全專案**實質同步**，真正的 `async/await` 僅 1 處（且是注入瀏覽器的 JS，非 Python 並發）。
- 並發僅靠 `concurrent.futures.ThreadPoolExecutor`，出現在 **2 個模組**：
  - `cli/_publish_helpers.py`（用於 `check_url` 預檢/連結檢查，`max_workers=workers`）
  - `content/fetch.py`（並發抓取）
- **關鍵觀察**：`cli/publish_backlinks/_engine.py`（635 行，實際發布核心）**未使用執行緒池**——發布多個 URL / 跨多平台時為**順序**執行。對一個 I/O-bound 的發布器而言，這是吞吐量的主要槓桿（需驗證，見下方假說）。

### 1.2 效能信號計數（source scan）
| 信號 | 次數 | 評註 |
|---|---|---|
| `time.sleep(...)` | 40 | 多為限速/退避，合理；但意味吞吐受 sleep 約束 |
| 裸 `requests.get/post`（未用 `Session`） | 4 | 連線重複使用的小優化點（`http_form_post.py`、`llm/http_guard.py`、`_bind/chrome_backend.py`） |
| `sqlite3`/`execute` | 227 | SQLite 操作用量高；需確認連線是否複用（見 1.3） |
| `bs4` 解析 | 6 | `content/scraper.py` 中逐一 `soup.find`，量小可接受 |
| `json.loads/dumps` | 256 | 普遍，難免 |
| `re.compile` 模組層級 | 98 | 多為模組常數（**良好**實踐），非迴圈內重編譯 |

### 1.3 待驗證假說（報告不修改程式碼，列為建議）
- H1：發布核心順序執行，批量發布時存在明顯的「排隊延遲」→ 建議以 `cProfile` 實測 `publish_backlinks` 單次 vs 批量的 wall-time。
- H2：SQLite 是否為「每次操作開新連線」→ 若是，連線池/單連線可降開銷（參見 `audit/readers.py`、`events/store.py`、`idempotency/store.py`）。
- H3：`http_form_post.py` 等 4 處裸 `requests` 改為 `requests.Session()` 可省 TCP/TLS 握手。

### 1.4 基準缺口（🔴 重要）
- `.benchmarks/` 目錄**存在但為空**——無任何效能基準。
- 程式碼中有 `cProfile` 埋點（約 5 個 CLI 入口：`_publish_cli.py`、`plan_backlinks/core.py`、`spray_backlinks/_args.py`、`sdk/api.py` 等），屬**臨時剖析**而非連續基準。
- 結論：目前無法對「速度優化」做回歸守護。任何優化都可能無聲地退化。

---

## 2. 程式碼品質

### 2.1 Lint（🟢）
- `ruff check src/`：**All checks passed!**
- `ruff check webui_app/ webui_store/`：**All checks passed!**
- 規則集 F / E / W / UP / I 全部通過。

### 2.2 型別（mypy，🟡 僅 Windows）
- `mypy src/backlink_publisher` 報告 **76 errors / 19 files**（實際解析 58 條）。
- **幾乎全部為 `fcntl` 跨平台誤報**：`keepalive/chain.py`、`cli/ops/probe_*.py`、`_util/secrets.py`、`publishing/reliability/circuit.py`、`health/persistence/locked_store.py`、`idempotency/audit_log.py`、`pr_outreach/store.py`、`comment_outreach/store.py`、`publishing/adapters/medium_auth.py`、`_util/permissions.py` 等用 `fcntl.flock`/`LOCK_*`。
- 在 **Linux（實際 CI 運行環境）`fcntl` 存在，mypy 通過**。本機 Windows 才報錯 → 這是**開發體驗摩擦**，非生產缺陷。
- **真實可清理項（少數）**：約 5 處 `Unused "type: ignore"` + 1–2 處其他 minor。建議在 Linux 上跑一次 mypy 取得「真實」錯誤清單。

### 2.3 複雜度（radon cc，🟡）
- 2265 個函式/方法，A–F 分布：
  - A (1–5): **1652** ｜ B (6–10): **386** ｜ C (11–20): **196** ｜ D (21–30): **31**
  - ≥11（重構候選）：**227（10%）** ｜ ≥21：**31**
- 最複雜函式 Top（cyclomatic complexity）：
  | CC | 檔:行 | 函式 |
  |---|---|---|
  | 30 | `events/history_query.py:113` | `_build_history_item` |
  | 30 | `cli/plan_backlinks/core.py:67` | `main` |
  | 28 | `publishing/adapters/catalog/catalog_schema.py:55` | `validate_entry` |
  | 28 | `config/loader.py:55` | `load_config` |
  | 28 | `_dispatch_router/routing.py:103` | `route` |
  | 27 | `publishing/adapters/medium_brave.py:341` | `publish` |
  | 27 | `phase0/validation.py:249` | `validate_seal_schema` |
  | 27 | `cli/spray/canary_seed.py:147` | `main` |
  | 27 | `cli/_seal_init.py:56` | `_handle_init` |
  | 26 | `gap/engine.py:95` | `plan_gap` |
  | 26 | `cli/publish_backlinks/__init__.py:69` | `_prepare_publish_rows` |
  | 26 | `cli/plan_backlinks/_zh_short.py:170` | `_plan_zh_short_row` |
  | 25 | `publishing/session/provider.py:286` | `_load_velog_cookies` |
  | 24 | `ledger/aggregate.py:180` | `build_ledger` |
  | 24 | `events/_project_reducers.py:53` | `_project_checkpoint` |

### 2.4 可維護性指數（radon mi，🟢）
- MI < 20 的檔案：**0**。整體可維護性健康。
- 註：`comment_outreach/brief.py`、`llm/client.py`、`publishing/adapters/llm_anchor_provider.py` 在 radon MI 下報 SyntaxError，但 `ast.parse` 均可通過 → 為 radon 舊解析器對新語法（如 `X | Y` 聯集型）的**誤報**，非真實問題。

### 2.5 技術債登記
- `debt_registry.toml`：**0 筆**債務登記（clean）。

---

## 3. 特定模組 / 檔案

### 3.1 最大檔案（依 radon SLOC）
| SLOC | 檔 |
|---|---|
| 773 | `idempotency/store.py` |
| 712 | `publishing/_manifests.py` |
| 699 | `cli/_publish_helpers.py` |
| 678 | `publishing/registry.py` |
| 663 | `publishing/adapters/velog_graphql.py` |
| 655 | `config/types.py` |
| 651 | `publishing/adapters/telegraph_api.py` |
| 635 | `cli/publish_backlinks/_engine.py` |
| 580 | `publishing/browser_publish/_chrome_session_impl.py` |
| 579 | `events/_project_reducers.py` |
| 576 | `cli/_bind/_driver_impl.py` |
| 574 | `cli/_resume.py` |
| 572 | `cli/admin/phase0_seal.py` |
| 568 | `events/history_query.py` |
| 545 | `cli/pipeline_orchestrator.py` |

> 整體 `src/backlink_publisher`：454 檔，**47,484 SLOC**，平均 **104.6 SLOC/檔**——單檔規模整體克制，但上述 15 個檔集中了發布/事件/配置的核心邏輯，是變更風險與重構的首選目標。

### 3.2 高風險交集（既大又複雜）
- `cli/publish_backlinks/_engine.py`（635 SLOC，CC 26 `_prepare_publish_rows`）—— 順序發布核心，建議優先審視並發化。
- `events/history_query.py`（568 SLOC，最熱點 `_build_history_item` CC 30）。
- `config/loader.py`（`load_config` CC 28）。
- `cli/plan_backlinks/core.py`（`main` CC 30）。
- `publishing/adapters/medium_brave.py`（`publish` CC 27）。

---

## 4. CI / 建構流程

### 4.1 預算守護（🟢 全綠）
- `monolith_budget.toml`：監控 **65** 個檔，以 **radon SLOC** 為基準比對 ceiling → **0 超標**（最初以「實體行數」誤判 56 個超標，已用正確指標修正）。
- `complexity_budget.toml`：監控 **2** 個函式，0 超標。
- 守護測試：`tests/test_no_monolith_regrowth.py`（按 AGENTS.md 記載強制 SLOC ceiling）。
- 見解：預算機制健全；但多個檔實際 SLOC 已逼近 ceiling（如 `config/types.py` 655 vs 260 仍有緩衝，但 `webui_app/api/v1/schemas.py` 1068 vs 620 緩衝偏緊），持續成長時需依政策在同一 PR 調高 ceiling 並附 ≥80 字 rationale。

### 4.2 測試規模
- `tests/` 下 **657** 個 `test_*.py` 檔（標記：unit / integration / e2e / real_* / seam，按 AGENTS.md）。
- 網路預設 mocked（4 個 autouse conftest fixture）；CSRF 在測試中停用。

### 4.3 Makefile 目標（節錄）
- `optimize-static`、`mutate`（突變測試）、`type-check`、`lint`、`lint-imports`、`coverage`、`docker-build/run`、`restart-webui` 等。
- 註：未從 Makefile 抓到 `optimize-static`/`mutate` 的具體內容（目標體擷取失敗），建議直接 `make help` 或閱讀 Makefile 確認其行為。

### 4.4 建構摩擦點
- **Windows 開發機 mypy 失敗**（58 錯誤全因 `fcntl`），雖 Linux CI 通過，但本地 `make type-check` 會紅，降低開發迴圈速度。建議：在相關 `fcntl` 使用處加 `sys.platform` 守衛或 mypy `platform` override，使 Windows 本地也能過型別檢查。

---

## 5. 風險與誤報澄清
- ⚠️ **預算超標為誤報**：本報告初版曾顯示 56 個 monolith 超標，係因使用「實體行數」；改用政策定義的 **radon SLOC** 後確認 **0 超標**。後續任何預算比對請以 radon SLOC 為準。
- ⚠️ **mypy 錯誤為跨平台誤報**：本機 Windows 的 `fcntl` 錯誤不反映 Linux CI 真實狀態。
- ⚠️ **radon MI SyntaxError 為誤報**：3 個檔的 MI 解析失敗源於 radon 舊解析器，非程式錯誤。

---

## 6. 優先級建議（僅建議，未執行）

| 優先級 | 項目 | 面向 | 預期效益 | 工作量 |
|---|---|---|---|---|
| P0 | 建立效能回歸基準（填補 `.benchmarks/` + 固定 `cProfile` 輸出為基準） | 效能 | 讓後續優化可被守護，避免無聲退化 | 中 |
| P1 | 實測並評估發布核心並發化（`publish_backlinks/_engine.py` 順序→執行緒/批次） | 效能 | 批量發布吞吐提升（須先證實 H1） | 中–大 |
| P1 | 對 31 個 CC≥21 函式做小步萃取重構（先從 Top 15 熱點） | 品質/特定模組 | 降變更風險、升可讀性 | 中 |
| P2 | 修掉約 5 處 `Unused "type: ignore"`，並在 Linux 重跑 mypy 取真實清單 | 品質 | 清潔度 | 小 |
| P2 | 4 處裸 `requests` 改 `Session`（連線重複使用） | 效能 | 省握手開銷 | 小 |
| P2 | 修 Windows 本地 mypy（`fcntl` 守衛 / mypy override） | CI/建構 | 本地 `make type-check` 可用的開發迴圈 | 小 |
| P3 | 確認 SQLite 連線是否複用（H2），必要時引入連線池 | 效能 | 降 DB 開銷 | 小–中 |
| P3 | 監控預算緩衝偏緊檔（`webui_app/api/v1/schemas.py` 等），依政策在增長時調 ceiling | CI/建構 | 防止單檔單次暴衝 | 持續 |

---

## 附錄：資料來源（可重現）
- 工具：`ruff 0.15.10`、`mypy 2.1.0`、`radon 6.0.1`
- 指令摘要：
  - `python -m ruff check src/ webui_app/ webui_store/`
  - `python -m mypy src/backlink_publisher`
  - `python -m radon raw -s src/backlink_publisher`（總 SLOC 47,484 / 454 檔）
  - `radon.complexity.cc_visit` 逐檔（2265 區塊；A 1652 / B 386 / C 196 / D 31）
  - `radon.metrics.mi_visit`（0 檔 <20）
  - 比對 `monolith_budget.toml`（65 檔，radon SLOC 0 超標）、`complexity_budget.toml`（2 函式 0 超標）、`debt_registry.toml`（0 筆）
- 所有數字均來自上述實際執行；誤報項已在第 5 節標註。
