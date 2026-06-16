---
title: "feat: GSC 雙面接入 — Indexation 確認 + Ranking Feedback Loop"
type: feat
status: completed
date: 2026-06-16
origin: docs/brainstorms/2026-06-16-gsc-indexation-ranking-loop-requirements.md
deepened: 2026-06-16
---

# feat: GSC 雙面接入 — Indexation 確認 + Ranking Feedback Loop

## Overview

新增兩條 GSC（Google Search Console）整合路徑，關閉 Q3 路線圖的最大盲點：
1. **Indexation 確認**：偵測已發布的外鏈頁面是否出現於 Google Search Analytics（proxy for indexation），結果回寫 events.db。
2. **Ranking Feedback Loop**：在 plan-backlinks 建鏈前抓一次 GSC keyword 排名 baseline（-60d~-30d 窗口），建鏈後定期抓近 30d 快照，讓 operator 看到非重疊的前後排名比較。

兩條路徑共用 `GscConfig`（service account JSON）、`events.db`、launchd 排程，並在 `/ce:health` 面板集中顯示。

## Problem Frame

v0.4.0 驗收鏈：`publish → URL alive → citation (Perplexity) → referral (GA4)`

盲點：
- 無法分辨「外鏈頁面被 Google 收錄」vs「只是 URL 活著」
- 無法量化「建了這批鏈後，目標關鍵字排名移動了多少」

（詳見 origin：`docs/brainstorms/2026-06-16-gsc-indexation-ranking-loop-requirements.md`）

## Requirements Trace

- R1. `probe-index` CLI：透過 GSC Search Analytics `page` 維度查詢，判斷外鏈頁面是否有曝光（`has_impressions`），結果回寫 events.db（`gsc.page_signal` event kind）
- R2. `gsc.page_signal` event kind 新增至 events/kinds.py（欄位：`page_url`、`has_impressions`、`coverage_state`、`checked_at`）
- R3. `/ce:health` 新增索引狀態面板（顯示「出現於 GSC」vs「未出現於 GSC」，附清單）
- R5. `probe-ranking` CLI：GSC Search Analytics keyword ranking snapshot（近 30d 窗口）
- R6. `ranking.snapshot` event kind
- R7. plan-backlinks 建鏈前自動觸發 baseline ranking snapshot（advisory，不阻斷建鏈）
- R8. `/ce:health` 新增排名趨勢面板（baseline vs. latest，delta ↑↓）
- R9. `probe-index` 加入每日 launchd plist
- R10. `probe-ranking` 加入每週 launchd plist

## Scope Boundaries

- 不使用 GSC URL Inspection API（service account 不支援）
- 不做趨勢折線圖（前端選型未解）
- 關鍵字清單由 operator 手動設定於 config.toml，不自動發現
- **不做 IndexNow ping**（第三方平台頁面 operator 無法控制根域名 key file，ping 會靜默失敗，移除 R4）
- probe-index 每批 ≤200 URL，單日總量控制在 GSC 每日 2,000 req 配額內
- `verify_health.py` BaseSqliteStore 遷移不在本輪範圍

## Context & Research

### Relevant Code and Patterns

- **CLI 結構範本**：`src/backlink_publisher/cli/probe_citations.py`（495 行）— `fcntl.flock` 防重疊、`--dry-run` 預設開啟、`--probe` 真打 API、stdout=JSONL、`_log.recon()` 輸出、`run_id=uuid4()`
- **Google Auth 範本**：`src/backlink_publisher/click_track/engine.py:103–128`— `service_account.Credentials.from_service_account_file(path, scopes=[...])` → `googleapiclient.discovery.build("searchconsole","v1",...)`
- **Config dataclass 範本**：`src/backlink_publisher/config/types.py`— `ClickTrackConfig` 的 `dataclass` 欄位設計（credential_path + 功能旗標）
- **events.db 寫入**：`src/backlink_publisher/events/store.py:169`— `EventStore().append(KIND, payload, target_url=..., run_id=...)`；缺必要欄位自動隔離、回傳 -1
- **KINDS / REQUIRED_FIELDS**：`src/backlink_publisher/events/kinds.py`— 兩處都要改，CI gate 擋（R2/R6）
- **Health panel 新增**：`webui_app/routes/health.py:231–249`— `_g_cache("key", fn)` + `_render(tmpl, ..., key=value)`
- **Health metric 函式**：`webui_app/health_metrics.py:233–314`— `store.query(sql, params)` + `json_extract`，仿 `geo_citation_share`
- **launchd 範本**：`scripts/com.dex.bp-citations.plist`— shell wrapper + `StartCalendarInterval` + `RunAtLoad: false`
- **plan-backlinks 掛鉤點**：`src/backlink_publisher/cli/plan_backlinks/core.py:238`（`plan_rows()` 呼叫前）

