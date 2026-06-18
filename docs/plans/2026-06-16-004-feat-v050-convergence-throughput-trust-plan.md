---
title: "feat: v0.5.0 三層版本節奏 — 收斂 / Throughput / 信任層"
type: feat
status: shipped
date: 2026-06-16
origin: docs/_archive/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md
claims: {}
---

# feat: v0.5.0 三層版本節奏 — 收斂 / Throughput / 信任層

## Overview

v0.5.0 不是新一輪功能爆發，而是把三條已落地但未收割的線收成可衡量產出：

| Milestone | 主題 | 性質 | 週期 |
|---|---|---|---|
| **M1 收斂** | 關閉在飛工作 + 治理對齊 | 純收尾，零新風險 | 1 週 |
| **M2 Throughput** | dofollow 產出擴充 | 經營已建能力，擴 YAML catalog | 2-3 週 |
| **M3 信任層** | 喚醒死能力 + 補觀測 | 低風險補洞 | 2 週 |

## Problem Frame

規劃前的關鍵發現（已逐一 code-verify，非臆測）：

1. **002 路線圖的 checkbox 嚴重落後於 git log。** 12 個 Unit 中，11 個（U1/U3/U4/U5/U6/U8/U9/U10/U11/U12 + U2 半成）已透過 commit 落地（`e3522764`/`2cdf71b0`/`9f05bbdc`/`534e169f`/`0eb91c6f`/`c1096690`/`9ecf3ab7`/`f9e0aecd`/`1aa3e1ef`），但 plan-doc 仍標 `active` 且多數 checkbox 未翻。**唯一真正未做的是 U7 HTTP 統一**（`grep -rl "import requests" src/` 仍回 27 檔）。這違反 update-plan-on-ship 紀律，是治理缺口。

2. **GSC 003 落得比預期多。** Unit 1（`gsc/client.py`）、Unit 2（`gsc.page_signal`/`ranking.snapshot` kinds）、Unit 3（`cli/probe_index.py` + entrypoint）、Unit 4（`cli/probe_ranking.py` + entrypoint）**全部已落**。**剩 U5（launchd plists）、U6（/ce:health 面板）、U7（plan-backlinks baseline hook）** 三塊。GSC 雙面接入離「可量產」只差這三步。

3. **「直攻 dofollow throughput」的核心能力其實已全部落地。** ideation R11 #2（`config-driven-lightweight-adapters`）標「no plan yet / Unexplored」，但 code audit 顯示：`catalog/catalog_schema.py`（完整 schema + 目錄掃描 + 使用者覆蓋）、`config_driven.py`（`ConfigDrivenAdapter`，含 none/api_key_header/api_key_query 三條 auth path）、`catalog/txtfyi.yaml`（reference entry）、`cli/verify_dofollow.py`（probe → 寫回 catalog）、`cli/_publish_cli.py:155` 的 `--tier-1`/`--dofollow-only` flag（`publish_backlinks/__init__.py:121` 已接 dispatch）**全部已落**。runtime 驗證：`registered_platforms()` 回 24 個，`txtfyi in registry: True`。**所以 M2 不是「建新能力」，而是「補完 catalog 框架的最後驗收 + 擴充更多 dofollow 平台」**。

4. **`bp runs`/resume 是真死能力。** `grep -nE '^\w*(runs|resume|checkpoint)' pyproject.toml` 完全空。checkpoint/resume 邏輯存在於 publishing 層但無 console entrypoint，operator 無法觸達。

5. **reconcile-swallow 的 ideation 描述過時。** ideation R9 #2 說「UNIQUE collision 只剩 int 計數」，但 `events/kinds.py:71` 已登記 `RECONCILE_SWALLOWED` kind 且 `_project_reducers.py:246` 註解顯示已 emit。**真正的洞在另一處**：`_project_reducers.py:118` 的 `skipped_due_to_dedup`（run-level intent dedup，**不同於** UNIQUE collision 的 swallow）仍是 int 計數，這個 dimension 才是未事件化的。

詳見 origin：`docs/_archive/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md`。

## Requirements Trace

- R1. 對齊 002 的 checkbox 與 `status: active → shipped`（治理紀律，update-on-ship）
- R2. 排程 002 U7 HTTP 統一（27 檔 `import requests` 收口，radon 前置門控）
- R3. 完成 GSC 003 U5 launchd plists（probe-index daily + probe-ranking weekly）
- R4. 完成 GSC 003 U6 /ce:health 索引狀態 + 排名趨勢面板
- R5. 完成 GSC 003 U7 plan-backlinks baseline ranking hook（advisory，不阻斷）
- R6. catalog 框架驗收 gate（端到端：YAML → publish → verify-dofollow → catalog 回寫），確認現有 txtfyi 路徑可重現
- R7. 擴充 catalog：新增 ≥2 個 dofollow 平台 YAML（從 `docs/solutions/dofollow-platform-shortlist.md` 候選挑選，需通過 verify-dofollow 確認）
- R8. catalog framework 文件化（operator 指南：如何寫一個 YAML、如何驗證、如何貢獻回 built-in dir）
- R9. `bp runs` + `resume` console entrypoint（喚醒 checkpoint/resume 死能力）
- R10. run-level intent dedup 事件化（`skipped_due_to_dedup` int → 事件，補觀測洞；**注意**：與已事件化的 `reconcile.swallowed` 是不同 dimension，本計劃只動前者）

