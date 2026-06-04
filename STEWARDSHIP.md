# STEWARDSHIP.md — 领域 stewardship 模型

> **結論：Stewardship 是「知情與把關」，不是「獨佔編輯權」。任何人都可以改任何檔案，但 steward 對其領域的變更有 awareness 責任、review 責任、以及 debt 條目維護責任。**

---

## 1. Stewardship 的定義

Stewardship 不是檔案所有權。一個領域的 steward 負責三件事：

1. **Awareness** — 關注其領域的變更，確保自己知道正在發生什麼
2. **Review gate** — 對涉及該領域的 PR 提供 review，重點不是審美而是防護已知的坑、合約約束、以及架構一致性
3. **Debt 條目維護** — 在其領域內發現結構性 debt 時，寫入 `docs/debt/` 或更新現有條目；steward 是 debt 的第一發現者和記錄者，不一定是修復者

Stewardship 不賦予：
- 獨佔寫入權限（沒有 `CODEOWNERS` 式的強制 gates）
- 決策否決權（技術爭議走正常 RFC 流程）
- 超出該領域的管轄權

## 2. 當前領域與 Steward

以下為當前認領的領域和 steward。**`[unassigned]` 表示尚未有人認領。**

| 領域 | Steward | 覆蓋範圍 |
|------|---------|----------|
| **Adapter config 標準化** | `[unassigned]` | `config/` 下的 schema 定義、`save_config` taxonomy、各 adapter 的 TOML 規範、`config.example.toml` |
| **WebUI store SQLite** | `[unassigned]` | `webui_store/` 中的 persistence 層、migration 腳本、concurrency 安全 |
| **CDP wiring** | `[unassigned]` | CDP bridge (`cdp/`)、Playwright-steered publishing 路徑、browser session 管理 |
| **Invariant hardening** | `[unassigned]` | monolith budget (`monolith_budget.toml`)、dofollow gate (`test_adapter_dofollow_gate.py`)、adapter manifest contract (`test_manifest_contract.py`)、no-orphan-guard 測試 |
| **Platform adapter registry** | `[unassigned]` | `publishing/registry.py`、`register()` 模式、`_REJECTED_PLATFORMS`、20+ adapter |
| **CLI entrypoints** | `[unassigned]` | 23 個 CLI 命令的一致性（argparse、exit code 合約、stdout/stderr 規範） |
| **Config lifecycle** | `[unassigned]` | `save_config` 五分支 taxonomy、credential 存儲與輪換、`config-history/` 滾動快照 |
| **Channel binding** | `[unassigned]` | `cli/_bind/`、Playwright binding flow、`CHANNELS` 封閉集合、`AuthExpiredError` 路由 |
| **Test infrastructure** (Wave 1) | `[unassigned]` | pytest 基礎設施、conftest fixtures、network mock、`pytest-env`、CI workflow |
| **Observability** (Wave 2) | `[unassigned]` | events pipeline (`events/`)、RECON 日誌規範、`canary-health.json`、channel-status |
| **Debt governance** (Wave 3) | `[unassigned]` | budget 執行、deprecation hygiene、`docs/debt/` 維護、技術債追蹤 |

## 3. 輪換制度

- **頻率**：每季一次（3 月、6 月、9 月、12 月）
- **機制**：季初由任意 steward 發起輪換討論（GitHub issue），重新分配領域
- **紀錄**：每次輪換在本文件下方 changelog 追加一筆，包含日期、變更摘要
- **原則**：鼓勵跨領域輪換以建立全局理解；不強制輪換，同一人可以連任

### Changelog

| 日期 | 變更 |
|------|------|
| 2026-06-04 | 初始版本，所有領域 `[unassigned]` |

## 4. 如何成為 Steward

**任何人都可以成為 steward — 不需要頭銜或權限。**

流程：
1. 選擇一個或多個 `[unassigned]` 的領域（或既有 steward 願意交接的領域）
2. 開一個 PR 修改本文件，將你的 GitHub 用戶名填入對應欄位
3. 在 PR 描述中簡述你對該領域的理解（2-3 句即可）
4. PR 合併後即正式成為 steward

既有 steward 可以透過同一個 PR 流程主動交接領域。

## 5. 期望

Steward 的時間投入很小，但要求一致性：

- **Review**：每 sprint 至少 review 1 筆涉及你領域的 PR（如果該 sprint 沒有相關 PR，則免）
- **Response**：被 `@mention` 在 domain-tagged issue 中時，**3 個工作日內**回應（「收到了，週五前看」也算）
- **Debt**：發現 debt 時有義務寫下條目（不需要當下修復）
- **缺席**：如果連續兩個 sprint 無法履行上述期望，請在 #stewardship 頻道或 PR 中通知，讓領域可以重新分配

> Stewardship 是輕量的共同責任模型。三個期望中最重要的不是 review 數量，而是 **awareness** — 知道你的領域正在發生什麼。