### Institutional Learnings

- **RECON log level**：GSC 同步結果、IndexNow 送出狀態屬 operator 必看信號，使用 `_log.recon(...)` 而非 `_log.info()`（`docs/solutions/best-practices/recon-log-level-for-always-on-signals-2026-05-15.md`）
- **SLOC 預算先測後動**：新 CLI 寫完即跑 `radon raw -s`；超出 ceiling 需在同一 PR 調高並附 rationale ≥80 chars（`docs/solutions/best-practices/extract-cli-epilogue-block-2026-05-26.md`）
- **WebUI config 讀取用 `_g_cache`**：read-path handler 必須 `_g_cache('config', load_config)`，write-path 直接 `load_config()`（`docs/solutions/best-practices/webui-config-request-cache-governance-2026-06-03.md`）
- **Credentials 缺失需降級**：GSC credential 不存在時 CLI exit 非零 + 明確錯誤；WebUI panel 顯示「未設定」而非 500（`docs/solutions/best-practices/probe-then-pivot-when-api-unverifiable-2026-05-20.md`）
- **launchd retry 設計**：失敗後依賴下次排程週期重跑，不需 resume 機制（LITE scope accepted deferral）

## Key Technical Decisions

- **Indexation 推斷方式**：用 Search Analytics `page` 維度查詢（service account 支援）而非 URL Inspection API（需 user OAuth），以維持現有認證架構一致性（see origin）
- **`google-api-python-client` 依賴已存在**：`pyproject.toml` 已有 `google-api-python-client>=2.196,<3`（滿足 GSC 需求），Unit 1 **不需要修改** `pyproject.toml`
- **`GscConfig` dataclass 獨立於 `ClickTrackConfig`**：兩者雖同用 service account，但 scopes 不同（GA4 vs. Search Console）；欄位：`credential_path`、`property_url`（`sc-domain:example.com`）、`ranking_keywords`。`GscClient.search_analytics_query()` 的 `site_url` 參數即為 `GscConfig.property_url`，命名在 API 層保留 GSC 術語，config 層統一用 `property_url`
- **IndexNow 移除**：R4 確認移除。IndexNow 需要 operator 在目標頁面根域名放置 key file，外鏈頁面（Mastodon、Blogger、WriteFreely 等）為第三方平台，ping 會靜默失敗，無實際效果（3 審查員一致）
- **ranking 時間窗口非重疊設計**：`snapshot_baseline()`（plan-backlinks 建鏈前呼叫）使用固定窗口 `startDate=-60d, endDate=-30d`（建鏈前 30d 基準）；`probe-ranking` CLI 常規快照使用近 30d（`startDate=-30d, endDate=today`）；兩窗口不重疊，`ranking_trend()` 比較最舊 baseline vs. 最新快照，delta 具統計意義
- **`gsc.page_signal` 語義**：`has_impressions: bool` 代表「過去 30d 是否出現於 GSC Search Analytics」，不等於「Google 已索引」；UI 標籤用「出現於 GSC」而非「已索引」
- **plan-backlinks baseline 鉤子為 advisory**：包在 `try/except Exception:` + `_log.debug("gsc baseline hook skipped: %s", exc, exc_info=True)`（非裸 `pass`，保留可追蹤性但不產生常態噪音）；同 PR 修復現有 canary nudge 裸 `pass`（`core.py:285`）
- **WebUI panel 走現有 `/ce:health` 路由，但強制登記 monolith_budget.toml**：health.py 目前 427 SLOC 且未登記在 budget 中；GSC 面板新增約 60-90 SLOC 後需在同 PR 將 health.py 加入 `monolith_budget.toml`（ceiling = 現有 SLOC + GSC 新增 + 30 緩衝，rationale ≥80 字元）
- **`gsc/__init__.py` 不做頂層 import**：`import googleapiclient` 不能出現在 `gsc/` 模組的頂層，必須在函式內 lazy import，避免 `import backlink_publisher.gsc` 觸發 discovery cache 初始化