## Scope Boundaries

- **不新增 publishing adapter 的 Python 程式碼**——M2 純 YAML data-driven（catalog 框架已支援）
- **不重生 002 的已完成工作**——M1 只翻 checkbox + status + 排 U7
- **GSC 003 的 U5-U7 完全沿用原 plan-doc 規格**，本計劃只標「M1 收尾」不重寫 Units（避免雙份規格漂移）
- **Tier-1 dispatch flag 已落地，M2 不改 dispatch 邏輯**——只增加 catalog YAML 並驗收
- **reconcile.swallowed 已事件化，本計劃不動**——R10 只針對 `skipped_due_to_dedup`（run-level intent dedup），兩者 dimension 不同
- **趨勢折線圖前端選型**仍 deferred（R13 既定邊界，本輪不碰）
- **`verify_health.py` BaseSqliteStore 遷移**仍不在本輪（002 已 deferred）
- M2 新增平台需先過 verify-dofollow 確認 dofollow，不確定的標 `uncertain` 並留 rationale（沿用既有 gate）

## Context & Research

### Relevant Code and Patterns

**M1 — GSC 003 收尾（U5/U6/U7）**
- launchd 範本：`scripts/com.dex.bp-citations.plist`（probe-citations 已用的範本，probe-index/ranking 直接仿）
- health 面板 metric 函式範本：`webui_app/health_metrics.py` 的 `geo_citation_share()`（`store.query` + `json_extract` SQL 模式，GSC 面板直接仿）
- health 路由 `_g_cache` 模式：`webui_app/routes/health.py:231-249`（read-only GET 必須 `_g_cache`，CI gate `tests/test_webui_request_cache.py`）
- plan-backlinks baseline hook 掛鉤點：`src/backlink_publisher/cli/plan_backlinks/core.py:238`（`plan_rows()` 呼叫前；原 plan-doc U7 已指定）
- `gsc/__init__.py` 不做頂層 import（`googleapiclient` lazy import，避免 import-time discovery cache）

**M2 — catalog throughput**
- catalog 框架（全已落，M2 是驗收 + 擴充，非建立）：
  - schema：`src/backlink_publisher/publishing/adapters/catalog/catalog_schema.py`（`validate_entry` + `load_all_entries` + 使用者覆蓋語義）
  - adapter：`src/backlink_publisher/publishing/adapters/config_driven.py`（`ConfigDrivenAdapter`，none/api_key_header/api_key_query 三條 path）
  - 註冊接線：`src/backlink_publisher/publishing/adapters/__init__.py:347-381`（`register_catalog_entries()` + `_builtin_catalog`，runtime 已驗證 24 platforms / txtfyi registered）
  - reference entry：`src/backlink_publisher/publishing/adapters/catalog/txtfyi.yaml`（none-auth form-POST + CSRF prefetch + redirect permalink）
  - verify CLI：`src/backlink_publisher/cli/verify_dofollow.py`（probe live page → 寫回 user catalog override）
  - Tier-1 dispatch：`src/backlink_publisher/cli/_publish_cli.py:155` `--tier-1`/`--dofollow-only`，`publish_backlinks/__init__.py:121` 接 dispatch
- dofollow 候選清單：`docs/solutions/dofollow-platform-shortlist.md`
- form-POST 複用：`src/backlink_publisher/publishing/adapters/http_form_post.py`（`fetch_form`/`extract_hidden_fields`/`submit_form`/`attach_link_verification`）

**M3 — 信任層**
- checkpoint/resume 邏輯（需找出現有函式接 entrypoint）：`src/backlink_publisher/publishing/` 內 checkpoint 邏輯（規劃時再 grep 定位）
- bp CLI 總覽命令：`src/backlink_publisher/cli/bp.py`（GROUPS 結構，新增 `runs` 群組需在此登記，`tests/test_bp_registry.py` CI gate）
- pyproject entrypoint 慣例：`[project.scripts]`
- intent-dedup int 計數：`src/backlink_publisher/events/_project_reducers.py:44,68,118,149,381,417,418,462`（`skipped_due_to_dedup`，與 `reconcile.swallowed` 不同 dimension）
- 事件 kind 登記：`src/backlink_publisher/events/kinds.py`（KINDS frozenset + REQUIRED_FIELDS，CI gate）
- monolith 預算：`_project_reducers.py` ceiling 620（HTTP/intent-dedup 若動此檔需同 PR 評估）

### Institutional Learnings

