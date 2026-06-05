---
title: "feat: Per-link liveness drill-down drawer under the channel scorecard"
type: feat
status: completed
date: 2026-06-05
deepened: 2026-06-05
origin: docs/brainstorms/2026-06-05-backlink-liveness-tracking-loop-requirements.md
---

# feat: Per-link liveness drill-down drawer under the channel scorecard

## Overview

外鏈存活的**宏觀層已經有了**——`build_channel_scorecard()` 逐平台聚合 `live_pct` /
`live_dofollow` / `liveness_breakdown` / `small_sample`，server-render 在 health 頁的
channel scorecard 卡（card 3a）。本計畫只補**微觀層**：在 scorecard 每一列底下加一個
**可展開的逐條鏈結抽屜**（fetch-on-expand），讓操作者點某平台就看到它底下每一條
published URL 的最新 verdict + 最後檢查時間，並能對單條即時重檢。讀取型，不接回發布器。

實查數據（origin 文件）支持此範圍：已重檢 88 條中 78 條（89%）是真實目標，telegraph
57 條 / blogger 25 條有強訊號——抽屜有真實鏈結可鑽。

**抽屜是「重檢歷史視圖」，非「已發布鏈結清冊」**：U1 只讀 `link.rechecked` 事件，覆蓋率
~5%，故抽屜只照已重檢的鏈結。U3 標頭顯示「已重檢 N 條」讓此契約明示，避免操作者把
「telegraph 抽屜 3 列」誤讀為「telegraph 只有 3 條鏈結」。

## Problem Frame

操作者能看到「某平台平均存活」，但看不到該平台底下**每一條鏈結各自的生死**——無法逐條
trackable，也無法對單條即時重檢。底層 5 級 verdict 與 events.db `link.rechecked` 時間
序列都已存在，缺的只是把它攤到既有記分板下的一個抽屜。（see origin:
docs/brainstorms/2026-06-05-backlink-liveness-tracking-loop-requirements.md）

**修正 origin 假設**：origin 文件假設宿主是 `webui_app/health_metrics.py`；實際 scorecard
由 `routes/health.py` 的 `ce_health` → `_scorecard_rows()`（route 內變數名 `channel_scorecard`，
:312）提供，template 以 `{% set scorecard_rows = channel_scorecard | default([]) %}` 別名後
`{% for c in scorecard_rows %}` render（`health.html:227,248`，7 欄表）。本計畫以實際路徑為準。

## Requirements Trace

- R1. scorecard 每列可展開，看到該平台底下每一條已發布鏈結的獨立列；資料源為 events.db
  `link.rechecked` 取每條鏈結**最新** verdict。
- R2. 每條列顯示：published URL（= `live_url`）、平台、最新 verdict（ALIVE / HOST_GONE /
  LINK_STRIPPED / DOFOLLOW_LOST / PROBE_ERROR）、最後檢查時間（`ts_utc`）。
- R3. 單條即時重檢，**必須走會寫 `link.rechecked` 的 keepalive 路徑**（`recheck_link` →
  `emit_recheck`），重檢後該列就地更新；不可用不發事件的 `recheck_one`。
- R4. PROBE_ERROR 列照常顯示，但不計入任何存活率分母。verdict badge 須帶**文字標籤**
  （非僅顏色），讓 PROBE_ERROR 與其他 verdict 可區辨（a11y + R4 語義）。
- R5. **dofollow 狀態**（非 raw rel 字串）只在「目標確實被檢視過」時顯示，否則 n/a。
  **修正（code-verified）**：`emit_recheck` payload **不存** `target_rel`（probe 算了但落地時丟棄），
  只存 `confirmed_dofollow` / `confirmed_nofollow` / `expected_nofollow` 布林——故顯示的是
  「此鏈結是否保住 dofollow」而非 rel 字串。`anchor_drift` **有**落地，沿用其值。**判斷
  「檢視過」不能只看 verdict==ALIVE**：`probe.py` 的 `if not target:` 分支會回 ALIVE 卻沒
  檢視 backlink（`anchor_baseline_missing`/無 inspected 訊號）→ 須用更強的 inspected 謂詞。
- R6. 抽屜逐條**預設排除測試/保留網域來源**，按 host label（網域邊界感知）比對 `target_url`，
  非裸字串 suffix（避免 `myexample.com` 誤殺）。**實查釘定（events.db 2026-06-05）**：生產
  rechecked 鏈結的 target 只有 `51acgs.com`(真,78) 與 `example.com`(測,10)——唯一污染是
  `example.com` 及其子網域（如 `blogger.example.com`）。故執行期排除集 = `example.com` + 子網域；
  另含 RFC2606 `example.net/example.org` + `.example` 保留 TLD 作防禦並讓單元測試邊界有意義。
  **注意**：`money.example`/`site.com`/`a.com` 等只在 tests/ fixture 出現、**不在生產 target**，
  故為單元測試覆蓋對象、非執行期必要成員。