## Open Questions

### Resolved During Planning

- **URL Inspection API 可用性**：service account 不支援 → 改用 Search Analytics `page` 維度（see Key Technical Decisions）
- **GSC 配額競爭**：probe-index（每日）與 probe-ranking（每週）用不同 GSC endpoint（SearchAnalytics.query），配額池獨立；每日排程錯開 probe-citations 執行時間
- **advisory hook 失敗模式**：`_log.debug()` 取代裸 `pass`，credential 缺失 vs. 暫時失敗均用 debug level，不阻斷建鏈流程
- **health.py monolith 風險**：retrofit 可行但必須同 PR 登記 `monolith_budget.toml`（architecture audit 發現）

### Deferred to Implementation

- ~~`json_extract` 可用性~~ **已確認**：`health_metrics.py` 的 `geo_citation_share()` 已在生產環境使用 `json_extract`，Unit 6 可直接沿用同樣的 SQL 模式。Unit 6 測試中加一行斷言 `conn.execute("SELECT json_extract('{\"k\":1}', '$.k')").fetchone() == (1,)` 即可驗收
- `probe-index` 分批策略：URL 超過 200 個時的 batch 切割邏輯（按 target_url 分組 vs. 全域 FIFO）
- `config/types.py` ceiling 精確值：實作時跑 `radon raw -s config/types.py` 確認新增 `GscConfig` 後的 SLOC，同 PR 調整 ceiling（預估 ceiling 從 260 → 290）

## High-Level Technical Design

> *此為方向性指引，非實作規格。實作時應以 repo 現有模式為準。*

```
┌─────────────────────────────────────────────────────┐
│  plan-backlinks/core.py                             │
│  → try: snapshot_baseline(rows, cfg)  [advisory]   │
└──────────────────┬──────────────────────────────────┘
                   │ writes ranking.snapshot to events.db
                   ▼
┌─────────────────────────────────────────────────────┐
│  src/backlink_publisher/gsc/                        │
│  ├── client.py   GscClient(credentials, property)  │
│  ├── indexation.py  check_indexed(urls) → dict      │
│  └── ranking.py     snapshot(keywords) → list       │
└──────┬────────────────────────┬───────────────────┘
       │                        │
       ▼                        ▼
  probe-index CLI          probe-ranking CLI
  (daily launchd)          (weekly launchd)
       │
       └── writes gsc.page_signal → events.db
                                                │
                                                ▼
                                     writes ranking.snapshot → events.db

events.db ──────────────────────────────────────────►
                     health_metrics.py
                     ├── indexation_status()
                     └── ranking_trend()
                                │
                                ▼
                     /ce:health panel (routes/health.py)
```

## Implementation Units

```mermaid
TB
  U1[U1: GscConfig + client.py] --> U2[U2: events kinds]
  U2 --> U3[U3: probe-index CLI]
  U2 --> U4[U4: probe-ranking CLI]
  U3 --> U5[U5: launchd plists]
  U4 --> U5
  U3 --> U6[U6: health panels]
  U4 --> U6
  U4 --> U7[U7: plan-backlinks hook]
```

- [ ] **Unit 1: GscConfig + gsc/client.py**

**Goal:** 建立 GSC 認證層與 Search Analytics API 客戶端，供 probe-index 和 probe-ranking 共用

**Requirements:** R1, R5

**Dependencies:** 無

**Files:**
- Create: `src/backlink_publisher/gsc/__init__.py`
- Create: `src/backlink_publisher/gsc/client.py`
- Modify: `src/backlink_publisher/config/types.py`（新增 `GscConfig` dataclass）
- ~~Modify: `pyproject.toml`（依賴已存在 >=2.196，無需修改）~~
- Test: `tests/gsc/test_client.py`