- **plan-doc checkbox 漂移是真實治理風險**：002 顯示 11/12 Unit 落地但 checkbox 未翻、status 未改。M1 R1 是紀律修復，非功能。
- **「已落地但 ideation 標 Unexplored」是本 repo 最大陷阱**（ideation 文件自己的警告）：M2/M3 的前提都必須先 code-verify，否則會重複發明已存在的東西。本計劃的 M2/M3 經過 verify。
- **launchd 慣例**：`WorkingDirectory` 中文絕對路徑；stdout+stderr 合併同一 log；`RunAtLoad: false`；EnvironmentVariables 顯式列（launchd 不繼承 shell env）。
- **SLOC 預算先測後動**：新 CLI/改動寫完即跑 `radon raw -s`；超 ceiling 需同 PR 調高 + rationale ≥80 chars。
- **WebUI config 讀取用 `_g_cache`**：read-path handler 必須 `_g_cache('config', load_config)`，write-path 直接 `load_config()`。
- **dofollow gate 在 catalog schema 已鏡像 `register()` 契約**：`catalog_schema.py:96-116` 的 rationale ≥80 chars + referral_value 檢查，新增 YAML 需遵守。
- **`register()` 不可重複註冊已 claimed slug**（`register_catalog_entries` 跳過已存在 slug）——M2 新 YAML slug 不可撞既有 24 個 platform 名。
- **reliability enforce 只動 mastodon，其他 channel 保持 observe**（002 已定邊界，M1 不擴大）。

## Key Technical Decisions

- **M1 不重寫 GSC 003 的 Units**：003 的 U5/U6/U7 規格完整且仍準確，M1 只「指向並執行」，不在本計劃重複規格。避免雙份規格漂移。本計劃的 R3/R4/R5 是「執行 003 的 U5/U6/U7」的同義詞。
- **M2 catalog 驗收優先於擴充**：R6（端到端驗收）必須在 R7（擴充新平台）之前——先證明 txtfyi 既存路徑可重現，再談擴充。否則在未驗證的框架上加平台是盲擴。
- **M2 新增平台優先 none-auth form-POST 類型**：`config_driven.py` 的 `_publish_form_post` path 已驗證（txtfyi 用此），`_publish_api_post` path 未有 reference entry。M2 暫限 form-POST 類型，API-key 類型留待有真實需求再擴（避免在未驗證的 path 上承諾）。
- **M3 `bp runs`/resume 的 entrypoint 純接線，不動 checkpoint 邏輯**：死能力的根因是缺 entrypoint，不是缺邏輯。先確認現有 checkpoint 函式能被 CLI 包裝，若邏輯有缺再評估範圍。
- **R10 intent-dedup 事件化只動 reducer 的 int 計數，不改 dedup 行為**：把 `skipped_due_to_dedup` 從 aggregate int 改為 emit 一個事件 kind（暫名 `publish.intent_deduped`），reducer 行為不變。需先確認是否有 reader 依賴這個 int（grep `ProjectionResult.skipped_due_to_dedup` 的 consumer）。
- **不碰 `reconcile.swallowed`**：它已事件化（kind + reducer emit），R10 是不同的 dimension（intent-level vs UNIQUE-collision-level）。混在一起會破壞語義。
- **M1 R1 的 checkbox/status 對齊是獨立小 PR**：不與 GSC U5-U7 混提，避免把治理修復綁在功能 PR 上（diff 難 review）。

## Open Questions

### Resolved During Planning

- **catalog 框架是否真的可用？** 是。runtime 驗證 `registered_platforms()` = 24，txtfyi registered = True，`ConfigDrivenAdapter` 三條 auth path 完整。
- **reconcile.swallowed 是否未事件化？** 否，已事件化（`kinds.py:71` + `_project_reducers.py:246`）。R10 改的是另一個 int（`skipped_due_to_dedup`，intent-level），不是這個。
- **002 哪些 Unit 真未做？** 僅 U7（HTTP 統一）。其餘 11 個 git log 可證已落。

### Deferred to Implementation

- **M2 新增平台的具體名單**：從 `docs/solutions/dofollow-platform-shortlist.md` 挑，實作時確認候選仍存活且 form-POST 可達。優先 none-auth 類型。
- **M3 checkpoint 邏輯的確切位置與 resume 契約**：規劃時 grep 定位，確認 `run_receipt`/`run_id` 的持久化格式。若邏輯不完整，M3 範圍需重新評估。
- **R10 的 consumer 影響**：grep `skipped_due_to_dedup` 的 reader（reports/health panel？），確認事件化後 consumer 改讀事件聚合不破壞現有報表。
- **GSC U6 health.py monolith 風險**：003 plan-doc 已記 `health.py` ≈427 SLOC 未登記 budget，GSC 面板 +60-90 SLOC 需同 PR 登記 `monolith_budget.toml`（ceiling ≈ 540 + rationale）。本計劃繼承此約束。

## High-Level Technical Design

> *方向性指引，非實作規格。M1 的 GSC Units 規格以 003 plan-doc 為準。*

