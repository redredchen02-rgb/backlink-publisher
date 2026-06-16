---
title: "feat: Autopilot 狀態可視性"
type: feat
status: active
date: 2026-06-16
origin: docs/brainstorms/2026-06-16-autopilot-status-visibility-requirements.md
---

# feat: Autopilot 狀態可視性

## Overview

操作員設定 autopilot toggle 後缺乏確認感：不知道排程是否真的掛上、下次何時執行、上次是否
成功。後端資料（`schedule_store.autopilot_targets[url].{alert_pending, last_run}`、
APScheduler `job.next_run_time`）已完整存在，缺的只是呈現層。

本計畫分四個單元：擴充 GET /sites 路由資料 → 更新 sites.html 狀態欄 →
擴充 POST /sites/autopilot 回應 JSON 與 sites.js toggle 即時回饋 →
在 health.html 現有 `autopilot-alert-banner` 加入計數徽章與跳轉連結。

(see origin: docs/brainstorms/2026-06-16-autopilot-status-visibility-requirements.md)

## Problem Frame

`sites.html` 的 autopilot 列只呈現 toggle 狀態；`autopilot-row-status` span 僅在 toggle
動作時短暫更新，頁面重整後即清空。操作員無法從 sites 頁面確認排程是否真正在運作，也無法
從 `/ce:health` 一眼看出有幾個 site 失敗。

## Requirements Trace

- R1. 每個 site 列依優先級顯示：未啟用→空白；已停止→灰色；失敗→紅色警示；正常→下次時間
- R2. 狀態由後端 GET /sites 模板渲染時靜態注入（no AJAX 輪詢）
- R3. Toggle 後即時回饋顯示「✓ 已排程，下次：{相對時間}」
- R4. `/ce:health` 現有 `autopilot-alert-banner` 加入失敗計數徽章與 /sites 連結
- R5. POST /sites/autopilot 回應加入 `next_run_time`、`last_run` 欄位

## Scope Boundaries

- 🚫 不做 WebSocket/SSE 推播
- 🚫 不改 history 頁面、APScheduler job 執行邏輯
- 🚫 不新增獨立 autopilot 監控頁面
- 「已停止」為 JS transient state（toggle 動作後短暫顯示）；頁面重整後 `enabled=false` 的
  site 顯示空白（`—`），不需持久化「已停止」狀態

## Context & Research

### Relevant Code and Patterns

- `webui_app/routes/sites.py:60-78` — `sites_form()` 的 `all_sites` 建構段落；
  需在此段落加入 `alert_pending`、`next_run_time_iso` 欄位
- `webui_app/routes/sites.py:246-300` — `sites_autopilot()` POST handler；
  目前回傳 `{ok, site_url, enabled}`，需加 `next_run_time`、`last_run`
- `webui_app/scheduler.py:265-277` — `_autopilot_job_id()` 與 `_register_autopilot_job()`；
  scheduler module 在 routes 中以 `sys.modules['webui_app.scheduler']` 存取
- `webui_app/scheduler.py:319-330` — `_update_autopilot()` 寫入 `last_run` + `alert_pending`；
  成功時 `alert_pending=False`，失敗時 `alert_pending=True`（**自動清除**，無需額外改動）
- `webui_app/templates/sites.html:174-222` — `autopilot-sites-tbody` 表格；
  `autopilot-row-status` span 目前為空，需從後端 data attribute 初始化
- `webui_app/static/js/sites.js:147-173` — `toggle-autopilot` handler；
  成功後寫 `'已启用 ✓'`，需改為含相對時間的文字
- `webui_app/static/js/lib/api.js` — 共用 `postJson`、`readCsrf`；sites.js 已匯入
- `webui_app/templates/health.html:86-112` — 現有 `autopilot-alert-banner`；
  有 dismiss 按鈕但無計數徽章與 /sites 導覽連結
- `webui_app/routes/health.py:483-491` — `_autopilot_alerts()` 已建構 site list 並傳入模板

### Test Patterns

- `tests/test_webui_sites_routes.py:226-300` — `_make_mock_scheduler()` 工廠函式，
  使用 `types.ModuleType` + `monkeypatch.setitem(sys.modules, 'webui_app.scheduler', mock)`；
  mock 的 `_scheduler` 屬性是 `MagicMock`，可設 `get_job().next_run_time`
- `tests/test_webui_sites_routes.py:21-64` — conftest fixtures：`client`、`csrf_client`

### Institutional Learnings