- R7. 讀取型——抽屜不修改 plan-gap / 發布優先級 / 平台白名單。
- R8. **U4 只接受已發布鏈結的識別碼**：client 傳 `live_url` 作 lookup key，route 須在
  events.db 已發布集合中反查、不存在回 404/結構化錯誤、**不發探測**；只有反查到的紀錄
  URL 可進 `recheck_link`。防盲 SSRF（mirror `equity_ledger_recheck` 的安全前例）。

## Scope Boundaries

- **不**重建平台聚合記分板——複用既有 `build_channel_scorecard`。
- **不**做逐條 verdict 篩選/排序（~73 條真實鏈結量級不需要；origin 已降級為 deferred）。
- **不**自動接回發布決策。**不**改 verdict 分類 / events schema / 偵測引擎。
  （含義：不為了 R5 去 emit `target_rel`——改用已落地的 dofollow 布林。）
- **不**做自動排程重檢（cron 屬既有 plan 的 UPGRADE）；R3 的逐條即時重檢在範圍內。
- **不**做 anchor-drift 修復工作流（僅在「檢視過」列顯示標記）。**不**接 GA4/GSC。
- **並行課題（不在本案）**：重檢覆蓋率僅 ~5%，提升覆蓋（bulk-recheck/排程）另起 plan。
- **不**消除「抽屜 per-link vs 記分板 per-target」的視圖差異——這是兩種正確粒度，靠 UI 說明，
  不靠對齊（見 Key Technical Decisions / System-Wide Impact）。

## Context & Research

### Relevant Code and Patterns

- **Scorecard 宿主**：`webui_app/routes/health.py:279-312` `_scorecard_rows()`（變數 `channel_scorecard`，
  `_g_cache` 快取、fail-open 回 `[]`）→ `templates/health.html:226-274` card 3a，
  `{% set scorecard_rows = channel_scorecard | default([]) %}` + `{% for c in scorecard_rows %}`
  server-render `<tr>`（7 欄，無 rowspan/colspan → sibling detail-row 須 `colspan=7`）。
- **Scorecard 引擎**：`scorecard/engine.py:112` `build_channel_scorecard(...)`；`engine.py:56`
  `_platform_by_live_url`（從 articles JOIN，排除 NULL-live_url/NULL-article_id）。
- **逐條讀取的權威範本**：`recheck/overlay.py:172` `build_discount_map`——已做「latest-per-link
  keyed on canonical `live_url`、article_id fallback、`(ts_utc,id)` tiebreaker、無 NULL 過濾」
  的掃描（:188-220），**但 collapse 成 per-target 折扣計數、`continue` 跳過 ALIVE/PROBE_ERROR、
  丟棄 rel/drift**——故 per-link list 仍須新建。`recheck/events_io.py:140` `derive_per_target_status`
  **有 `article_id IS NOT NULL` 陷阱**（SQL :166-169），勿用。
- **⚠ overlay 是「用完即丟」模組**（`overlay.py:1-17` docstring：R6-proper 落地即退役）。其
  `_canon_target`/`_is_newer` 為前導底線私有；`scorecard/` 目前**零依賴** `recheck/`。直接跨包引
  私有名 = 把永久視圖綁在待刪 scaffolding 上（見 Risks / U1 Approach 的緩解）。
- **最新-verdict-per-link 去重已解**：`ledger/aggregate.py` `_load_confirmed_dofollow_urls` 用
  `canonicalize_url` + `(ts_utc, event_id)` recency 排序。
- **emit_recheck payload（唯一 `link.rechecked` 寫入者，`events_io.py:72-92）`**：含 verdict /
  reason / live_url / platform / expected_nofollow / anchor_drift / anchor_baseline_missing /
  indexability / indexability_reason / source / confirmed_dofollow / confirmed_nofollow。
  **不含 `target_rel`**（R5 依此修正）。
- **重檢探測**：`recheck/probe.py:195-235` `recheck_link(record, probe=True)`，預設 `timeout=10.0`；
  **ALIVE 可讀路徑做兩段循序抓取**（`inspect_target_anchor` :117 + `_probe_indexability` :143，
  各 10s）→ 最壞 ~20s。`if not target:`（:147-149）回 ALIVE 但未檢視 backlink。candidate 形狀
  （`selection.py:231-246`）：live_url/target_url/host/article_id/platform/baseline_anchor…
  （`recheck_link` 只讀其中數鍵、忽略多餘鍵）。