```
M1 收斂（1 週）
  ├── [docs PR] 002 checkbox 對齊 git log + status: active → shipped
  ├── [GSC 003 U5] com.dex.bp-probe-index.plist (daily) + com.dex.bp-probe-ranking.plist (weekly)
  ├── [GSC 003 U6] /ce:health indexation_status() + ranking_trend() → 兩個面板
  └── [GSC 003 U7] plan_backlinks/core.py baseline hook (advisory try/except)

M2 Throughput（2-3 週）
  ├── [R6 驗收] 端到端: cat seeds | plan | validate | publish --platform txtfyi --tier-1
  │              → verify-dofollow txtfyi → catalog 回寫 dofollow verdict
  ├── [R7 擴充] ≥2 新 dofollow 平台 YAML (none-auth form-POST, from shortlist)
  │              每個過 verify-dofollow 確認 → 標 dofollow=true 或 uncertain+rationale
  └── [R8 文件] docs/operations/catalog-adapter-guide.md (YAML 撰寫 + 驗證 + 貢獻流程)

M3 信任層（2 週）
  ├── [R9] pyproject: bp runs (list resumable) + resume <run_id> entrypoint
  │        bp.py GROUPS 登記 runs 群組; tests/test_bp_registry.py 過
  └── [R10] events/kinds.py: publish.intent_deduped kind + REQUIRED_FIELDS
            _project_reducers.py: skipped_due_to_dedup int → emit event (行為不變)
            grep consumer 改讀事件聚合 (reports/health)

[並行/背景] M1 R2 HTTP 統一（27 檔 import requests）
  └── radon 前置掃描 → 分批 PR 收口到 _util/http_client.py
      （可跨 M1-M3 並行，不阻塞主線；每批 PR 獨立）
```

## Implementation Units

### Milestone 1 — 收斂

- [x] **Unit 1: 002 plan-doc checkbox + status 對齊（治理 PR）** — `48cb0c4` + plan-002 status→shipped

**Goal:** 修正 002 的 checkbox 與 git log 不一致，把 `status: active → shipped`，恢復 plan-doc 的可信度。

**Requirements:** R1

**Dependencies:** 無（純 docs）。

**Files:**
- Modify: `docs/_archive/plans/2026-06-16-002-feat-comprehensive-optimization-roadmap-plan.md`

**Approach:**
- 對照 git log 逐 Unit 翻 checkbox：U1/U3/U4/U5/U6/U8/U9/U10/U11/U12 → `[x]`（附 commit SHA 作為證據）；U2 半成標註；U7 保持 `[ ]`
- 把 `status: active` 改 `status: shipped`
- 在 plan-doc 開頭加一段「Reality Check」說明哪些已落、附 commit，未來讀者不會被舊 checkbox 誤導
- **不動 `date:` 欄位**（R11b filename↔date lock，bump 會破壞 grandfather + 檔名鎖）

**Patterns to follow:** AGENTS.md「Update-plan-on-ship discipline」

**Test scenarios:**
- N/A（純 docs，無可測行為）；但 `plan-check docs/plans/2026-06-16-002-*.md` 需仍 exit 0（claims:{} 不觸發 drift）

**Verification:** plan-check exit 0；git diff 只動該檔的 checkbox 與 status 欄

---

- [x] **Unit 2: GSC 003 U5 — probe-index/probe-ranking launchd plists**

**Goal:** 兩個 GSC probe CLI 進入無人值守排程。

**Requirements:** R3

**Dependencies:** GSC 003 U3/U4 已落（CLI + entrypoint 存在）。

**Files:**
- Create: `scripts/com.dex.bp-probe-index.plist`
- Create: `scripts/com.dex.bp-probe-ranking.plist`
- Create: `scripts/run-probe-index-periodic.sh`
- Create: `scripts/run-probe-ranking-periodic.sh`
- Create/Update: `docs/operations/gsc-setup.md`（install 步驟）

**Approach:**
- 完全仿 GSC 003 plan-doc U5 規格（daily UTC 02:30 / weekly Sun UTC 03:30，錯開 probe-citations 03:00）
- plist 慣例：中文絕對路徑 WorkingDirectory、stdout+stderr 合併、`RunAtLoad: false`、env 顯式列
- wrapper：`--probe` flag（不 dry-run），log 到 `logs/probe-index.log` / `logs/probe-ranking.log`
- 確認 `.gitignore` 有 `logs/*.log` 條目

**Patterns to follow:** `scripts/com.dex.bp-citations.plist`、`scripts/run-citations-periodic.sh`

**Test scenarios:**
- `plutil -lint scripts/com.dex.bp-probe-index.plist` 通過
- 手動執行 wrapper（mock credential）→ 非零退出寫 log（配額/credential 缺失），不 silent

**Verification:** 兩 plist + 兩 wrapper committed；plutil -lint 通過；runbook install 步驟可重現

---

- [x] **Unit 3: GSC 003 U6 — /ce:health 索引狀態 + 排名趨勢面板**

**Goal:** operator 在 /ce:health 看到 GSC 索引狀態（出現/未出現）+ 排名 baseline vs latest delta。

**Requirements:** R4

**Dependencies:** GSC 003 U2（kinds 已落）。

**Files:**
- Modify: `webui_app/health_metrics.py`（新增 `indexation_status()` + `ranking_trend()`）
- Modify: `webui_app/routes/health.py`（`_g_cache` + template 傳參）
- Modify: `webui_app/templates/health.html`（兩個面板）
- Modify: `monolith_budget.toml`（health.py + health_metrics.py 登記，rationale ≥80 chars）
- Test: `tests/webui/test_health_metrics.py`（或同等）