**Approach:**
- `GscConfig`：`credential_path: str | None`（None 時走 `GOOGLE_APPLICATION_CREDENTIALS`）、`property_url: str | None`（`sc-domain:example.com`）、`ranking_keywords: list[str]`（空清單 = 功能停用）
- `GscClient.__init__`：載入 service account JSON 前，先確認檔案 mode 為 0o600，不符合則 `_log.warning("gsc: credential file mode is %o, expected 0o600")`（對齊 LLM key 的 guard 模式）；接著呼叫 `service_account.Credentials.from_service_account_file(path, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])`；credentials 缺失時 raise `ExternalServiceError`（讓 CLI 捕獲後 exit 3）
- `GscClient.search_analytics_query(site_url, request_body)`：薄包裝，回傳原始 API response；4xx 轉成 `ExternalServiceError`
- **Import safety**：`googleapiclient.discovery.build(...)` 必須在方法內呼叫，不出現在模組頂層，確保 `import backlink_publisher.gsc` 不觸發 discovery cache 初始化

**Execution note:** 實作前先讀 `old/0511 backlink/src/gsc_client.py`（178 行），評估 lazy import 結構、search_analytics 查詢格式、403 處理、0o600 guard 等可直接移植的段落，避免重複發明

**Patterns to follow:**
- `old/0511 backlink/src/gsc_client.py`（現有 GSC client 原型）
- `click_track/engine.py:103–128`（service account auth 模式）
- `_util/errors.py`（`ExternalServiceError` 的使用）

**Test scenarios:**
- Happy path：mock service account file → `GscClient` 成功建構，`search_analytics_query` 回傳 mock response
- Edge case：`credential_path=None` + `GOOGLE_APPLICATION_CREDENTIALS` 未設定 → raise `ExternalServiceError`
- Error path：API 回 403 → `ExternalServiceError` 包裝原始 message
- Edge case：`property_url=None` → `GscConfig` 建構成功，但 `GscClient` 初始化時 raise `ValueError`

**Verification:**
- `from backlink_publisher.gsc.client import GscClient` 不 raise ImportError
- mock credentials 下 `GscClient` 可建構（pytest with `unittest.mock`）

---

- [ ] **Unit 2: events/kinds.py — 新增兩個 event kinds**

**Goal:** 在 `events/kinds.py` 登記 `gsc.page_signal` 和 `ranking.snapshot` 兩個 event kind，讓 CI gate 通過

**Requirements:** R2, R6

**Dependencies:** Unit 1（GscConfig 確認欄位名稱後才定 REQUIRED_FIELDS）

**Files:**
- Modify: `src/backlink_publisher/events/kinds.py`
- Test: `tests/events/test_kinds.py`（現有測試，確認不 break）

**Approach:**
- 新增兩個 `Final` 常數
- 加入 `KINDS` frozenset
- 加入 `REQUIRED_FIELDS` dict：
  - `gsc.page_signal`：`frozenset({"page_url", "has_impressions", "coverage_state", "checked_at"})` — 語義：「過去 30d 是否出現於 GSC Search Analytics」，不代表已索引
  - `ranking.snapshot`：`frozenset({"keyword", "avg_position", "impressions", "clicks", "date_range_start", "date_range_end"})`

**Patterns to follow:**
- `events/kinds.py` 現有 event kind 登記方式（KINDS frozenset + REQUIRED_FIELDS dict 兩處都改）

**Test scenarios:**
- Happy path：`GSC_PAGE_SIGNAL in KINDS` 為 True（`GSC_PAGE_SIGNAL = "gsc.page_signal"`）
- Happy path：`RANKING_SNAPSHOT in KINDS` 為 True
- Happy path：`REQUIRED_FIELDS[GSC_PAGE_SIGNAL]` 包含 `"page_url"` 和 `"has_impressions"`
- Integration：`EventStore().append(GSC_PAGE_SIGNAL, valid_payload, ...)` 回傳正整數（不被隔離）
- Error path：`EventStore().append(GSC_PAGE_SIGNAL, {"page_url": "x"}, ...)` 回傳 -1（缺 `has_impressions` 欄位）