- **安全前例（U8/R8 必抄）**：`routes/equity_ledger.py:104-120` `equity_ledger_recheck`——client
  `target_url` **僅作 lookup key**，canonicalize 後在 store 反查、缺則 404、只探測**反查到**的
  URL，從不探 client 字串。Origin guard `helpers/security.py:130` `_check_bind_origin_or_abort`
  （keep_alive.py:20 import、:45 呼叫）。SSRF 網路層 `_util/net_safety.py:20-27`（擋 RFC1918+
  loopback+link-local+Azure wireserver；公網目標**不擋**——故需 R8 成員檢查）。
- **前端慣用法**：`static/js/equity.js:226-255` expand idiom（sibling `<tr class="detail-row d-none">`
  + `.expand` toggle + `aria-expanded`）——**但其 detail row 為同步 in-memory 渲染（:242-243），
  無 fetch-on-expand**，故載入/錯誤狀態無範本，須自定（U3）。`equity.js` 用單一 module-level
  `recheckBusy` 全域鎖 + 單一共享 `#recheckStatus` aria-live（`equity_ledger.html:100`）——
  ~57 列各有重檢鈕時不夠（須逐列鎖，見 U4）。`lib/api.js` `readCsrf()`/`postJson`；`esc()`/
  `truncMiddle`（URL 截斷）。

### Institutional Learnings

- `docs/solutions/logic-errors/2026-06-05-001-live-dofollow-undercounting-triple-gap.md`：
  `article_id IS NULL` 陷阱實證（22/44 unverified 為 NULL）；fallback `live_url → article_id`；
  最新-verdict 去重用 `(ts_utc, event_id)`。
- `docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md`：操作者判斷
  server-side 算好注入，別把 verdict/platform 邏輯送 client。
- `docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift-2026-05-26.md`：只查
  `events/kinds.py` 註冊 kind；勿在持寫鎖時開第二 SQLite 連線（WAL 死鎖）。
- `docs/solutions/best-practices/app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md`：
  勿加 per-route CSRF（app 級 guard 已覆蓋）；JS 送 `X-CSRFToken`，測試 seed `session['csrf_token']`，
  `monkeypatch.setitem(...WTF_CSRF_ENABLED, True)` 強制姿態。
- `docs/solutions/best-practices/webui-config-request-cache-governance-2026-06-03.md`：讀 config 走
  `_g_cache('config', load_config)`（AST CI gate）。
- `docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md`：
  顯示**目標 backlink 自己的** dofollow 狀態，非頁面級 `nofollow_detected`（會誤報 nav/footer）。
- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`：
  測試用 `monkeypatch.setenv/delenv`，勿裸 `del os.environ[...]`。

### External References

- 不適用——純內部 WebUI 改動，已有強本地樣板。

## Key Technical Decisions

- **抽屜採 fetch-on-expand（GET），非 server-render 全量**：per-link events.db 掃描非輕量，
  fetch-on-expand 把重掃留在展開時。**注意**：equity.js 的 expand idiom 是同步渲染，給不出
  載入/錯誤狀態範本——U3 須自定三態（pending / loaded-empty / load-error），且 U2 回傳須帶
  `{ok, links}` 狀態旗標，否則 fail-open 的 `{links:[]}` 會把後端錯誤偽裝成「空」。
- **逐條讀取 key on `live_url`，新建函式，但抽共用 iterator**：既有函式皆 collapse 成 counts。
  新函式照 overlay 的 live_url 鍵 + `(ts_utc,event_id)` 去重。**為免把永久視圖綁在 overlay
  待刪私有函式上**，先把 latest-verdict-per-link iterator（overlay.py:202-220 的迴圈，含
  NULL-article_id 不變式）抽到穩定公開位置（`recheck` public API 或 `_util`），讓
  `build_discount_map` 與新 `derive_links_by_channel` 共用——勿複製（複製 = 兩份不變式會 drift，
  正是 two-truths）。
- **R5 改用已落地的 dofollow 布林（code-verified）**：`target_rel` 從未寫進 events.db；顯示
  `confirmed_dofollow`/`confirmed_nofollow`/`expected_nofollow` 推導的 dofollow 狀態，語義上即
  操作者要的「此鏈結是否保住 dofollow」。閘門用「目標確實檢視過」謂詞（非 verdict==ALIVE）。
- **R5/R6 在讀取函式邊界落實**：對「未檢視」列把 dofollow/anchor_drift 歸 n/a；用保留域集排除測試
  資料——讓「資料誠實」成為資料契約。
- **「兩個真相」是兩種正確粒度，靠說明不靠對齊（code-verified 修正）**：抽屜按 `live_url` 逐鏈、
  overlay 的平台存活按 `target_url` 逐目標且「同目標有兄弟鏈活著就保平台」（`apply_discounts`
  overlay.py:289-294）。一條 LINK_STRIPPED 的鏈結可正確地出現在仍被記分板計為 live 的平台下。
  **不宣稱消除**，U3 加 UI 說明（「平台層存活看記分板，此處為單鏈狀態」）。
- **單條重檢同步內聯，顯式 timeout**：單鏈一次操作，但 ALIVE 路徑是**兩段循序抓取（~2×timeout）**。
  U4 顯式傳較短 timeout（如 5s）、文件載明 ~2×timeout 最壞值；確認 flask-limiter 覆蓋此 POST
  或加 per-session debounce（防雙擊洗 worker）。async 降級（`start_recheck(candidates=[record])`）
  列為 deferred，僅當實測延遲過高。
- **U4 強制 events.db 成員反查（R8，安全硬需求）**：抄 `equity_ledger_recheck`——client live_url
  僅作 key，反查不到不探測。

## Open Questions

### Resolved During Planning

- 宿主視圖？→ `routes/health.py` channel scorecard 卡（變數 `channel_scorecard`/別名 `scorecard_rows`）。
- 逐條讀取重用還是新建？→ 新建 `scorecard/links.py`，但先抽共用 iterator 到穩定位置再複用。
- 哪條重檢路徑？→ keepalive（`recheck_link`+`emit_recheck`），同步內聯、顯式 timeout。
- R5 rel 來源？→ **`target_rel` 未落地**，改用 `confirmed_dofollow`/`confirmed_nofollow` 布林。
- R5 閘門？→「目標確實檢視過」謂詞，非 verdict==ALIVE（涵蓋 no-target ALIVE 漏洞）。
- example.com 過濾？→ **實查釘定**：生產唯一污染 = `example.com` + 子網域；排除集再加 RFC2606
  `example.net/.org` + `.example` TLD 防禦。host-label 比對。fixture 的 `money.example`/`site.com`
  等只在測試、非執行期成員。
- U4 SSRF？→ 強制 events.db 成員反查，非 client 字串直探。
- 低樣本/RYG？→ 不在本案；per-channel small_sample 已由既有 scorecard 處理。

### Deferred to Implementation

- 共用 latest-per-link iterator 的最終公開位置與簽章——讀 overlay/events_io 實際耦合後定。
- U4 candidate record 精確欄位組裝對齊 `selection.select_candidates` 形狀——讀實際後定。
- ~~保留域集的精確成員~~——**已查定**（見 R6）：生產唯一污染 example.com + 子網域，餘為防禦集。
- U4 顯式 timeout 的確切秒數（5s?）與 flask-limiter 規則——量測單探測實際延遲後定。

## High-Level Technical Design

> *以下示意意圖、供審查驗證方向，非實作規格；實作代理視為脈絡，勿照抄。*

```
展開某平台列
   │  GET /ce:health/scorecard/<channel>/links
   ▼
U2 route ──reads──▶ U1 derive_links_by_channel(store)
   │                   │ WHERE kind=LINK_RECHECKED（無 NULL 過濾）
   │                   │ key on canonical live_url，(ts_utc,event_id) 取最新
   │                   │ channel 解析 _platform_by_live_url；保留域集排除測試
   │                   │ 「檢視過」謂詞為真才填 dofollow/anchor_drift，否則 n/a
   ▼                   ▼
{ok:true, links:[{live_url, verdict, last_recheck_ts,
                  dofollow_state|null, anchor_drift|null}, ...]}
   │  （錯誤時 {ok:false}；空時 {ok:true, links:[]} — 兩者前端區辨）
   ▼
U3 抽屜渲染（三態 pending/empty/error；verdict 文字標籤；esc()/truncMiddle）
   │  逐列 [重檢] 鈕（per-row 鎖，非全域）
   ▼  POST /ce:health/scorecard/recheck-link  {live_url}
U4 route ── R8 反查 events.db 成員 → 不存在則 404，不探測
   │         存在 → recheck_link(reverified_record, probe=True, timeout=5)
   │         → emit_recheck(store,[result])（寫 link.rechecked）
   ▼  {ok, verdict, last_recheck_ts, error_code?}（call-fail≠PROBE_ERROR-verdict）