**Approach:**
- 完全仿 GSC 003 plan-doc U6 規格
- `indexation_status(store)`：`store.query` + `json_extract`，按 target_url 分組 has_impressions
- `ranking_trend(store)`：每 keyword 最舊 baseline vs 最新 snapshot，position delta（`↑` 綠/`↓` 紅）
- 無資料顯示「尚無快照」，不 500
- **強制同 PR 登記 monolith_budget.toml**（health.py ≈427+75+30=540；health_metrics.py ≈245+60+30=340，rationale ≥80）

**Patterns to follow:** `health_metrics.geo_citation_share()`、`routes/health.py:231-249`

**Test scenarios:**
- Happy: events.db 有 gsc.page_signal → indexation_status 正確 counts
- Happy: baseline + follow-up snapshot → ranking_trend delta 正確（非重疊窗口）
- Edge: 無資料 → `[]`，面板顯示提示
- Integration: `pytest tests/test_webui_request_cache.py` 過

**Verification:** GET /ce:health 200 含兩面板；CI gate 過；radon 未超新 ceiling

---

- [x] **Unit 4: GSC 003 U7 — plan-backlinks baseline ranking hook**

**Goal:** plan-backlinks 建鏈前 advisory 觸發 ranking baseline snapshot（GSC 未設定靜默跳過）。

**Requirements:** R5

**Dependencies:** GSC 003 U4（probe_ranking 邏輯）。

**Files:**
- Modify: `src/backlink_publisher/cli/plan_backlinks/core.py`（line ~238，plan_rows 呼叫前）
- Test: `tests/cli/plan_backlinks/test_core.py`

**Approach:**
- 完全仿 GSC 003 plan-doc U7 規格
- `try: from backlink_publisher.gsc.ranking import snapshot_baseline; snapshot_baseline(rows, cfg) except Exception as exc: _log.debug(...)`
- GSC 未設定（property_url=None）→ 函式立即 return
- 實作前跑 `radon raw -s core.py` 確認 headroom（ceiling 250）

**Patterns to follow:** GSC 003 U7；keepalive/chain.py 的非阻塞 side-effect 模式

**Test scenarios:**
- Happy: mock snapshot_baseline 成功 → plan_rows 照常
- Edge: 拋 ExternalServiceError → plan_rows 仍被呼叫（不阻斷）
- Edge: GscConfig 未設定 → 立即 return，無 API 呼叫

**Verification:** 現有 test_core.py 全綠；plan-backlinks 在 GSC 未設定環境照常

---

### Milestone 2 — Throughput

- [x] **Unit 5: catalog 框架端到端驗收** — `8b443de`

**Goal:** 證明既存 catalog 路徑可重現，作為 M2 擴充的前提。

**Requirements:** R6

**Dependencies:** 無（catalog 框架已落）。

**Files:**
- Test: `tests/publishing/test_catalog_e2e.py`（新建）
- Verify: `src/backlink_publisher/publishing/adapters/catalog/txtfyi.yaml`（reference entry，不動）

**Approach:**
- 端到端 happy path（mock HTTP）：
  1. `cat seeds.jsonl | plan-backlinks | validate-backlinks` 產生一筆 txtfyi payload
  2. `publish-backlinks --platform txtfyi --tier-1 --dry-run` 確認 dispatch 選到 ConfigDrivenAdapter
  3. mock form-POST 回 302 redirect → `published_url` 解析正確
  4. mock `verify_link_attributes` 回 dofollow → `verify-dofollow txtfyi` 寫回 user catalog override
  5. 讀回 user catalog 確認 `dofollow` 欄位更新
- 確認 `--tier-1` flag 確實過濾掉 non-dofollow platform（txtfyi 是 uncertain，測試需驗證 uncertain 的過濾行為——若 uncertain 不被 tier-1 收，測試改用 dofollow=true 的 mock entry）
- 失敗 path：API key 缺失（api_key_header 類型）→ DependencyError；form-POST 5xx → ExternalServiceError

**Patterns to follow:** `tests/publishing/` 現有 adapter 測試模式

**Test scenarios:**
- Happy: 上述 5 步全綠
- Edge: `--tier-1` 過濾行為符合預期
- Error: DependencyError（api_key 缺）、ExternalServiceError（5xx）

**Verification:** `pytest tests/publishing/test_catalog_e2e.py` 全綠；證明 ConfigDrivenAdapter + verify-dofollow + catalog 回寫閉環可重現

---

- [ ] **Unit 6: 擴充 ≥2 個 dofollow 平台 catalog YAML**

**Goal:** 增加 dofollow 平台產出管道，直攻 throughput 業務瓶頸。

**Requirements:** R7

**Dependencies:** Unit 5（框架已驗收）。

**Files:**
- Create: `src/backlink_publisher/publishing/adapters/catalog/<platform1>.yaml`
- Create: `src/backlink_publisher/publishing/adapters/catalog/<platform2>.yaml`
- Test: `tests/publishing/test_catalog_<platform>.py`（每平台一個 schema + mock publish test）

