---
title: "feat: 全面優化迭代路線圖（2026 Q3）— 激活 + 排程化 + 自治閉環"
type: feat
status: shipped
date: 2026-06-16
origin: docs/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md
claims: {}
---

# feat: 全面優化迭代路線圖（2026 Q3）

## Overview

三個月、三個 Phase，讓 backlink-publisher 從「建好但未動」走向「排程化閉環」。
006/007 代碼已全部完成（所有 Unit `[x]`）；本計劃的起點是**啟動**，而非重新實作。

> **Reality Check（updated 2026-06-17, plan 004 Unit 1）**
> Checkbox 對齊後：**12 個 Unit 全部已落地**（commit 證據見各 Unit 行）。
> U7 HTTP 統一：batch 1 完成（`98677dd6`，27→17 檔），**16 檔 deferred**（session/status-code
> 語義需 per-adapter 評估，非純機械替換）。剩餘追蹤在 plan `2026-06-16-004` Unit 10。
> 本計劃標為 `shipped`；U7 deferred 部分由 plan-004 獨立追蹤，不阻塞本計劃收口。

| Phase | 主題 | 週期 |
|---|---|---|
| Phase 1 (M1) | 激活 + 排程化 | 4 週 |
| Phase 2 (M2) | 信號延伸 + HTTP 統一 | 4 週 |
| Phase 3 (M3) | 自治閉環 | 4 週 |

## Problem Frame

v0.4.0 功能完備，但自動化深度不足：enforce gate 從未真正攔截過一次；citation probe / weights
排程缺失；27 個 src 檔案仍直呼 `requests`；plan-gap → publish 仍需人工組裝命令。
詳見 origin：`docs/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md`。

## Requirements Trace

- R1. 啟用 mastodon enforce（006 Unit 9 operator-gate，代碼已就緒）
- R2. 驗收 007 plists committed + install runbook 完整
- R3. probe-citations 每日排程（plist committed，配額先確認）
- R4. weights 週排程（plist committed）
- R5. debt_registry.toml mitigated 項稽查
- R6. /ce:health citation 面板（per-target 分布 + 7d rolling）
- R7. HTTP client 統一（src 27 個 import requests 收口，radon 前置門控）
- R8. Decay alert（14d 掉 ≥2 鏈 → events.db + /ce:health banner）
- R9. weights 快照顯示於 /ce:health
- R10. plan-gap 週排程腳本（equity-ledger | plan-gap | plan-backlinks 組合）
- R11. autopilot 狀態頁擴展（上次 plan-gap 結果）
- R12. Citation share health gate（gated on R3 配額確認）

## Scope Boundaries

- 不新增 publishing adapter
- Phase 3 plan-gap 排程**不自動 publish**（operator 確認後執行）
- 趨勢折線圖（R13）為 stretch goal，前端選型未解前不納入
- `verify_health.py` 的 BaseSqliteStore 遷移不納入本輪
- 006 Unit 9 mastodon enforce 為 operator-gated 動作，計劃提供驗收標準，不寫自動化腳本

## Context & Research

### Relevant Code and Patterns

**Phase 1**
- 006 Unit 9 接口：`src/backlink_publisher/publishing/reliability/policy.py` — `publish_with_policy()`，enforce-allowlist 已穿進此 chokepoint（Unit 7+8 [x]）
- enforce-allowlist config：`src/backlink_publisher/publishing/reliability/` — `allowlist.py` 或 config key（Unit 7 建立）
- would_skip 事件：`publishing/reliability/events_store.py::append_reliability_decision()` → `events.db`
- launchd 範本：`scripts/com.dex.bp-recheck.plist`（bash wrapper + WorkingDirectory 用中文路徑 `/Users/dex/YDEX/INPORTANT WORK/外链/...` + stdout/stderr 合併同一 log + RunAtLoad: false）
- weights CLI：`backlink_publisher.cli.weights:main`（subcommands: collect / optimize / show）
- probe-citations CLI：`backlink_publisher.cli.probe_citations:main`；geo 引擎在 `src/backlink_publisher/geo/`
- citation.observed 事件 → `geo/run.py` → `events.db`

**Phase 2**
- /ce:health 路由：`webui_app/routes/health.py`（GET /ce:health 第 394 行）
- health 面板模板：`webui_app/templates/health.html` + `webui_app/static/js/health.js`
- health metrics 服務：`webui_app/health_metrics.py`
- _g_cache 模式：read-only GET 必須用 `_g_cache('config', load_config)`（CI gate: `tests/test_webui_request_cache.py`）
- events.db kinds 登記：`src/backlink_publisher/events/kinds.py` KINDS frozenset（:82-105）+ REQUIRED_FIELDS（:134-170）
- citation direct-append 參考：`referral/store.py::append_referral_observed`
- HTTP client 模組：`src/backlink_publisher/_util/http_client.py`、`_util/http_session.py`
- HTTP 直呼熱點：`geo/perplexity.py`、`content/_http.py`、`publishing/session/provider.py`