就地更新該列 + aria-live（含列識別）
```

## Implementation Units

```
U1 (read fn + shared iterator) ──▶ U2 (GET drawer route) ──▶ U3 (drawer frontend) ──▶ U4 (single-link recheck)
```

- [x] **Unit 1: Shared latest-verdict iterator + per-link read function** — done in clone `~/bp-per-link-u1` @ `9531f60` (branch `feat/per-link-liveness-u1`), 25 tests green, regression-clean (overlay/engine/keep-alive/gap/cli), ce:review passed (no P0/P1; type hints + coverage + stale-comment fixes applied), push held.

**Goal:** 抽出共用的 latest-verdict-per-link iterator（含 NULL-article_id 不變式）到穩定位置，
新增 `derive_links_by_channel`，落實 R5（dofollow 布林 + inspected 謂詞）與 R6（保留域集排除）。

**Requirements:** R1, R2, R4, R5, R6

**Dependencies:** None

**Files:**
- Create: `src/backlink_publisher/scorecard/links.py`
- Modify: `src/backlink_publisher/recheck/overlay.py`（或新 `recheck/_recency.py`：抽出共用 iterator）
- Modify: `src/backlink_publisher/recheck/events_io.py`（若 iterator 移位，更新既有 import）
- Test: `tests/test_scorecard_links.py`

**Approach:**
- 先抽 `build_discount_map` 的 latest-verdict-per-link 迴圈（overlay.py:202-220）為公開共用件，
  `build_discount_map` 與新函式共用，避免不變式 drift（two-truths 根因）。
- `derive_links_by_channel(store, *, exclude_test=True) -> dict[str, list[LinkVerdictRow]]`：
  SQL `WHERE kind=LINK_RECHECKED`（**無** `article_id IS NOT NULL`），以 payload `live_url`
  canonical 為主鍵、`(ts_utc,event_id)` 取最新。channel 解析用 `engine._platform_by_live_url`，
  payload `platform` fallback。
- **R5**：dofollow 狀態由 `confirmed_dofollow`/`confirmed_nofollow`/`expected_nofollow` 推導
  （**非** `target_rel`，後者未落地）。`dofollow_state` 與 `anchor_drift` **僅當「目標確實檢視過」
  謂詞為真**才填（例如有 inspected anchor 訊號 / `anchor_baseline_missing` 為 False），否則 None——
  涵蓋 `if not target:` 的 no-target ALIVE 漏洞。
- **R6**：以網域邊界感知的保留域集（RFC2606 `example.com/.net/.org` + `.example` TLD + 專案佔位
  含 `money.example`）按 host label 比對 `target_url`，`exclude_test=True` 時排除。
- **LinkVerdictRow 為穩定契約**：永遠含 `live_url, target_url, channel, verdict, last_recheck_ts,
  dofollow_state|None, anchor_drift|None`——非 ALIVE/未檢視列設 None 而非略去欄位。
- 只查 `events/kinds.py` 註冊的 `LINK_RECHECKED`；勿在持寫鎖開第二連線；CC ≤ 30。

**Execution note:** 先寫失敗測試鎖定 R5 inspected 謂詞與 R6 保留域集邊界。

**Patterns to follow:** `recheck/overlay.py` `build_discount_map`（live_url 鍵）；
`ledger/aggregate.py` `_load_confirmed_dofollow_urls`（去重排序）。

**Test scenarios:**
- Happy path: 兩平台多筆 `link.rechecked`、同 live_url 多筆 → 只回最新、分組正確。
- Edge（tiebreaker）: 同 live_url 同 ts 不同 event_id → `(ts_utc,event_id)` 決勝、確定性。
- Edge（NULL-article_id 陷阱）: 種 `article_id=NULL` 的列 → **必現於結果**（證未被過濾丟掉）。
- R5（資料缺欄）: 種一筆 ALIVE 但 payload 無 `target_rel`（真實情況）→ 不崩、dofollow_state 由
  `confirmed_dofollow` 推導。
- R5（no-target ALIVE 漏洞）: 種 verdict=ALIVE 但 `target_url=None`/`anchor_baseline_missing=True`
  → `dofollow_state`/`anchor_drift` 回 None（n/a），不顯示誤導「正常」。
- R5（死鏈預設值）: verdict=LINK_STRIPPED/HOST_GONE/PROBE_ERROR 且 payload `anchor_drift=False`
  → 回 None，不顯示「無漂移」。
- R6（保留域集）: `target_url` 為 `money.example` / `a.example`（`.example` TLD）/ `site.com`
  / `blog.example.com`（子網域）→ `exclude_test=True` 皆排除；`myexample.com`（lookalike）**不**誤殺。
- R4: PROBE_ERROR 列存在於輸出、攜帶可供上層排除分母的標記。

**Verification:** 對混合 verdict / NULL-article_id / 測試域 / 缺欄的種子回傳確定、誠實的 per-link 列。

- [ ] **Unit 2: Read-only GET route serving drawer data**

**Goal:** 新增 fetch-on-expand 唯讀 route，回傳某 channel 的 per-link 列 JSON，帶 `{ok}` 狀態
旗標讓前端區辨「空」與「錯誤」。

**Requirements:** R1, R2, R4, R7

**Dependencies:** Unit 1

**Files:**
- Modify: `webui_app/routes/health.py`
- Test: `tests/test_health_scorecard_links_route.py`

**Approach:**
- `GET /ce:health/scorecard/<channel>/links`，呼叫 U1 取該 channel 列、回 `{"ok": true, "links": [...]}`。
- **Fail-open 但可區辨**：try/except → 回 `{"ok": false, "links": []}`（仿 `_scorecard_rows`
  :292 fail-open，但加 `ok` 旗標——避免後端錯誤被前端誤判為「空」）。GET 永不 500。
- config 走 `_g_cache('config', load_config)`。唯讀，無 CSRF/Origin（GET）。`<channel>` 須參數化
  查詢/字典查找，不可拼接 SQL。
- server-side 算好所有判斷再注入（勿把 verdict 邏輯送 client）。
- **效能（U1 ce:review advisory）**：`derive_links_by_channel` 一次回**全平台**（兩個全表掃描：
  latest_link_verdicts + _platform_by_live_url）。route 須**一次呼叫拿所有 channel** 後按
  `<channel>` 取該鍵，**勿**每個 channel 各呼叫一次；並用 `_g_cache('scorecard_links', …)` 快取
  整個結果於請求生命週期，避免重複掃描。

**Patterns to follow:** `routes/health.py` `_scorecard_rows()` fail-open + `_g_cache`。

**Test scenarios:**
- Happy path: 種資料 GET `/ce:health/scorecard/telegraph/links` → 200，`{ok:true, links:[...]}` 欄位齊全。
- Edge: 未知/無紀錄 channel → 200 `{ok:true, links:[]}`（合法空，非錯誤）。
- Error path: U1 拋例外（monkeypatch）→ 200 `{ok:false, links:[]}`，不 500（前端可辨為錯誤）。
- Security: `<channel>` 含 SQL/特殊字元 → 參數化/字典查找，無注入、無 500。
- R7: GET、無任何寫入/狀態變更。

**Verification:** 展開取得逐條 JSON；空與錯誤可由 `ok` 區辨；壞資料下頁面不崩。

- [ ] **Unit 3: Drawer frontend (expand + render + states)**

**Goal:** scorecard 每列加展開鈕，展開 fetch U2 並渲染逐條列，含三態、verdict 文字標籤、
per-link vs per-target 說明、安全 DOM。

**Requirements:** R1, R2, R4, R5

**Dependencies:** Unit 2

**Files:**
- Modify: `webui_app/templates/health.html`（card 3a `<tr>` 加 `.expand` 鈕 + sibling
  `<tr class="detail-row d-none"><td colspan="7">`；標頭一行 UI 說明 per-link vs per-target）
- Create: `webui_app/static/js/scorecard.js`
- Test: `tests/test_health_channel_scorecard_card.py`（擴充既有檔；**注意檔名**為
  `test_health_channel_scorecard_card.py`，非 `test_health_scorecard_card.py`）

**Approach:**
- 抄 `equity.js:226-255` 抽屜骨架，但**補 equity.js 沒有的 fetch-on-expand 三態**：
  (1) pending（fetch 進行中：skeleton/spinner 列 + chevron pending 姿態）；
  (2) loaded-empty（`{ok:true, links:[]}` → 「此平台尚無重檢紀錄」）；
  (3) load-error（`{ok:false}` 或 fetch throw/非 200/非 JSON → 錯誤態 + 重試鈕）。
- **不快取，每次展開重 fetch**（量小 ~57，且 U4 重檢後需反映新值——消除 U3 cache 與 U4 整合
  測試的矛盾）。
- 用 `createElement`/`textContent`/`esc()` 建列，URL 用 `truncMiddle` + `title=` 全值；**不**把
  未信任 URL 塞 innerHTML。
- verdict badge **帶文字標籤**（ALIVE/STRIPPED/…），非僅顏色（R4/a11y）。
- dofollow_state / anchor_drift 僅「檢視過」列顯示，否則 "—"（R5）。
- 標頭一行說明：「平台層存活以上方記分板為準；此處為單鏈最新狀態」（化解 two-truths 困惑）。
- `data-action` 委派監聽；script tag 帶 `v=asset_version`。

**Patterns to follow:** `equity.js` expand idiom + `esc()`/`truncMiddle`；`keep_alive.js` 委派監聽。

**Test scenarios:**
- Happy path（route/render）: GET health 頁含每 channel 列 `.expand` 鈕與 `aria-expanded`；
  注入種子後抽屜 fetch 回的列含 verdict 文字標籤/時間/URL。
- Edge（三態）: `{ok:true,links:[]}` → 空態文案；`{ok:false}` → 錯誤態 + 重試（**非**空態）。
- R5: 未檢視列 dofollow/drift 顯「—」而非「dofollow/無漂移」。
- R4/a11y: 各 verdict badge 含可辨文字標籤（非僅顏色）。
- Integration: 展開 → fetch U2 → 列數與種子相符（route+前端串接）。
- Security: live_url 含 `<script>` 樣字串 → 經 esc()/textContent 不執行。

**Verification:** 操作者能展開任一平台、看到逐條列且三態正確、死鏈不顯示誤導資訊。

- [ ] **Unit 4: Single-link recheck (membership-guarded button + route)**

**Goal:** 抽屜每列加「重檢」鈕，經 events.db 成員反查後走 keepalive 路徑同步重檢、就地更新該列。

**Requirements:** R3, R8

**Dependencies:** Unit 3

**Files:**
- Modify: `webui_app/routes/health.py`（新增 `POST /ce:health/scorecard/recheck-link`）
- Modify: `webui_app/static/js/scorecard.js`（per-row 重檢鈕 + aria-live + 就地更新）
- Modify: `webui_app/templates/health.html`（aria-live `#recheckStatus` region）
- Test: `tests/test_webui_scorecard_recheck_link_route.py`（integration tier）