**Verification:**
- 現有 `tests/events/` 全部通過
- `store.append(INDEXATION_CHECKED, {...全欄位...})` 回傳 > 0

---

- [ ] **Unit 3: probe-index CLI**

**Goal:** 實作 `probe-index` CLI，從 events.db 取已發布但未 probe 的外鏈頁面，透過 GSC Search Analytics 查詢是否有曝光，結果回寫 `gsc.page_signal` event

**Requirements:** R1

**Dependencies:** Unit 1（GscClient）、Unit 2（event kinds）

**Files:**
- Create: `src/backlink_publisher/cli/probe_index.py`
- Modify: `pyproject.toml`（`probe-index = "backlink_publisher.cli.probe_index:main"`）
- Test: `tests/cli/test_probe_index.py`

**Approach:**
- 結構完全仿 `cli/probe_citations.py`：`fcntl.flock` 防重疊、`--dry-run`（預設）/ `--probe`（真打 API）、stdout=JSONL diagnostics、`_log.recon()` 輸出
- 取 URL 邏輯：`EventStore().query(...)` 取 `published_confirmed` 事件，排除 **30 天內已有 `indexation.checked` 的 URL**（rolling window — `checked_at IS NULL OR checked_at < datetime('now', '-30 days')`）；每批 ≤200 URL。30d 前已 probe 的 URL 重新進入候選，以偵測後續索引狀態變化
- GSC 查詢：`GscClient.search_analytics_query(site_url, {dimensions:["page"], startDate:-30d, endDate:today})` → 提取出現在回應中的 page URL 清單 → 比對批次 URL → 標記 `has_impressions=True/False`
- 回寫：`EventStore().append(GSC_PAGE_SIGNAL, {...}, target_url=..., run_id=...)`；EventStore 使用現有 WAL + timeout 模式（不另開 SQLite 連線）
- **SQL 安全**：所有從 GSC API 回應取得的 URL（`rows[].keys[]`）寫入 SQLite 時，必須使用 `?` 佔位符參數化查詢，禁止任何形式的字串拼接
- Credentials 缺失（`GscConfig` 未設定）→ exit 3 + stderr 說明

**Patterns to follow:**
- `cli/probe_citations.py`（完整 CLI 範本）
- `_util/errors.py ExternalServiceError` 捕獲模式

**Test scenarios:**
- Happy path：mock GscClient 回傳 3 個 URL（其中 2 個有曝光）→ events.db 寫入 3 筆 `gsc.page_signal`、2 筆 `has_impressions=True`、1 筆 `has_impressions=False`
- Edge case：`--dry-run`（預設）不打 API、不寫 events.db，stdout 印 dry-run summary
- Edge case：events.db 無未確認 URL → 正常退出（exit 0），`_log.recon()` 輸出「nothing to probe」
- Error path：GscConfig 缺失 → exit 3 + stderr 明確錯誤訊息
- Error path：GSC API 回 429（rate limit）→ `ExternalServiceError` 捕獲 → exit 6（advisory），不 crash
**Verification:**
- `probe-index --dry-run` 在 GSC 未設定環境 exit 0
- `probe-index --probe` 在 mock credential 環境寫入正確 `gsc.page_signal` events

---

- [ ] **Unit 4: probe-ranking CLI**

**Goal:** 實作 `probe-ranking` CLI，抓 GSC Search Analytics keyword ranking snapshot 並存入 events.db

**Requirements:** R5

**Dependencies:** Unit 1（GscClient）、Unit 2（event kinds）

**Files:**
- Create: `src/backlink_publisher/cli/probe_ranking.py`
- Modify: `pyproject.toml`（`probe-ranking = "backlink_publisher.cli.probe_ranking:main"`）
- Test: `tests/cli/test_probe_ranking.py`