**Phase 3**
- autopilot 路由：`webui_app/routes/sites.py::sites_form()` + `sites_autopilot()`
- autopilot 狀態頁：`webui_app/templates/sites.html`
- plan-gap CLI：`backlink_publisher.cli.plan_gap:main`
- equity-ledger CLI：`backlink_publisher.cli.equity_ledger:main`
- webui_store 跨進程 RMW 風險：webui.db 的 RLock 只保護 intra-process；launchd job + WebUI 同寫需評估 `fcntl.flock`（參考 `circuit.py` 的跨進程 flock 模式）

### Institutional Learnings

- **enforce 啟用順序**：Unit 8（損毀態降級 + 告警源解耦）必須在 Unit 9 之前。Unit 8 已 `[x]`，所以 Phase 1 R1 可以安全進行。
- **plist 慣例**：`WorkingDirectory` 用中文絕對路徑；stdout + stderr 合併同一 log；`RunAtLoad: false`；EnvironmentVariables 顯式列（launchd 不繼承 shell env，`PATH`、`BP_LANG` 等都要明列）。
- **probe-citations 配額前置**：plist 的 `StartCalendarInterval` 和 `--max-batch` 取決於 Perplexity v1 API 日配額。必須先確認配額再寫 plist，不要反過來。
- **recheck per-probe timeout (R10)**：daily recheck plist（007）已讓 recheck 進入無人值守模式，原 LITE 期 defer 的 per-probe timeout 的 resume trigger 已正式觸發。Phase 1 Unit 2 須確認 recheck wrapper 已有 `timeout` 指令包裝，或評估補 `socket.settimeout`。**重要**：現有 plist 用 `StartCalendarInterval`（定時觸發，不管前次是否仍在跑）；若 job 卡死，launchd 不會可靠 kill python child process。若 wrapper 無 timeout 保護，應改為 `StartInterval`（前次仍在跑則 skip）直到 timeout 補齊。
- **logs/ 跨進程路徑一致性**：launchd job 的 `WorkingDirectory` 和 WebUI process 的啟動路徑可能不同，相對路徑 `logs/` 不可靠。Unit 10/11 的 `logs/plan-gap-latest.json` 和 `logs/citation-low-share.json` 均應使用 `WorkingDirectory` 的同一絕對路徑（從 `BACKLINK_PUBLISHER_CONFIG_DIR` 或 hardcode git root 絕對路徑），不用相對路徑。
- **logs/ git 狀態**：`logs/plan-gap-latest.json` 和 `logs/citation-low-share.json` 必須在 `.gitignore`（launchd 每次執行都更新，否則永遠 dirty working tree）。Unit 10 實作前確認 `.gitignore` 已有 `logs/*.json` 條目。
- **events.db 新 kind 登記路徑**：① `kinds.py` KINDS frozenset；② REQUIRED_FIELDS；③ platform 資訊放 `payload` JSON 欄（events.db 的 INSERT 沒有獨立 platform 欄）。
- **monolith_budget.toml 監控清單重點**：`cli/plan_backlinks/core.py`(250)、`cli/publish_backlinks/__init__.py`(240)、`content/fetch.py`(250)、`publishing/adapters/__init__.py`(340)。HTTP 統一若觸碰到這些檔案需同 PR 提 ceiling update。

## Key Technical Decisions

- **Phase 1 = 啟動，不重新實作**：006/007 Unit 全部 `[x]`，Phase 1 只需 operator 動作 + plist commit，不需要新 Python 代碼（除非 recheck timeout 評估後決定補）。
- **mastodon enforce 在 Phase 1 啟用（Unit 9 operator-gate）**：Unit 8 已解決損毀災難模式，啟用成本低，應儘快取得首次真實 `skipped_policy` 事件作為 Phase 2 信號基礎。
- **probe-citations plist 先確認 API 配額**：Perplexity v1 rate limit 決定 `--max-batch` 和 `StartCalendarInterval`；若配額不足則降為 stretch goal，不強制。
- **HTTP 統一前置 radon 掃描**：27 個 `import requests` 檔案，必須先跑 radon 確認哪些超 ceiling，才能評估 Phase 2 真實工作量。
- **plan-gap 排程腳本放 `scripts/`（bash wrapper）**：避免觸碰 monolith_budget.toml 監控的 cli/ 路徑；shell 腳本難測試的代價小於引發 CI 預算衝突的成本。
- **自治閉環保留人工確認**：plan-gap 腳本輸出推薦列表，operator 確認後才執行 plan-backlinks。不自動 publish。

## Open Questions

### Resolved During Planning

- **mastodon enforce 的先決條件是否滿足？** 是。006 Unit 8（損毀態降級 + 告警源解耦）已 `[x]`，Unit 9 接線已建；只需 operator-gate 動作。
- **plan-gap 腳本放 scripts/ 還是新 CLI entrypoint？** 放 `scripts/`（bash wrapper），避免 monolith budget 衝突。
- **citation panel 是否需要 CSRF guard？** 不需要。`/ce:health` 是 GET-only，現有 `_global_csrf_guard` 只攔 POST/PUT/PATCH/DELETE。