**Approach:**
- **R8 成員反查（安全硬需求）**：client 傳 `live_url` 僅作 key；route 在 events.db 已發布集合
  （U1 讀取/`_platform_by_live_url`）反查，**不存在回 404/結構化錯誤、不發探測**；只有反查到的
  紀錄 URL 組 candidate。抄 `equity_ledger_recheck:104-120` 安全前例，**勿**直接拿 request 欄位
  組 candidate。
- candidate 欄位（live_url/target_url/host/platform/article_id）對齊 `selection.select_candidates`
  形狀；呼叫 `recheck_link(record, probe=True, timeout=<5s>)` + `emit_recheck(store,[result])`。
- **顯式 timeout**（ALIVE 路徑 ~2×timeout 兩段抓取）；確認 flask-limiter 覆蓋此 POST 或加 debounce。
- 強制 `_check_bind_origin_or_abort()`（出站探測；`from ..helpers.security import` 之，非從
  keep_alive 複製）；CSRF 由 app 級 guard 自動，**勿**加 per-route token。
- 回傳**誠實結構化結果** `{ok, verdict, last_recheck_ts, error_code?, flash_msg?}`：**區辨**
  「重檢 call 失敗」（`ok:false`，保留原 verdict badge、提示重試）與「重檢成功但 verdict=PROBE_ERROR」
  （`ok:true`，badge 更新為 PROBE_ERROR、套 R4 排除分母語義）。勿吞例外/勿回假 ok/勿寫半截事件。