- APScheduler `BackgroundScheduler` 無 `timezone=` 參數，`job.next_run_time` 為
  host 本地時區的 tz-aware datetime。直接呼叫 `.isoformat()` 輸出即可，前端
  `new Date(isoStr)` 能正確解析 tz-aware ISO string
- `datetime.now(timezone.utc)` 已用於 `last_run` 寫入（scheduler.py:311）；
  `next_run_time` 為本地時區但 tz-aware，兩者都能被前端 `Date` 正確處理

## Key Technical Decisions

- **相對時間：前端計算**：後端輸出 ISO timestamp，前端 `formatRelative(isoStr)` 用
  `new Date()` 計算。避免靜態 HTML 時間字串過期問題；不需 bundler 也不需外部 library
- **`_scheduler` 存取**：GET /sites 採用與 POST handler 相同模式：
  `sys.modules.get('webui_app.scheduler')` 取得 module（注意 `.get()` 不是 `[]`，
  scheduler 尚未載入時不應 500）；再呼叫 `mod._scheduler.get_job(job_id)`
- **get_job() = None fallback**：`enabled=true` 但 `get_job()=None` 時，
  `next_run_time_iso=None`；模板渲染為空白，與「未啟用」視覺相同（不顯示錯誤）
- **「已停止」是 transient JS state**：toggle 關閉後 JS 顯示「已停止」；
  頁面重整後 `enabled=false` 的 site 後端不傳 next_run_time，模板顯示 `—`
- **R4 計數徽章**：直接在 health.html 現有 `{% if autopilot_alerts %}` 區塊加
  `{{ autopilot_alerts|length }}` 計數，加 `/sites` 跳轉連結；不新增路由

## Open Questions

### Resolved During Planning

- **時區**：`job.next_run_time` 是本地時區 tz-aware；直接 `.isoformat()` 輸出，
  前端 `new Date(isoStr)` 正確解析，無需 UTC 轉換
- **格式化責任**：前端 JS（`formatRelative()`），不需 Jinja filter
- **alert_pending 清除**：scheduler.py:325 已在成功時自動清除，**無需改動**
- **get_job() = None**：顯示空白，與未啟用行為一致
- **R4 掛載點**：`health.html` 第 87 行 `autopilot-alert-banner` 現有區塊

### Deferred to Implementation

- `formatRelative()` 的精確本地化字串（「3 小時後」vs「in 3 hours」）：
  實作時參考現有 UI 語言（中文）決定輸出格式
- `all_sites` 擴充是否需要 `try/except` 保護 `get_job()` 呼叫：
  實作時確認 APScheduler MagicMock 行為是否需要調整 `_make_mock_scheduler`

## Implementation Units

- [ ] **Unit 1: GET /sites 路由擴充 — 加入 autopilot 狀態欄位**

**Goal:** `all_sites` 每項加入 `alert_pending`、`next_run_time_iso`，讓模板無需 AJAX 即可渲染狀態

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- Modify: `webui_app/routes/sites.py` — `sites_form()` only（Unit 3 另行修改 `sites_autopilot()`）
- Test: `tests/test_webui_sites_routes.py`

**Approach:**
- 在 `sites_form()` 的 `all_sites` 建構段落，讀取 `ap_cfg.get('alert_pending', False)` 和 `ap_cfg.get('last_run')`
- 取 scheduler module：`_sched_mod = sys.modules.get('webui_app.scheduler')`
- 若 module 存在且 `ap_cfg.get('enabled')`：先確認 `getattr(_sched_mod, '_scheduler', None)` 非 None，再呼叫 `.get_job(job_id)` 取 `job.next_run_time`；呼叫 `.isoformat()` 或若 `None` 則設 `None`
- 若 module 不存在或 `_scheduler` 尚未初始化：`next_run_time_iso = None`（不 raise）
- `all_sites` 每項新增：`"alert_pending": bool(...)`, `"next_run_time_iso": str | None`

**Patterns to follow:**
- `sites.py:289-295` — POST handler 的 `sys.modules['webui_app.scheduler']` 存取；GET 版本改用 `.get()` 做 graceful fallback
- `ap_cfg.get(...)` 已在現有 `all_sites` 建構中使用