**Approach:**
- 仿 probe_citations.py 結構
- 關鍵字清單來自 `GscConfig.ranking_keywords`（空清單 → exit 0 + recon「no keywords configured」）
- GSC 查詢（常規快照）：`dimensions:["query"]`、`startDate: 30d ago`、`endDate: today`（近 30d 不重疊窗口），`dimensionFilterGroups` 篩 `keyword in ranking_keywords`
- 每個 keyword 寫一筆 `ranking.snapshot` event：`avg_position`、`impressions`、`clicks`、`date_range_start`、`date_range_end`（date_range 精確記錄，供 ranking_trend() 比對窗口用）
- **Baseline 窗口（由 Unit 7 呼叫）**：`snapshot_baseline()` 使用 `startDate=-60d, endDate=-30d`（建鏈前 30d 基準，與常規快照窗口不重疊）
- `target_url` 欄位用 `GscConfig.property_url`

**Patterns to follow:**
- `cli/probe_citations.py`

**Test scenarios:**
- Happy path：2 個 keyword，mock GSC 回傳 position 資料 → events.db 寫入 2 筆 `ranking.snapshot`
- Edge case：`ranking_keywords=[]` → exit 0，recon 說「no keywords」
- Edge case：某 keyword 在 GSC 無資料（0 impressions）→ 仍寫入一筆（position=None 或 0）
- Error path：GscConfig 缺失 → exit 3
- Error path：GSC API 500 → exit 6（advisory）

**Verification:**
- `probe-ranking --dry-run` 在未設定環境 exit 0
- mock 環境下 events.db 寫入 `ranking.snapshot` 筆數正確

---

- [ ] **Unit 5: launchd plists + shell wrappers**

**Goal:** 新增 probe-index（每日）和 probe-ranking（每週）的 launchd 排程，讓兩個 CLI 在 cron 環境自動執行

**Requirements:** R9, R10

**Dependencies:** Unit 3、Unit 4

**Files:**
- Create: `scripts/com.dex.bp-probe-index.plist`
- Create: `scripts/com.dex.bp-probe-ranking.plist`
- Create: `scripts/run-probe-index-periodic.sh`
- Create: `scripts/run-probe-ranking-periodic.sh`
- Modify: `scripts/install-launchd.sh`（若有安裝腳本）或在 runbook 中記錄手動安裝步驟

**Approach:**
- 複製 `scripts/com.dex.bp-citations.plist` 結構：shell wrapper、`StartCalendarInterval`、`RunAtLoad: false`、`WorkingDirectory`
- probe-index：每日 UTC 02:30（probe-citations 03:00 之前，不競爭 GSC 配額）
- probe-ranking：每週日 UTC 03:30
- shell wrapper：`--probe` flag（不 dry-run），log 到 `logs/probe-index.log` / `logs/probe-ranking.log`

**Test expectation:** none — launchd plist 是設定檔，無可測行為；runbook 中記錄 `launchctl load` 驗收步驟

**Verification:**
- `plutil -lint scripts/com.dex.bp-probe-index.plist` 通過
- `launchctl list | grep bp-probe-index` 顯示 job（install runbook 跑完後）

---

- [ ] **Unit 6: /ce:health 索引狀態 + 排名趨勢面板**

**Goal:** 在 `/ce:health` WebUI 頁面新增兩個面板：索引狀態面板（未/已索引統計 + 清單）和排名趨勢面板（baseline vs. latest delta）

**Requirements:** R3, R8

**Dependencies:** Unit 2（event kinds），Unit 3、Unit 4 需有資料才能展示（但 UI 在無資料時顯示「尚無快照」）

**Files:**
- Modify: `webui_app/health_metrics.py`（新增 `indexation_status()` 和 `ranking_trend()` 函式）
- Modify: `webui_app/routes/health.py`（新增 `_g_cache` 呼叫 + template 傳參）
- Modify: `webui_app/templates/health.html`（新增兩個面板 HTML block）
- Test: `tests/webui/test_health_metrics.py`（現有 or 新建）