- 前端 `lib/api.js` `postJson`（送 `X-CSRFToken`）；**per-row 鎖**（停用該列鈕 + spinner，
  非全域 `recheckBusy`）；aria-live 訊息含列識別（哪條 URL）。

**Execution note:** 先寫失敗的路由整合測試鎖定契約（含 R8 成員 404、Origin 403、CSRF 姿態、
call-fail≠PROBE_ERROR-verdict）。

**Patterns to follow:** `equity_ledger_recheck`（成員反查安全前例）；`keep_alive.py` Origin guard；
`equity.js` 就地更新 + aria-live；`tests/test_webui_keepalive_recheck_route.py`（Origin +
`disable_csrf` + integration tier）。

**Test scenarios:**
- Happy path: POST 一條**已發布** live_url（monkeypatch probe 回 ALIVE）→ 200、回新 verdict，
  且**寫了一筆 `link.rechecked`**（直接查 SQLite 證明，非經 build_ledger）。
- R8（SSRF 守衛）: POST 一條**不在** events.db 的 live_url → 404/結構化錯誤、**未發任何探測**
  （斷言 probe 未被呼叫）。
- R3 路徑守衛: 斷言走 `emit_recheck`（事件 +1），非 `recheck_one`。
- 區辨: 重檢成功但 verdict=PROBE_ERROR → `ok:true` + badge=PROBE_ERROR；probe 拋例外 →
  `ok:false`+error_code、保留原 badge、不 500、不寫半截事件、flash 為 sanitized。
- Security: 缺/錯 Origin → 403；缺 CSRF token → app guard 403。
- 並發: 一列重檢進行中時另一列可獨立重檢（per-row 鎖，非全域阻塞）。
- Integration: 重檢後重新展開抽屜（U2 重 fetch）→ 該列反映新 verdict。

**Verification:** 只有已發布鏈結可重檢、會寫一筆 `link.rechecked` 並就地更新；失敗誠實回報、
不 500、SSRF/Origin/CSRF 守衛到位、逐列鎖獨立。

## System-Wide Impact

- **Interaction graph:** 新 GET/POST 掛既有 health blueprint；POST 經成員反查後
  `recheck_link`→`emit_recheck`→events.db append。複用既有 scorecard 快取，不動 `build_channel_scorecard`。
- **Error propagation:** GET fail-open 回 `{ok:false}`（前端可辨）；POST 誠實結構化錯誤、區辨
  call-fail 與 PROBE_ERROR-verdict、不吞例外、不寫半截事件。