**Test scenarios:**
- **Happy path**: enabled site with registered job → `all_sites` entry has `next_run_time_iso` as ISO string, `alert_pending=False`
- **Failure state**: `alert_pending=True` in store → entry has `alert_pending=True`
- **Scheduler unavailable** (module not in sys.modules): `next_run_time_iso=None`, no exception
- **Scheduler module present but _scheduler unstarted** (`_scheduler` attribute is None): `next_run_time_iso=None`, no AttributeError
- **get_job() returns None**: `next_run_time_iso=None`, `alert_pending` still reflects store value
- **Disabled site** (`enabled=False`): `next_run_time_iso=None`, `alert_pending=False`
- **GET /sites returns 200** with expanded `all_sites` context passed to template

**Verification:**
- `GET /sites` 在測試中傳入 monkeypatched scheduler module 時，response 200 且模板 context 含 `alert_pending`、`next_run_time_iso` 欄位

---

- [ ] **Unit 2: sites.html 狀態欄顯示**

**Goal:** autopilot 表格加入狀態欄，依優先級呈現 R1 定義的四種狀態

**Requirements:** R1, R2

**Dependencies:** Unit 1

**Files:**
- Modify: `webui_app/templates/sites.html`

**Approach:**
- 在 autopilot 表格 header 加 `<th>狀態</th>`
- 在每列 `<tr>` 加 `<td>` 依優先級渲染：
  - `not site.autopilot_enabled`：`<span class="text-muted">—</span>`
  - `site.autopilot_enabled and site.alert_pending`：`<span class="text-danger small" role="status">⚠ 上次失敗</span>`
  - `site.autopilot_enabled and site.next_run_time_iso`：`<span class="text-success small autopilot-next-run" data-next-run="{{ site.next_run_time_iso }}" aria-label="下次執行時間">⏭ 計算中…</span>`（JS 填入）
  - 其餘（enabled 但無 job）：`<span class="text-muted small">排程中…</span>`
- 現有 `autopilot-row-status` span 保留（toggle 動作後 JS 寫入即時回饋）

**Patterns to follow:**
- `health.html:88-112` — 現有 `alert-danger` / `text-danger` 使用方式
- `sites.html:261` — `batch-row-status` 的 `<td>` 寫法
- 使用 `aria-live="polite"` 和 `role="status"` 保持 a11y 一致性

**Test scenarios:**
- Test expectation: none — template rendering; visual outcomes verified in browser walkthrough

**Verification:**
- 進入 sites 頁面：已啟用且有 job 的 site 顯示「⏭ 計算中…」欄（JS 會填入相對時間）；失敗 site 顯示紅色「⚠ 上次失敗」；未啟用顯示 `—`

---

- [ ] **Unit 3: POST /sites/autopilot 回應擴充 + sites.js toggle 即時回饋**

**Goal:** POST 回應加入 `next_run_time`、`last_run`；toggle 成功後即時顯示相對時間

**Requirements:** R3, R5

**Dependencies:** None（可與 Unit 1 並行；Unit 4 依賴本單元）

**Files:**
- Modify: `webui_app/routes/sites.py` — `sites_autopilot()` return 段落
- Modify: `webui_app/static/js/sites.js` — toggle handler + 新增 `formatRelative()`
- Test: `tests/test_webui_sites_routes.py`

**Approach:**

*後端（sites.py）：*
- 在 `sites_autopilot()` 末尾，`_register_autopilot_job()` 成功後：
  - 呼叫 `_sched_mod._scheduler.get_job(job_id)` 取 `next_run_time`（可為 None）
  - 從 `schedule_store.load()` 讀 `last_run`（同 site URL）
  - 回傳 `{"ok": True, "site_url": ..., "enabled": ..., "next_run_time": iso_or_null, "last_run": iso_or_null}`
- disable 時 `next_run_time=None`（job 已 remove）

*前端（sites.js）：*
- 在 module 頂層加 `formatRelative(isoStr)` helper：
  - 用 `new Date(isoStr)` 計算距今秒數
  - 回傳「X 分鐘後」/「X 小時後」/「明天」等中文字串
  - 輸入 null 或無效時回傳 null
- 修改 `toggle-autopilot` handler 成功分支：
  - 從 `postJson` 回應讀取 `next_run_time`
  - 若有值：`statusCell.textContent = '✓ 已排程，下次：' + formatRelative(next_run_time)`
  - 若無值：`statusCell.textContent = '✓ 已排程'`
  - disabled：`statusCell.textContent = '已停止'`（維持現有邏輯）
- 頁面載入時，對所有 `.autopilot-next-run[data-next-run]` 元素套用 `formatRelative()`