**Approach:**
- `health_metrics.indexation_status(store)` → 呼叫 `store.query(sql, (GSC_PAGE_SIGNAL, since_90d))` 按 `target_url` 分組，讀 `has_impressions` 欄位，回傳 `[{target_url, total, gsc_appeared_count, gsc_absent_count}]`；空清單時回傳 `[]`
- `health_metrics.ranking_trend(store)` → 取每個 keyword 最舊（baseline）和最新（latest）`ranking.snapshot`，計算 position delta；無資料時回傳 `[]`
- `routes/health.py`：`indexation = _g_cache("indexation_panel", lambda: indexation_status(EventStore()))` → 傳入 `_render(...)` kwargs
- `health.html`：
  - GSC 出現狀態面板：顯示 total/出現於 GSC/未出現於 GSC 摘要（不用「已索引/未索引」標籤）；未出現 > 0 時展開清單
  - 排名趨勢面板：per-keyword table，`↑` 綠 / `↓` 紅 delta；空資料時顯示「尚無排名快照 — 執行 probe-ranking 後顯示」
- 前端：純 server-render，無 JS 狀態（保持與現有 health 面板一致）

**Patterns to follow:**
- `health_metrics.geo_citation_share()`（`store.query` + `json_extract` SQL 模式）
- `routes/health.py:231–249`（`_g_cache` + `_render` kwargs 模式）
- 前端面板樣式仿現有 glass-card 設計

**Test scenarios:**
- Happy path：events.db 有 5 筆 `gsc.page_signal`（3 筆 has_impressions=True, 2 筆 False）→ `indexation_status()` 回傳正確 counts
- Happy path：events.db 有 baseline snapshot（date_range: -60d~-30d）+ follow-up snapshot（date_range: recent 30d），keyword 排名從 18 → 11 → `ranking_trend()` 回傳 delta=-7（非重疊窗口比較正確）
- Edge case：events.db 無 `gsc.page_signal` 事件 → 回傳 `[]`，面板顯示「尚無 GSC 資料」而非 500
- Edge case：某 keyword 只有 baseline，無 follow-up → delta 顯示 `—`（待更新）
- Error path：`store.query()` 拋出例外 → health.py 捕獲 → 面板顯示 error state（不 500）
- Integration：GET /ce:health 回應 200、HTML 含 indexation panel element

**Verification:**
- `GET /ce:health` 在 GSC 資料缺失時回應 200（不 500）
- `indexation_status()` 單元測試通過（in-memory SQLite）

---

- [ ] **Unit 7: plan-backlinks baseline ranking hook**

**Goal:** 在 plan-backlinks/core.py 建鏈流程前，advisory 觸發 ranking baseline snapshot（GSC 未設定時靜默跳過）

**Requirements:** R7

**Dependencies:** Unit 4（probe_ranking 的 snapshot 邏輯）

**Files:**
- Modify: `src/backlink_publisher/cli/plan_backlinks/core.py`（line 238 附近，`plan_rows()` 呼叫前）
- Test: `tests/cli/plan_backlinks/test_core.py`（確認 hook 不阻斷主流程）

**Approach:**
- 在 `plan_rows()` 呼叫前加入：
  ```
  try:
      from backlink_publisher.gsc.ranking import snapshot_baseline
      snapshot_baseline(rows, cfg)
  except Exception as exc:
      _log.debug("gsc baseline hook skipped: %s", exc, exc_info=True)
  ```
- `gsc/ranking.py` 提供 `snapshot_baseline(rows, cfg)` 函式，內部讀 `GscConfig`、呼叫 `GscClient`、寫 events.db
- GSC 未設定（`GscConfig.property_url` 為 None）→ 函式立即 return，不拋例外

**Execution note:** 確認 SLOC 預算：修改 `core.py` 前跑 `radon raw -s src/backlink_publisher/cli/plan_backlinks/core.py` 確認 headroom

**Patterns to follow:**
- `cli/plan_backlinks/core.py` 現有 advisory try/except 模式（若有）；若無，參考 `keepalive/chain.py` 的非阻塞 side-effect 模式

**Test scenarios:**
- Happy path：mock `snapshot_baseline` 成功 → `plan_rows()` 照常被呼叫
- Edge case：`snapshot_baseline` 拋出 `ExternalServiceError` → `plan_rows()` 仍被呼叫（hook 不阻斷）
- Edge case：`snapshot_baseline` 拋出任意 `Exception` → `plan_rows()` 仍被呼叫
- Edge case：`GscConfig` 未設定 → `snapshot_baseline` 立即 return，沒有任何 API 呼叫