### Deferred to Implementation

- **Perplexity v1 API 日配額確切數字**：Phase 1 Unit 3 開始前必須確認，決定 `--max-batch` 和觸發頻率。若配額不足，R3 plist 降頻或 R12 降為 stretch goal。
- **recheck per-probe timeout 是否納入 Phase 1**：daily recheck 已無人值守，R10 resume trigger 已觸發。實作者應評估 `socket.settimeout` 或 `signal.alarm` 的加入成本，若輕量則同 Phase 1 進；否則列為 Phase 2 前置。
- **HTTP 統一的實際 SLOC 衝突範圍**：Phase 2 Unit 1 前置步驟，先 `radon raw -s` 掃 27 個檔案，列出超 ceiling 者。

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```
Phase 1 (M1)
  ├── [operator] enforce-allowlist add mastodon → verify skipped_policy in events.db
  ├── [plist commit] com.dex.bp-citations.plist  (daily, after quota confirmed)
  ├── [plist commit] com.dex.bp-weights.plist    (weekly)
  └── [audit] debt_registry.toml mitigated → resolved review

Phase 2 (M2)
  ├── /ce:health citation panel
  │     └── GET handler → _g_cache → geo/share.py query → health.html section
  ├── HTTP unification
  │     └── radon scan → per-file patch → _util/http_client.py unified call
  ├── decay alert
  │     └── recheck events → compare 14d window → events.db decay.alert → health.html banner
  └── weights snapshot
        └── weights show → /ce:health health_metrics.py → health.html section

Phase 3 (M3)
  ├── plan-gap weekly script
  │     └── scripts/run-plan-gap-weekly.sh: equity-ledger | plan-gap | tee output
  ├── autopilot page: last plan-gap result
  │     └── sites.py GET: read last plan-gap output → sites.html new row
  └── citation share gate (gated on Perplexity quota)
        └── probe-citations --fail-on-low-share → autopilot notify
```

## Implementation Units

### Phase 1 — 激活 + 排程化

- [x] **Unit 1: mastodon enforce 啟用（operator-gate）** — landed `e3522764`

**Goal:** 取得首次真實 `skipped_policy` 事件，驗證 enforce layer 在生產環境可靠攔截。

**Requirements:** R1

**Dependencies:** 確認 006 Unit 8 已 `[x]`（已完成）。

**Files:**
- Verify/Modify: `src/backlink_publisher/publishing/reliability/allowlist.py`（或 enforce config key）
- Verify: `src/backlink_publisher/publishing/reliability/policy.py`
- Verify: `webui_app/routes/health.py`（/ce:health rollout 面板）

**Approach:**
- 確認 enforce-allowlist 的 config key 位置（Unit 7 建立的結構）
- 在 allowlist 中加入 `mastodon`
- 執行一次 dry-run publish-backlinks，確認 `skipped_policy` 事件出現在 events.db
- 若 events.db 有記錄，驗收 /ce:health 的 mastodon rollout 面板顯示 `enforce` 模式

**Patterns to follow:** `publishing/reliability/events_store.py::append_reliability_decision()`（讀取端驗收）

**Test scenarios:**
- Happy path: allowlist 加入 mastodon 後，publish-backlinks 對低品質 mastodon link 回傳 `skipped_policy`；events.db 有對應記錄；/ce:health mastodon channel 顯示 mode=enforce
- Error path: allowlist config 路徑錯誤時，policy.py 應 fallback 到 observe 並 log warning，不 crash

**Verification:** `events.db` 中有 `would_skip_policy` 或 `skipped_policy` 事件，且 `channel = mastodon`；/ce:health 面板 mastodon 顯示 `enforce`

---

- [x] **Unit 2: 007 plist 驗收 + install runbook 完整化** — landed `18e13ba4` (plists + runbooks verified on disk 2026-06-16)

**Goal:** 確保 daily recheck plist 和 selector-drift plist 的 commit 完整且 runbook 可操作。

**Requirements:** R2

**Dependencies:** None（007 已完成）。

**Files:**
- Verify: `scripts/com.dex.bp-recheck.plist`
- Verify/Create: `scripts/com.dex.bp-selector-drift.plist`（若尚未 commit）
- Verify/Update: `docs/operations/recheck-backlinks-runbook.md`
- Verify/Update: `docs/operations/selector-drift-runbook.md`（若尚未建立）

**Approach:**
- 逐一確認 plist 格式：`WorkingDirectory` 中文路徑、stdout/stderr 合併、`RunAtLoad: false`、env 顯式列
- 確認 runbook 有 `launchctl load` 指令、log 檔路徑、手動觸發方式
- 若 selector-drift plist 尚未 commit，補建（比照 recheck plist 格式）

**Test scenarios:**
- Happy path: `launchctl load scripts/com.dex.bp-recheck.plist` 後 `launchctl list | grep bp-recheck` 顯示 job 存在，不立即執行
- Edge case: plist 的 WorkingDirectory 不存在時 launchd job 失敗且寫 log，不 silent