- **State lifecycle risks:** `emit_recheck` append-only 單進程；勿在持寫鎖開第二 SQLite 連線。
  單條同步、無背景 job 狀態需清理；顯式 timeout + 逐列鎖防 worker 耗盡。
- **API surface parity（修正）:** 抽屜（per-`live_url` 逐鏈）與 ledger/overlay（per-`target_url`
  逐目標、兄弟鏈活著保平台）**是兩種正確粒度，無法靠同一 canonicalize 對齊**。一條 stripped 鏈結
  可正確地出現在記分板仍計 live 的平台下——此非 bug，U3 以 UI 說明處理，勿宣稱消除。共用 iterator
  確保「最新-verdict-per-link」這層不變式不 drift。
- **Integration coverage:** U4→U2 串接（重檢寫事件後重 fetch 反映）、U2→U1 透傳須整合測試。
- **Security surface:** U4 是本庫**首個** per-URL client 觸發的出站探測 route——R8 成員反查是
  防盲 SSRF 的授權邊界（Origin guard 只防 CSRF/rebinding，非授權）。net_safety 只擋私網、不擋公網。
- **Unchanged invariants:** `build_channel_scorecard` / ChannelScoreRow / verdict 分類 /
  events schema / publish 路徑全不變。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| R5 讀 `target_rel` 但它從未落地 events.db → 永遠 None | 改用已落地 `confirmed_dofollow`/`confirmed_nofollow` 布林推導 dofollow 狀態 |
| verdict==ALIVE 不保證檢視過（no-target ALIVE 分支）→ 誤顯示「正常」 | R5 閘門用「確實檢視過」謂詞；專測 target_url=None 的 ALIVE 列回 n/a |
| 抽屜 per-link 與 ledger per-target 顯示衝突（two truths） | 不對齊；U3 UI 說明 + System-Wide Impact 載明兩種粒度；共用 iterator 防不變式 drift |
| U4 盲 SSRF（client 傳任意公網 URL 被探測） | R8 強制 events.db 成員反查、不存在不探測；抄 equity_ledger_recheck；專測「不在庫→404 無探測」 |
| 逐條讀取誤用 `derive_per_target_status`（NULL-article_id 丟 50%） | key on live_url、無 NULL 過濾；專測 NULL-article_id 列必現 |
| 同步探測 ~2×10s 兩段抓取拖住 worker + 無限速 | 顯式 timeout（~5s）；flask-limiter/debounce；逐列鎖；async 降級 deferred |
| example.com 硬編碼對異質語料兩頭錯 | 保留域集（RFC2606+`.example`+佔位）host-label 比對；對照實際 seed 後定成員 |
| scorecard 跨包引 overlay 待刪私有函式 → overlay 退役時靜默壞 | 先抽 iterator 到穩定公開位置共用，非引私有名；pin 測試使退役失敗響亮 |
| 抽屜在 5% 覆蓋率多為空 / U4 誘導逐條手動重檢 | U3 標頭明示「重檢歷史視圖」+ 已重檢計數；覆蓋率提升另起 plan（並行課題） |
| 新讀取函式 CC > 30 hard-fail CI | 保持簡單或拆分；必要時 `complexity_budget.toml` 加 ≥80 字 rationale |
| 測試 env 污染（session-scoped fixture） | `monkeypatch.setenv/delenv`；CSRF 姿態顯式強制；直接查 SQLite |

## Documentation / Operational Notes

- 純讀取 + 單條重檢，無 migration、無新 env、無 rollout 旗標。
- events.db 單進程 append-only；無新狀態存儲。
- 覆蓋率 ~5% 為已知限制：抽屜為「重檢歷史視圖」非「鏈結清冊」——U3 標頭明示，覆蓋提升屬並行課題。

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-05-backlink-liveness-tracking-loop-requirements.md](docs/brainstorms/2026-06-05-backlink-liveness-tracking-loop-requirements.md)
- Scorecard host: `webui_app/routes/health.py:279-312`, `templates/health.html:226-274`, `scorecard/engine.py:56,112`
- Read pattern: `recheck/overlay.py:172-294`（build_discount_map + apply_discounts）, `ledger/aggregate.py::_load_confirmed_dofollow_urls`
- Payload reality: `recheck/events_io.py:72-92`（emit_recheck，無 target_rel）, `recheck/probe.py:147-235`（recheck_link、no-target ALIVE、2×fetch）
- Recheck safety precedent: `routes/equity_ledger.py:104-120`, `helpers/security.py:130`, `_util/net_safety.py:20-27`
- Frontend idiom: `static/js/equity.js:226-293`, `equity_ledger.html:100`, `static/js/keep_alive.js`
- Learnings: 見 Context（7 篇 `docs/solutions/`）
