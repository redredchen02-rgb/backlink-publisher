# GSC Integration — Setup & Operations Runbook

**狀態**: Active（Plan 2026-06-16-003 Units 1-5）

## 概述

Google Search Console (GSC) 整合提供兩條觀測路徑：
1. **Indexation check**（`probe-index`）— 偵測已發布外鏈頁面是否出現於 GSC Search Analytics
2. **Ranking snapshot**（`probe-ranking`）— 記錄目標關鍵字在 GSC 的排名位置

兩條路徑共用 `[gsc]` config（service account JSON）和 `events.db`。

## Prerequisites

- Google Cloud project 已啟用 **Google Search Console API** (v1)
- Service account 已加入 GSC property 的「完整」權限使用者
- Service account JSON 金鑰檔已下載

## Config 設定

編輯 `~/.config/backlink-publisher/config.toml`，新增 `[gsc]` section：

```toml
[gsc]
credential_path = "/path/to/service-account-key.json"
property_url = "sc-domain:example.com"
ranking_keywords = ["your-brand", "target-keyword"]
```

| 欄位 | 必填 | 說明 |
|---|---|---|
| `credential_path` | 是 | Service account JSON 金鑰的絕對路徑。檔案權限應為 `0o600` |
| `property_url` | 是 | GSC property URL。使用 `sc-domain:` 前綴代表網域層級資源，或 `https://` 前綴代表 URL 層級資源 |
| `ranking_keywords` | 否（ranking 使用時必填） | 要追蹤排名的關鍵字清單。空清單 = ranking probe 不執行（exit 0） |

## 金鑰檔權限

```bash
chmod 600 /path/to/service-account-key.json
```

GSC client 初始化時會檢查權限，不符則輸出 warning（不阻擋，但建議修正）。

## Launchd 排程

三個 GSC 相關 launchd job：

| Job | 頻率 | 執行時間 | 用途 |
|---|---|---|---|
| `com.dex.bp-probe-index` | 每日 | UTC 02:30 | 偵測外鏈頁面是否出現於 GSC |
| `com.dex.bp-probe-ranking` | 每週日 | UTC 03:30 | 快照目標關鍵字排名位置 |
| `com.dex.bp-probe-citations` | 每日 | UTC 06:00 | AI citation probe（獨立於 GSC） |

### 安裝步驟

```bash
# 1. 重新安裝套件以生成 CLI entrypoints
cd /path/to/backlink-publisher
pip install -e .

# 2. 驗證 entrypoints 可用
.venv/bin/probe-index --help
.venv/bin/probe-ranking --help

# 3. 載入 launchd jobs
launchctl load scripts/com.dex.bp-probe-index.plist
launchctl load scripts/com.dex.bp-probe-ranking.plist

# 4. 確認已載入
launchctl list | grep bp-probe-index
launchctl list | grep bp-probe-ranking

# 5. 手動觸發驗證（dry-run）
BP_PROBE_INDEX_MAX_URLS=10 .venv/bin/probe-index --max-urls 10
.venv/bin/probe-ranking
```

### 手動觸發（真實 API）

```bash
# probe-index（會消耗 GSC 配額）
.venv/bin/probe-index --probe --max-urls 10

# probe-ranking
.venv/bin/probe-ranking --probe
```

### 配額管理

- GSC Search Analytics API：每日 2,000 requests（probe-index + probe-ranking 共用）
- probe-index 每次最多查 200 URLs（`--max-urls`，plist 預設 200）
- 排程錯開（probe-index 02:30 / probe-ranking Sun 03:30）避免同一小時內耗盡配額
- 透過環境變數 `BP_PROBE_INDEX_MAX_URLS` 調整 probe-index 每次批大小

### 卸載

```bash
launchctl unload scripts/com.dex.bp-probe-index.plist
launchctl unload scripts/com.dex.bp-probe-ranking.plist
```

## 故障排除

| 症狀 | 可能原因 | 解決方式 |
|---|---|---|
| `exit 3 — requires [gsc] config` | config.toml 缺 `[gsc]` section | 確認 `credential_path` 和 `property_url` 已設定 |
| `exit 6 — GSC query failed` | 配額耗盡或 service account 權限不足 | 降低 `--max-urls` 或檢查 GSC property 權限 |
| `probe-index: no unprobed URLs` | 所有已發布頁面已在 30d 內 probe 過 | 正常（30d dedup window）；等待下次窗口 |
| `probe-ranking: no keywords configured` | `ranking_keywords` 為空或 `[gsc]` 未設定 | 在 config.toml 填入關鍵字清單 |
| `credential file mode is 0o644` | 金鑰檔權限過寬 | `chmod 600 <key.json>` |

## Log 路徑

| 檔案 | 內容 |
|---|---|
| `logs/probe-index-launchd.log` | launchd job stdout+stderr |
| `logs/probe-index.log` | CLI 輸出（wrapper 附加） |
| `logs/probe-ranking-launchd.log` | launchd job stdout+stderr |
| `logs/probe-ranking.log` | CLI 輸出（wrapper 附加） |

## 相關文件

- Plan doc: `docs/plans/2026-06-16-003-feat-gsc-indexation-ranking-loop-plan.md`
- GSC API: https://developers.google.com/webmaster-tools/v1/api_reference_index