**Verification:** 兩個 plist 均在 `scripts/` 且已 commit；runbook 文件可按指引完成安裝

---

- [x] **Unit 3: probe-citations 每日排程 plist** — landed `2cdf71b0`

**Goal:** probe-citations 每日自動執行，citation.observed 事件持續進 events.db。

**Requirements:** R3

**Dependencies:** **前置確認 Perplexity v1 API 日配額**（決定 `--max-batch` 和觸發時間）。

**Files:**
- Create: `scripts/com.dex.bp-citations.plist`
- Create: `scripts/run-citations-periodic.sh`（bash wrapper，比照 `run-recheck-periodic.sh`）
- Create/Update: `docs/operations/probe-citations-runbook.md`

**Approach:**
- 先確認 Perplexity v1 API rate limit（`geo/perplexity.py` 中的文件或 API key 測試）
- 根據配額設定 `--max-batch` 和 `StartCalendarInterval`（若配額低，降頻至每 12h 或更低）
- plist 格式比照 `com.dex.bp-recheck.plist`：bash wrapper + 中文 WorkingDirectory + 合併 log + RunAtLoad: false
- EnvironmentVariables 需列 `PATH`、`BP_LANG`、Perplexity API key env 名稱（實際 key 不寫進 plist，從 config 讀）
- runbook 含配額說明、調整 `--max-batch` 的指引

**Patterns to follow:** `scripts/com.dex.bp-recheck.plist`、`scripts/run-recheck-periodic.sh`

**Test scenarios:**
- Happy path: `launchctl load` 後，手動觸發 wrapper script，`events.db` 中出現新的 `citation.observed` 事件
- Edge case: Perplexity API 配額耗盡時，script 以非零退出且寫 log，不重試死循環
- Edge case: events.db 不存在時，script 失敗且有明確錯誤訊息

**Verification:** plist committed；手動執行 wrapper 後 events.db 有 `citation.observed`；runbook 文件完整

---

- [x] **Unit 4: weights 週排程 plist** — landed `9f05bbdc`

**Goal:** `weights optimize` 每週自動執行，優化後的 channel 權重供下輪發布使用。

**Requirements:** R4

**Dependencies:** Unit 3 plist 格式確認後（共用格式慣例）。

**Files:**
- Create: `scripts/com.dex.bp-weights.plist`
- Create: `scripts/run-weights-weekly.sh`
- Create/Update: `docs/operations/weights-runbook.md`

**Approach:**
- `weights` CLI subcommands: `collect` → `optimize` → `show`。週排程跑 `collect` + `optimize` 的組合
- `StartCalendarInterval` 設為每週一 03:00（低流量時段，不與 recheck 04:30 衝突）
- plist 格式比照 recheck plist；log 路徑：`logs/weights-launchd.log`
- `weights optimize` 的結果寫入 events.db（Unit 9 [x] 已建立路徑）；runbook 說明如何手動 `weights show` 驗證

**Patterns to follow:** `scripts/com.dex.bp-recheck.plist`

**Test scenarios:**
- Happy path: 手動執行 wrapper，`weights show` 顯示更新後的 channel 分數；events.db 有對應 optimize 事件
- Edge case: events.db 無歷史資料時，`weights collect` 應 exit 0 並輸出 empty payload 提示，不 crash

**Verification:** plist committed；手動執行後 `weights show` 顯示最新優化結果

---

- [x] **Unit 5: debt_registry.toml mitigated 項稽查** — landed `534e169f` (8 resolved / 1 accepted)

**Goal:** 確認所有 `mitigated` 項的狀態是否可升為 `resolved`，恢復技術債的信號價值。

**Requirements:** R5

**Dependencies:** None。

**Files:**
- Modify: `debt_registry.toml`（視稽查結果）
- Verify: `tests/test_debt_registry_format.py`（schema 約束）

**Approach:**
- 逐條核實現有 `mitigated` 項（對照 2026-06-15 audit 結論）
- 確認各項的 `resolved_date` 欄位格式符合 test_debt_registry_format.py schema
- 可升為 `resolved` 者更新狀態；仍有殘留工作者補充 note；保留 `accepted` 項不動

**Test scenarios:**
- Happy path: 更新後 `pytest tests/test_debt_registry_format.py` 全綠
- Edge case: 若 `resolved_date` 欄位對 `resolved` 狀態是必填（schema 要求），確認補齊後再提 PR

**Verification:** `pytest tests/test_debt_registry_format.py` 通過；`mitigated` 項均有理由標注

---

### Phase 2 — 信號延伸 + HTTP 統一

- [x] **Unit 6: /ce:health citation 面板** — landed `0eb91c6f`

**Goal:** operator 在 /ce:health 可看到 per-target citation 分布（site_cited / article_cited / absent）+ 7d rolling 趨勢計數。

**Requirements:** R6

**Dependencies:** Unit 3（citation.observed 事件需有資料累積後才有意義）。

**Files:**
- Modify: `webui_app/routes/health.py`（新增 citation panel 資料查詢）
- Modify: `webui_app/health_metrics.py`（新增 `citation_panel()` 函數）
- Modify: `webui_app/templates/health.html`（新增 citation 區塊）
- Test: `tests/test_webui_health_routes.py`（或同等 health route 測試檔）