**Verification:**
- 現有 `tests/cli/plan_backlinks/test_core.py` 全部通過（hook 不 break 現有邏輯）
- `plan-backlinks` 在 GSC 未設定環境照常運行

## System-Wide Impact

- **Interaction graph**：`plan_backlinks/core.py` 新增 advisory lazy import（`gsc.ranking`）；`gsc/__init__.py` 頂層不 import `googleapiclient`（import-time side effect guard，見 Key Technical Decisions）
- **Error propagation**：所有 GSC 錯誤在 CLI 層捕獲（`ExternalServiceError` → exit code）；不向上傳播至 WebUI（WebUI handler 額外加 try/except）
- **State lifecycle risks**：`events.db` 的 `indexation.checked` 事件會累積；probe-index 的查詢邏輯需用 `checked_at` 避免重複 probe 同一 URL（rolling 30d 內若已 probe 則跳過）
- **API surface parity**：無 REST API 暴露；純 CLI + WebUI panel，不影響現有 publish pipeline 的 schema
- **Integration coverage**：Unit 6 的 `/ce:health` integration test 需要實際走 Flask test client，不能只測 `health_metrics` 函式
- **Unchanged invariants**：`publish-backlinks` / `validate-backlinks` / `report-anchors` pipeline 完全不受影響；`events.db` schema 擴充向前相容（新增 event kinds，不改現有 kinds）

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| GSC Search Analytics `page` 維度只回傳有曝光的 URL，`has_impressions=False` 代表「近 30d 零曝光」而非「確認未索引」 | UI 標籤用「未出現於 GSC」而非「未索引」；Risks 已登記於 Key Technical Decisions（`gsc.page_signal` 語義） |
| `google-api-python-client` 新依賴可能與現有版本 lock 衝突 | `>=2.100,<3` 上界寬鬆；若衝突，`pip-compile` 後確認 `google-auth` 版本相容性 |
| probe-index 每日跑 200 URLs，GSC 配額 2,000/day，若站點多可能超出 | CLI 加 `--max-urls` 參數（預設 200）讓 operator 控制；超出時 exit 6（advisory）+ recon 說明 |
| health.py / health_metrics.py 均未在 monolith_budget.toml 登記，GSC 面板新增後無 CI 護欄 | Unit 6 強制要求：同 PR 將兩個文件都加入 `monolith_budget.toml`（`health.py` ceiling ≈ 427 + 75 + 30 = 540；`health_metrics.py` ceiling ≈ 245 + 60 + 30 = 340），rationale ≥80 字元 |
| config/types.py ceiling（目前 260）可能在新增 GscConfig 後被突破 | Unit 1 要求：實作後跑 radon 確認；同 PR 調整 ceiling（預估 → 290），附 rationale |
| plan-backlinks/core.py SLOC 超出 ceiling | 實作前跑 `radon raw -s`（Unit 7 Execution note） |
| GSC URL 資料注入 SQLite（SQL injection via page URL） | 所有 GSC response 資料寫 SQLite 必須用 `?` 佔位符，明確要求在 code review checklist 中驗證（Unit 3 Approach） |

## Documentation / Operational Notes

- **Install runbook**：`docs/runbooks/gsc-setup.md`（新建）— 記錄 service account JSON 路徑設定、`property_url` 格式（`sc-domain:example.com`）、ranking_keywords 設定、launchd plist install 步驟
- **config.toml 新增欄位**：`[gsc]` section — `credential_path`、`property_url`、`ranking_keywords`（陣列）
- **config.example.toml 更新**：同步新增 `[gsc]` 範例

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-16-gsc-indexation-ranking-loop-requirements.md](docs/brainstorms/2026-06-16-gsc-indexation-ranking-loop-requirements.md)
- Related code: `src/backlink_publisher/cli/probe_citations.py`, `click_track/engine.py:103`
- External docs: GSC Search Analytics API — `https://developers.google.com/webmaster-tools/v1/api_reference_index`
- IndexNow spec — `https://www.indexnow.org/documentation`