**Approach:**
- 從 `docs/solutions/dofollow-platform-shortlist.md` 挑 ≥2 個候選
- **優先 none-auth form-POST 類型**（`_publish_form_post` path 已驗證；`_publish_api_post` 無 reference，本輪不碰）
- 每個 YAML 過 `validate_entry`（dofollow gate：true 或 uncertain+rationale≥80）
- 每個過 `verify-dofollow`（需真實發一篇確認）：
  - 確認 dofollow=true → YAML 標 `dofollow: true`
  - 不確定 → `dofollow: uncertain` + rationale ≥80 + referral_value
- slug 不可撞既有 24 platform 名（runtime `registered_platforms()` 已含）
- 每平台附 mock publish test（happy/DependencyError/ExternalServiceError，沿用 adapter test 慣例）

**Patterns to follow:** `catalog/txtfyi.yaml`（reference entry 格式）

**Test scenarios:**
- Happy: 每個新 YAML 過 schema validation + mock publish test
- Live: verify-dofollow 確認 dofollow verdict 後才標 true
- Edge: slug 撞既有 → `register_catalog_entries` 跳過（不重複註冊），需換 slug

**Verification:** `registered_platforms()` 含新 slug；每平台 mock test 全綠；verify-dofollow verdict 記錄

---

- [x] **Unit 7: catalog framework operator 指南** — `4f06c32`

**Goal:** operator 知道如何加一個 YAML、如何驗證、如何貢獻回 built-in dir。

**Requirements:** R8

**Dependencies:** Unit 5（驗收完成，內容準確）。

**Files:**
- Create: `docs/operations/catalog-adapter-guide.md`

**Approach:**
- 章節：(1) YAML 欄位速查（slug/endpoint/auth_type/content_field/permalink_via/dofollow gate）；(2) none-auth form-POST 寫法（仿 txtfyi）；(3) CSRF prefetch 寫法；(4) verify-dofollow 驗證流程；(5) user override vs built-in 貢獻流程；(6) dofollow gate rationale 要求
- 附一個最小可運作 YAML 範例（none-auth）
- 連結到 `catalog_schema.py` 的 `VALID_TOP_LEVEL_KEYS` 作為 SSoT

**Patterns to follow:** `docs/operations/` 現有 runbook 格式

**Test scenarios:** N/A（docs）；但內容需與 `catalog_schema.py` schema 一致（人工 review）

**Verification:** 文件存在；欄位描述與 `catalog_schema.py` 一致；operator 可照文件加一個 YAML 並 publish

---

### Milestone 3 — 信任層

- [x] **Unit 8: `bp runs` + `resume` console entrypoint** — `717d375`

**Goal:** 喚醒已建但無 entrypoint 的 checkpoint/resume 死能力。

**Requirements:** R9

**Dependencies:** 無（先確認 checkpoint 邏輯可包裝）。

**Files:**
- Create: `src/backlink_publisher/cli/runs.py`（`bp runs` subcommand）
- Create: `src/backlink_publisher/cli/resume.py`（`resume <run_id>` entrypoint）
- Modify: `pyproject.toml`（`runs = "..."` / `resume = "..."` [project.scripts]）
- Modify: `src/backlink_publisher/cli/bp.py`（GROUPS 登記 runs 群組）
- Test: `tests/cli/test_runs.py`、`tests/test_bp_registry.py`

**Approach:**
- **前置**：grep 定位現有 checkpoint/resume 邏輯（`grep -rln "checkpoint\|run_id\|resumable" src/backlink_publisher/publishing/`），確認：(a) run receipt 持久化格式；(b) 哪個函式能 list resumable runs；(c) 哪個函式能 resume 一個 run_id
- `bp runs`：list resumable runs（run_id, status, target, started_at, exact resume command）；stdout=JSONL
- `resume <run_id>`：讀 checkpoint → 重放未完成 rows → stdout JSONL
- 若 checkpoint 邏輯不完整（缺 list/resume 函式），**暫停本 Unit**，回到規劃評估範圍（不硬接不存在的邏輯）
- `bp.py` GROUPS 加 `runs` 群組；`tests/test_bp_registry.py` 過

**Patterns to follow:** `cli/bp.py` GROUPS 結構；其他 list-style CLI（如 `equity_ledger.py`）

**Test scenarios:**
- Happy: 一個中斷的 run → `bp runs` 列出 → `resume <run_id>` 完成剩餘 rows
- Edge: 無 resumable run → `bp runs` exit 0 空 JSONL
- Error: 不存在的 run_id → exit 1 + stderr
- Integration: `tests/test_bp_registry.py` 過（runs 群組已登記）

**Verification:** `bp runs` 列出中斷 run；`resume <run_id>` 完成重放；registry test 過

---

- [x] **Unit 9: run-level intent dedup 事件化** — `df7140d`

**Goal:** 把 `skipped_due_to_dedup` int 計數改為 emit `publish.intent_deduped` 事件，補觀測洞。

**Requirements:** R10

**Dependencies:** 無。