**Approach:**
- 查詢路徑：`events.db` → `WHERE kind = 'citation.observed'` + `WHERE ts > now - 7d` → group by target + verdict
- 用 `_g_cache('citation_panel', citation_panel)` 包裝（read-only GET，CI gate 要求）
- 函數 CC ≤ 30（否則同 PR 更新 `complexity_budget.toml` + 80 char rationale）
- 模板新增 collapsible card（比照 /ce:health 現有 channel rollout 面板的 Bootstrap card 格式）
- 資料為空時（citation.observed 尚無記錄）顯示 「尚無 citation 記錄 — 請先執行 probe-citations」，不顯示錯誤

**Patterns to follow:**
- `webui_app/routes/health.py` 的 `_g_cache` 使用方式
- `docs/solutions/best-practices/webui-config-request-cache-governance-2026-06-03.md`

**Test scenarios:**
- Happy path: events.db 有 7d 內 citation.observed 記錄，GET /ce:health 回傳 200，panel 含 site_cited 計數
- Edge case: events.db 空時，panel 顯示「尚無記錄」提示，不 500
- Edge case: events.db 只有 7d 外的舊記錄，7d rolling 顯示 0（不顯示舊資料）
- Integration: `_g_cache` 確保同一 request context 內 citation_panel() 只呼叫一次（CI gate test）

**Verification:** GET /ce:health 包含 citation 區塊；`pytest tests/test_webui_request_cache.py` 通過

---