**Patterns to follow:**
- `sites.js:2` — `import { postJson } from './lib/api.js'` 已完成，不需額外匯入
- `sites.js:160-165` — 現有 toggle 成功/失敗分支；新邏輯在成功分支內延伸
- `scheduler.py:295-296` — `_sched_mod._scheduler.get_job(job_id)` 的存取模式

**Test scenarios:**
- **POST enable → next_run_time present**: mock `get_job().next_run_time` returns datetime → response JSON has `next_run_time` as ISO string
- **POST enable → get_job() returns None**: response JSON has `next_run_time: null`, `ok: true` (不 500)
- **POST disable**: response JSON has `next_run_time: null`, `last_run` 為上次 cycle 的時間戳，若從未執行過則為 null（toggle 動作本身不寫入 last_run）
- **Response schema regression**: existing fields `{ok, site_url, enabled}` still present

**Verification:**
- 在 sites 頁面開啟 autopilot toggle：`autopilot-row-status` span 立即顯示「✓ 已排程，下次：X 小時後」（或無 job 時「✓ 已排程」），不需重整

---

- [ ] **Unit 4: health.html autopilot-alert-banner 計數徽章與跳轉連結**

**Goal:** `/ce:health` 頁面的失敗 banner 加入計數徽章與「前往 /sites」連結，操作員一眼知道幾個失敗

**Requirements:** R4

**Dependencies:** None（health.html 後端資料已就緒）

**Files:**
- Modify: `webui_app/templates/health.html`

**Approach:**
- 在 `autopilot-alert-banner` 的 `<strong>Autopilot 故障：</strong>` 後加
  `<span class="badge bg-danger ms-1">{{ autopilot_alerts|length }}</span>`
- 在 banner 標題行（`<strong>` 所在的 `<div>`）加 `<a href="/sites" class="ms-auto btn btn-sm btn-outline-danger">前往 /sites →</a>`，方便一鍵跳轉
- 不移除現有 per-site dismiss 按鈕（`/dashboard/autopilot-alert/dismiss` 仍可使用）

**Patterns to follow:**
- `health.html:88` — 現有 `alert alert-danger` 結構；徽章加在 `<strong>` 後
- `base.html` — Bootstrap `badge bg-danger`、`btn btn-sm btn-outline-danger` 已可用

**Test scenarios:**
- Test expectation: none — template rendering only; verified via browser walkthrough

**Verification:**
- 製造 `alert_pending=True` 的 site，進入 `/ce:health`：banner 顯示「Autopilot 故障：<badge>1</badge>」；「前往 /sites →」連結可點擊

## System-Wide Impact

- **Interaction graph:** `sites_form()` 新增 `sys.modules.get('webui_app.scheduler')` 呼叫；
  若 scheduler 尚未初始化（測試環境/冷啟動）需保持 graceful（`.get()` 回 None 即跳過）
- **Error propagation:** `get_job()` 可能在 job 執行中回傳不同 `next_run_time`；
  這是可接受的 transient state，不需特殊處理
- **State lifecycle risks:** `alert_pending` 清除仍由 `scheduler.py:325` 的 success path 負責；
  本計畫只讀取，不改寫清除邏輯，無狀態競爭風險
- **Unchanged invariants:**
  - POST `/sites/autopilot` 的 `{ok, site_url, enabled}` 欄位保留（backward-compat）
  - `autopilot-alert-banner` 現有 dismiss per-site 功能不變
  - APScheduler job 執行邏輯完全不動

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `get_job()` 在 job 執行中回傳 None（APScheduler 版本差異） | 已有 None fallback：顯示「排程中…」而非錯誤 |
| `sys.modules.get('webui_app.scheduler')` 在測試時為 None | GET /sites 用 `.get()` 不是 `[]`，返回 `next_run_time_iso=None` 不 500 |
| 相對時間字串在頁面長時間停留後過期 | 已知且接受（scope boundary）；操作員重整即更新 |
| `_make_mock_scheduler()` 沒有 `get_job()` 方法 | `MagicMock()` 預設任意屬性回 MagicMock；需在新測試中設定 `mock_sch.get_job.return_value.next_run_time` |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-16-autopilot-status-visibility-requirements.md](docs/brainstorms/2026-06-16-autopilot-status-visibility-requirements.md)
- Autopilot route: `webui_app/routes/sites.py:246-300`
- Scheduler module: `webui_app/scheduler.py:265-335`
- Health alert banner: `webui_app/templates/health.html:86-112`
- Existing autopilot tests: `tests/test_webui_sites_routes.py:226-345`