**Files:**
- Modify: `src/backlink_publisher/events/kinds.py`（新增 `PUBLISH_INTENT_DEDUPED` kind + REQUIRED_FIELDS）
- Modify: `src/backlink_publisher/events/_project_reducers.py`（int 計數 → emit event；行為不變）
- Modify: grep consumer（reports/health panel 讀 `skipped_due_to_dedup` 的地方）→ 改讀事件聚合
- Test: `tests/events/test_kinds.py`、`tests/events/test_project_reducers.py`

**Approach:**
- **前置 consumer 調查**：`grep -rn "skipped_due_to_dedup" src/ webui_app/`，列出所有 reader，評估事件化後改讀聚合的範圍
- `PUBLISH_INTENT_DEDUPED` kind 登記：REQUIRED_FIELDS `{run_id, target_url}`（platform 放 payload）
- reducer：原本 `skipped_due_to_dedup += 1` 改為同時 emit 一個事件（**保留 int 計數於 ProjectionResult 一段過渡期**，避免 consumer 同步切換破壞報表——双寫過渡，consumer 改完後再移除 int）
- **不改 dedup 行為本身**（哪些 row 被 dedup 的判斷邏輯不動），只改「被 dedup 時記錄什麼」
- **不碰 `reconcile.swallowed`**（不同 dimension，已事件化）

**Patterns to follow:** `events/kinds.py` 現有 kind 登記；`referral/store.py::append_referral_observed`（direct-append）

**Test scenarios:**
- Happy: 一個 run 有 intent dedup → `publish.intent_deduped` 事件寫入 events.db
- Edge: 無 dedup → 不 emit（行為不變）
- Regression: `skipped_due_to_dedup` int 仍存在（過渡期双寫），現有報表不破
- Integration: `pytest tests/events/` 全綠

**Verification:** events.db 有 `publish.intent_deduped`；現有 reducer test 不破；consumer 已切換讀事件

---

### 並行背景工作