- [x] **Unit 7: HTTP client 統一（radon 門控 + 分批收口）** — ✅ complete. batch 1 `98677dd6` (27→17 檔); batch 2 收口 (#33/#35/#36/#37/#38): tumblr/linkedin/config_driven/image_gen/rentry/hatena/provider 遷至 http_client（新增 `raise_for_status=False` + `allow_private=True` opt-out），http_form_post 結構性保留 raw（重試會重複非冪等 POST + 遮蔽 503 反爬信號）但內聯 `_guard_ssrf`。剩餘 7 個 allowlist 全為結構性豁免。gate `test_no_raw_requests_outside_http_client` 凍結成果

**Goal:** src/ 內所有裸 `import requests` 收口為 `_util/http_client.py`，SSL context 統一，消除不一致的 verify 行為。

**Requirements:** R7

**Dependencies:** **前置步驟**（實作開始前執行）：
```
python -m radon raw -s src/backlink_publisher/<每個含 import requests 的檔案>
```
列出超 ceiling 的檔案，決定是否需要 monolith_budget.toml 同 PR 更新。

**Files:**
- Modify: （先跑 radon，再列出具體 27 個目標檔案）
- Key targets（已知）: `geo/perplexity.py`、`content/_http.py`、`publishing/session/provider.py`
- Modify if needed: `monolith_budget.toml`（超 ceiling 者）
- Test: 各模組的現有測試應全綠（無新測試必要，行為不變）

**Approach:**
- 分批收口，優先處理 geo/ 和 content/ 等 Phase 2 信號路徑上的熱點
- 每個替換保持語義等價：`requests.get(url, timeout=...)` → `http_client.get(url, timeout=...)`
- SSL context 統一：`BACKLINK_NO_FETCH_VERIFY` env var 的處理移到 http_client 層
- 若某個模組有特殊 session 需求（如 cookie-based），記錄為 deferred exception，不強制收口
- 超 SLOC ceiling 的檔案：同 PR 在 `monolith_budget.toml` 提高 ceiling + ≥80 char rationale

**Patterns to follow:** `src/backlink_publisher/_util/http_session.py`、`_util/http_client.py`

**Test scenarios:**
- Happy path: 替換後，各模組現有測試全綠（行為等價驗證）
- Edge case: `BACKLINK_NO_FETCH_VERIFY=1` 時，替換後的路徑仍跳過 SSL verify（一致性）
- Error path: `http_client` 拋出 timeout 時，各模組的 caller 仍能正確捕獲異常（不因包裝層改變異常類型）

**Verification:** `grep -r "import requests" src/` 輸出為空（或只有合理的 exception 清單）；所有現有測試通過；`python -m radon raw -s` 受影響檔案均未超 ceiling

---

- [x] **Unit 8: Decay alert（14d 掉 ≥2 條 dofollow 鏈告警）** — landed `0eb91c6f`

**Goal:** 當同一目標在 14d 內失去 ≥2 條 dofollow backlink 時，自動寫入 events.db 並在 /ce:health 顯示 banner。

**Requirements:** R8

**Dependencies:** recheck-backlinks 每日排程（007 R1，已完成）提供資料。

**Files:**
- Create: `src/backlink_publisher/events/kinds.py`（新增 `decay.alert` kind）
- Create: `src/backlink_publisher/cli/decay_alert.py`（或 `recheck_backlinks.py` 內部函數）
- Modify: `webui_app/routes/health.py`（新增 decay banner 資料）
- Modify: `webui_app/templates/health.html`（新增 decay banner）
- Modify: `src/backlink_publisher/events/kinds.py`（KINDS + REQUIRED_FIELDS 登記）
- Test: `tests/test_decay_alert.py`

**Approach:**
- `decay.alert` kind 登記：KINDS frozenset 加入 `decay.alert`；REQUIRED_FIELDS 加入 `{target_url, lost_count, window_days}`；platform 放 payload
- 查詢邏輯：`events.db` → `WHERE kind = 'link.rechecked' AND status = 'dead' AND ts > now - 14d` → group by `(target, url)` → 相同 `(target, url)` 對只計一次（避免持續死亡重複計算）→ distinct dead urls per target ≥ 2 → append `decay.alert`
- 去重邏輯：寫入前查 `decay.alert WHERE target_url = ? AND ts > now - 14d`，已存在則 skip（防止每個 recheck 周期重複觸發；持續死亡只告警一次直到人工解決）
- 排程：decay alert 查詢可在 recheck wrapper script 結束後觸發（`scripts/run-recheck-periodic.sh` 末尾加一行），不需獨立 plist
- /ce:health banner：若 7d 內有 `decay.alert`，顯示紅色 alert banner（比照 autopilot-alert-banner 格式）

**Patterns to follow:**
- `src/backlink_publisher/events/kinds.py`（kind 登記格式）
- `referral/store.py::append_referral_observed`（direct-append 模式）
- `webui_app/templates/health.html` 現有 alert banner 格式

**Test scenarios:**
- Happy path: events.db 有同一 target 在 14d 內 2 條 dead 記錄 → `decay.alert` 事件寫入 → /ce:health 顯示 banner
- Edge case: 同 target 只有 1 條 dead 記錄（不觸發）
- Edge case: 2 條 dead 但超過 14d（不觸發）
- Edge case: decay.alert 已存在且未解決時，不重複寫入（dedup 邏輯）
- Integration: `pytest tests/test_decay_alert.py` + `pytest tests/test_webui_request_cache.py`（health route cache 合規）

**Verification:** 手動插入 2 條 `link.rechecked dead` 事件後，`decay.alert` 出現在 events.db；/ce:health 顯示 banner

---

- [x] **Unit 9: /ce:health weights 快照** — landed `c1096690`

**Goal:** /ce:health 顯示最新 weights optimize 時間戳 + top 3 channel 分數變化。

**Requirements:** R9

**Dependencies:** Unit 4（weights plist 已運行，events.db 有 optimize 結果）。**注意**：在首次 weights 任務觸發前，此 panel 輸出為空屬預期行為；Phase 2 開始後若 weights 尚未跑過，顯示「尚未執行 weights optimize」即可。

**Files:**
- Modify: `webui_app/health_metrics.py`（新增 `weights_snapshot()` 函數）
- Modify: `webui_app/routes/health.py`（接入 weights_snapshot）
- Modify: `webui_app/templates/health.html`（新增 weights 區塊）
- Test: `tests/test_webui_health_routes.py`

**Approach:**
- 查詢：`events.db` → 最新 weights optimize 事件 → 取 payload 的 top_channels（如有）
- 展示：上次優化時間戳 + top 3 channel 的 before/after 分數差（若有 diff 資料）
- 無資料時顯示「尚未執行 weights optimize」
- 用 `_g_cache` 包裝（read-only GET）

**Test scenarios:**
- Happy path: events.db 有 optimize 事件，/ce:health 顯示時間戳和 channel 分數
- Edge case: events.db 無 optimize 記錄，顯示提示訊息，不 500

**Verification:** GET /ce:health 包含 weights 區塊；手動跑 `weights optimize` 後區塊更新

---

### Phase 3 — 自治閉環

- [x] **Unit 10: plan-gap 週排程腳本**

**Goal:** `equity-ledger | plan-gap` 每週自動執行並輸出補鏈 seed 建議，operator 確認後執行。

**Requirements:** R10

**Dependencies:** Unit 4（weights plist 已建立，提供優化後的 channel 權重供 plan-gap 使用）。

**Files:**
- Create: `scripts/run-plan-gap-weekly.sh`（bash wrapper）
- Create: `scripts/com.dex.bp-plan-gap.plist`
- Create/Update: `docs/operations/plan-gap-runbook.md`

**Approach:**
- Script 開頭必須有 `set -euo pipefail`：確保 equity-ledger pipe 非零退出時 wrapper 立即失敗，不把空 stdin 傳給 plan-gap
- Script 組合：`equity-ledger | plan-gap --desired N --language LANG > <abs_path>/logs/plan-gap-latest.json.tmp && mv <abs_path>/logs/plan-gap-latest.json.tmp <abs_path>/logs/plan-gap-latest.json`（tmp→rename 確保原子寫入；`<abs_path>` 用 git root 絕對路徑，不用相對 `logs/`）
- `plan-gap` 只輸出 `plan-backlinks` 相容 seed JSONL，不直接生成文章也不 publish（operator 確認後才跑真實 plan-backlinks）
- `StartCalendarInterval`：每週日 02:00（低流量，和 weights 週一 03:00 相差一天）
- 輸出存至絕對路徑的 `logs/plan-gap-latest.json`，供 Unit 11 autopilot 頁面讀取
- 確認 `logs/plan-gap-latest.json` 在 `.gitignore`（launchd 每次執行都更新）
- plist 格式比照現有範本

**Test scenarios:**
- Happy path: 手動執行 wrapper，`logs/plan-gap-latest.json` 生成，包含推薦 seeds
- Edge case: equity-ledger 輸出空（無缺口目標）時，plan-gap 應 exit 0 並輸出空 JSONL，不 crash
- Edge case: plan-gap 執行超過 10 分鐘（launchd timeout 前），確認 flock 或 timeout 機制存在

**Verification:** `logs/plan-gap-latest.json` 生成後包含有效的 plan-backlinks seed JSONL 或空 JSONL；wrapper 設定 `PYTHONPATH="$BP_DIR/src:$BP_DIR"`，launchd 下 `python -m backlink_publisher...` 可解析套件。

---

- [x] **Unit 11: autopilot 狀態頁擴展（plan-gap 結果）**

**Goal:** sites.html 的 autopilot 區域顯示「上次 plan-gap 結果」—— 補鏈 seed 候選數 / 涉及目標數 / 觸發時間。

**Requirements:** R11

**Dependencies:** Unit 10（`logs/plan-gap-latest.json` 存在）。

**Files:**
- Modify: `webui_app/routes/sites.py`（GET /sites 讀取 plan-gap latest output）
- Modify: `webui_app/templates/sites.html`（新增 plan-gap 結果區塊）
- Test: `tests/test_webui_sites_routes.py`

**Approach:**
- GET /sites handler 讀取 plan-gap-latest.json，路徑使用與 Unit 10 wrapper 相同的絕對路徑（從 config 的 CONFIG_DIR / git root 環境變數讀取，不使用相對 `logs/`，否則 launchd WorkingDirectory 和 WebUI 啟動路徑不同時會對不上）
- 若檔案不存在，顯示「plan-gap 尚未執行」
- 跨進程 RMW 評估：`logs/plan-gap-latest.json` 是 **寫入由 launchd job，讀取由 WebUI**，屬於 single-writer 模式（不是 RMW）。`fcntl.flock` 只需在寫入側（wrapper 用 tmp→rename，已在 Unit 10 明確）；讀取側 catch `FileNotFoundError` + `JSONDecodeError` 即可，不需 RLock。路徑必須用絕對路徑（同 Unit 10 的 WorkingDirectory 一致）。

**Patterns to follow:** `webui_app/routes/sites.py` 現有 `sites_form()` 資料構建模式

**Test scenarios:**
- Happy path: `logs/plan-gap-latest.json` 存在，GET /sites 顯示已補鏈數和仍缺鏈數
- Edge case: 檔案不存在，顯示「尚未執行」提示，不 500
- Edge case: JSON 格式損毀（launchd job 中斷），顯示錯誤提示，不 crash

**Verification:** GET /sites 包含 plan-gap 結果區塊；`pytest tests/test_webui_sites_routes.py` 通過

---

- [x] **Unit 12: citation share health gate（gated on Perplexity 配額確認）** — landed `1aa3e1ef`

**Goal:** 低 citation share 的目標在 autopilot 通知中標記為 replanning 優先級。

**Requirements:** R12

**Dependencies:** Unit 3（probe-citations 已排程且配額充足）；R12 在 Unit 3 配額確認後決定是否執行。

**Files:**
- Modify: `src/backlink_publisher/geo/share.py`（新增 low-share 閾值判斷）
- Modify: `src/backlink_publisher/cli/probe_citations.py`（`--fail-on-low-share` flag 接入 share.py）
- Modify: `scripts/run-citations-periodic.sh`（加入 `--fail-on-low-share` 並捕獲退出碼）
- Modify: `webui_app/routes/health.py` 或 `sites.py`（顯示低 share 目標的 replanning 標記）
- Test: `tests/test_citation_share_gate.py`

**Approach:**
- `geo/share.py` 新增 `low_share_targets(threshold=0.2)` 函數：查 events.db 最新 citation.observed，計算 site_cited / total，低於閾值的 target 列表
- `--fail-on-low-share` exit code 語義（必須明確）：
  - exit 0：所有 above-floor target 均達標 OR 全部 target 均為 warming_up/never_probed（suppress）
  - exit 非零：至少一個 above-floor target 低於 threshold（無論是否有其他 target 被 suppress）
  - 混合情境（部分 target warming_up，部分 above-floor 低份額）→ exit 非零（suppress 只跳過 warming_up，不影響判定）
- 週排程 wrapper 捕獲非零退出 → 寫入 `logs/citation-low-share.json`
- health panel 或 autopilot page 讀取 low-share list，顯示 replanning 建議

**Patterns to follow:**
- `geo/verdict.py`（verdict 分類）、`geo/share.py`（現有 share 計算）
- `probe_citations.py` 的 `--fail-on-low-share` 旗標設計（Plan 2026-05-29-006 已有接口描述）

**Test scenarios:**
- Happy path: 有 above-floor target 且 share < threshold，exit 非零，low-share list 寫入 logs
- Edge case: 所有 target 均 warming_up / never_probed，exit 0（suppress）
- Edge case: share ≥ threshold 時，exit 0，不寫 low-share list
- Integration: `scripts/run-citations-periodic.sh` 執行後，health panel 正確顯示低 share 目標

**Verification:** `probe-citations --fail-on-low-share` 在低 share target 存在時 exit ≠ 0；health panel 顯示 replanning 建議

---

## System-Wide Impact

- **Interaction graph**: launchd plists（Unit 3/4/10）與 WebUI 共用 `events.db`（寫/讀分離，single-writer 模式，不需 RLock）；`logs/plan-gap-latest.json` 由 launchd 寫、WebUI 讀（需 write-side flock）
- **Error propagation**: launchd jobs 的 stderr 寫 log 檔，exit 非零由 launchd 記錄；WebUI 讀取 log 或 json 失敗時顯示提示訊息，不上升為 500
- **State lifecycle risks**: decay.alert 的 dedup 邏輯需防止重複寫入；plan-gap latest.json 的原子寫入（tmp → rename）防止讀到半寫檔
- **API surface parity**: /ce:health 新增 citation panel 和 weights snapshot 不改變現有路由 contract；sites.html 新增 plan-gap 區塊不改變現有 form 結構
- **Integration coverage**: `_g_cache` 合規（Unit 6/8/9）必須接受 `tests/test_webui_request_cache.py` 驗證；events.db kinds 登記必須通過 `tests/test_events_kinds.py`（若存在）
- **Unchanged invariants**: publish pipeline（plan→validate→publish→recheck）不受本計劃修改；enforce 只影響 mastodon channel，其他 channel 保持 observe

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Perplexity v1 API 配額不足 | 先確認配額再設 plist；配額低則降頻 or R12 降為 stretch goal |
| HTTP 統一（27 檔）觸碰 monolith ceiling | 前置 radon 掃描；超限者同 PR 提 rationale；分批 PR 降低 blast radius |
| decay.alert dedup 失效（重複寫入） | 寫入前查詢最近 24h 同 target 的 decay.alert，存在則 skip |
| plan-gap weekly script 執行時間過長 | tmp→rename 原子寫入；若 recheck wrapper 無 timeout，plist 改 StartInterval（skip overlapping）直到 timeout 補齊 |
| webui.db 跨進程 RMW（Phase 3 sites.py 讀 plan-gap JSON） | plan-gap JSON 用獨立 log 檔（不寫 webui.db）；讀取側 catch FileNotFoundError + JSONDecodeError |
| citation panel CC > 30 | 拆 health_metrics.py 的 citation_panel() 為多個小函數；同 PR 更新 complexity_budget.toml |
| bash wrapper（Unit 10）無法自動化測試 | edge case 驗收靠「手動執行 + 觀察 log」；CI 無法 catch wrapper 迴歸。此為已知限制，scripts/ 選擇的代價已接受 |
| logs/*.json 進入 git dirty tree | Unit 10 實作前確認 .gitignore 有 `logs/*.json` 或明確條目 |

## Documentation / Operational Notes

- 每個新 plist 配一份 runbook（`docs/operations/`），包含：install 指令、手動觸發方式、log 路徑、配額說明（probe-citations）
- Phase 1 Unit 1 的 mastodon enforce 啟用需記錄啟用時間戳和首次 skipped_policy 事件 ID，作為 enforce layer 的「第一次被信任的攔截」里程碑

## Phased Delivery

### Phase 1 — M1（4 週）
Units 1–5：掃尾 006/007，建立 plist 基礎設施，取得首次 enforce 事件。

### Phase 2 — M2（4 週）
Units 6–9：信號視覺化（citation panel、weights snapshot）+ HTTP 統一 + decay 保護。

### Phase 3 — M3（4 週）
Units 10–12：自治閉環（plan-gap 自動化、autopilot 擴展、citation gate）。

## Sources & References

- **Origin document**: [docs/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md](docs/brainstorms/2026-06-16-comprehensive-optimization-roadmap-requirements.md)
- Related plans: `docs/plans/2026-06-15-006-feat-reliability-observe-to-enforce-plan.md`（enforce layer，Unit 9 operator-gate）
- Related plans: `docs/plans/2026-06-15-007-feat-reliability-signal-freshness-plan.md`（daily recheck plist，Units 1-2 [x]）
- Related plans: `docs/plans/2026-05-29-006-feat-geo-citation-closed-loop-plan.md`（probe-citations CLI，Unit 7）
- Launchd pattern reference: `scripts/com.dex.bp-recheck.plist`
- WebUI cache governance: `docs/solutions/best-practices/webui-config-request-cache-governance-2026-06-03.md`
- Events.db direct-append pattern: `src/backlink_publisher/referral/store.py::append_referral_observed`