- [x] **Unit 10: 002 U7 HTTP client 統一（27 檔 import requests 收口）** — `98677dd` (batch 1) + batch 2 收口 (#33/#35/#36/#37/#38). 16 deferred 全部處置：可遷的 7 個遷至 http_client（OAuth/status-code 語義靠 `raise_for_status=False`、私網端點靠 `allow_private=True`）；http_form_post 結構性保留 raw + 內聯 `_guard_ssrf`。剩餘 allowlist 全為結構性豁免

**Goal:** src/ 所有裸 `import requests` 收口為 `_util/http_client.py`，SSL context 統一。

**Requirements:** R2

**Dependencies:** 無（可跨 M1-M3 並行，不阻塞主線）。

**Files:**
- Modify: 27 個含 `import requests` 的檔案（前置 radon 掃描列出）
- Key targets（已知）: `geo/perplexity.py`、`content/_http.py`、`publishing/session/provider.py`、`publishing/adapters/config_driven.py`（M2 動過的檔案若撞 ceiling 需協調）
- Modify if needed: `monolith_budget.toml`（超 ceiling 者）

**Approach:**
- **前置 radon 掃描**：`grep -rl "import requests" src/` 列 27 檔 → 每檔 `radon raw -s` → 標出超 ceiling 者
- 分批 PR（每批 3-5 檔，降低 blast radius），優先 geo/content 信號路徑熱點
- 每個替換語義等價：`requests.get(url, timeout=...)` → `http_client.get(url, timeout=...)`
- SSL context 統一：`BACKLINK_NO_FETCH_VERIFY` 處理移到 http_client 層
- 特殊 session（cookie-based）記為 deferred exception，不強制收口
- 超 SLOC ceiling：同 PR 提 ceiling + rationale ≥80

**Patterns to follow:** `src/backlink_publisher/_util/http_session.py`、`_util/http_client.py`

**Test scenarios:**
- Happy: 替換後各模組現有測試全綠（行為等價）
- Edge: `BACKLINK_NO_FETCH_VERIFY=1` 仍跳過 SSL verify
- Error: http_client timeout 時 caller 仍正確捕獲（異常類型不變）

**Verification:** `grep -rl "import requests" src/` 輸出為空（或只剩 documented exception）；所有測試通過；radon 受影響檔未超 ceiling

---

## System-Wide Impact

- **Interaction graph**: M1 launchd plists（Unit 2）與 WebUI 共用 events.db（single-writer 模式，不需 RLock）；M2 catalog 新 YAML 透過 `register_catalog_entries` 在 import 時 auto-register（runtime 已驗證不撞既有 slug）；M3 `bp runs`/resume 讀寫 checkpoint（需確認跨進程安全）；Unit 9 intent-dedup 事件寫 events.db
- **Error propagation**: M1 launchd job stderr 寫 log、exit 非零由 launchd 記錄；M2 ConfigDrivenAdapter 的 DependencyError/ExternalServiceError 沿用既有 dispatch chain；M3 resume 失敗 exit 非零 + stderr
- **State lifecycle risks**: Unit 9 intent-dedup 双寫過渡期需 consumer 同步切換（不然 int 與事件分歧）；Unit 2 logs/*.log 進 .gitignore（launchd 每次更新）；Unit 3 monolith budget 需同 PR 登記
- **API surface parity**: M1 /ce:health 新增面板不改路由 contract；M2 catalog 新平台不改 CLI/schema（registry 自動接線）；M3 `bp runs`/resume 是新 entrypoint，不改既有
- **Integration coverage**: Unit 5 catalog e2e test 是 M2 擴充的前提 gate；Unit 3 `_g_cache` 需過 `tests/test_webui_request_cache.py`；events kinds 需過 `tests/events/test_kinds.py`；bp registry 需過 `tests/test_bp_registry.py`
- **Unchanged invariants**: publish pipeline（plan→validate→publish→recheck）核心不變；enforce 只動 mastodon（002 邊界繼承）；`reconcile.swallowed` 不動（語義保護）；dofollow gate 契約（catalog schema 鏡像 register）

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| 002 checkbox 對齊遗漏某 Unit（git log 漏標） | M1 Unit 1 對照 commit message 的 `Plan 002 U*` 標記逐個核；不確定的標 `[ ]` 不亂翻 |
| GSC U6 health.py/health_metrics.py monolith 超限 | 繼承 003 U6 約束：同 PR 登記 monolith_budget.toml + rationale ≥80；radon 前置 |
| M2 新增平台 slug 撞既有 24 platform | runtime `registered_platforms()` 查；撞了換 slug（register_catalog_entries 跳過已 claimed） |
| M2 API-key path（`_publish_api_post`）無 reference，盲擴風險 | M2 Unit 6 限 none-auth form-POST；API-key 類型留待真實需求 |
| M3 checkpoint 邏輯不完整（缺 list/resume 函式） | Unit 8 前置 grep 調查；邏輯缺則暫停 Unit、回規劃，不硬接不存在的邏輯 |
| Unit 9 intent-dedup 双寫過渡期 consumer 未同步切換 | 前置 grep consumer；保留 int 一段過渡期；consumer 改完才移除 int |
| HTTP 統一（Unit 10）27 檔觸碰 monolith ceiling | 前置 radon 掃描；分批 PR（3-5 檔）；超限者同 PR rationale |
| catalog 框架 ideation 標 Unexplored 但實際已落（本 repo 最大陷阱） | 本計劃 M2 已 runtime verify（24 platforms, txtfyi registered）；執行時若發現框架有缺，回規劃而非硬上 |

## Documentation / Operational Notes

- M1 Unit 1 的 002 對齊 PR 需記錄「哪些 commit 證明 Unit 已落」，作為治理證據鏈
- M1 Unit 2 的 gsc-setup.md runbook 記錄：service account JSON 路徑、property_url 格式、ranking_keywords 設定、launchd install
- M2 Unit 7 的 catalog-adapter-guide.md 是 operator 加 YAML 的 SSoT，欄位需與 `catalog_schema.py` 一致
- M3 Unit 8 的 `bp runs`/resume runbook 記錄中斷 run 的恢復流程
- 整個 v0.5.0 完成後，`docs/ideation/gate-verdicts.md` 的 backlog roll-up 需更新（002 shipped、003 shipped、新 Unit 進 done）

## Phased Delivery

### M1 — 收斂（1 週）
Units 1-4：002 治理對齊 + GSC 003 U5/U6/U7 收尾。純收尾，讓在飛工作全部落地。

### M2 — Throughput（2-3 週）
Units 5-7：catalog 框架驗收 → 擴充 ≥2 dofollow 平台 → operator 指南。直攻業務瓶頸。

### M3 — 信任層（2 週）
Units 8-9：喚醒 `bp runs`/resume 死能力 + intent-dedup 觀測洞。補可信度。

### 並行背景
Unit 10：HTTP 統一（跨 M1-M3，不阻塞主線）。

## Sources & References

- **Origin document**: [docs/_archive/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md](docs/_archive/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md)
- **GSC 003 Units 規格來源**: `docs/_archive/plans/2026-06-16-003-feat-gsc-indexation-ranking-loop-plan.md`（U5/U6/U7，本計劃不重寫）
- **catalog 框架已落地證據**: `src/backlink_publisher/publishing/adapters/catalog/catalog_schema.py`、`config_driven.py`、`catalog/txtfyi.yaml`、`cli/verify_dofollow.py`、`cli/_publish_cli.py:155`（`--tier-1`）、`adapters/__init__.py:347-381`（runtime 24 platforms verified）
- **ideation 假設過時記錄**: `docs/ideation/2026-06-05-backlog-convergence-ideation.md`（#2 標「no plan yet / Unexplored」但 code 已落——本 repo 陷阱實例）
- Related plans: `docs/_archive/plans/2026-06-16-002-feat-comprehensive-optimization-roadmap-plan.md`（M1 Unit 1 對齊對象）、`docs/_archive/plans/2026-06-16-003-feat-gsc-indexation-ranking-loop-plan.md`（M1 Unit 2-4 規格來源）
- dofollow 候選: `docs/solutions/dofollow-platform-shortlist.md`
- Launchd pattern: `scripts/com.dex.bp-citations.plist`
