---
title: "feat: dispatch-backlinks 自動平台路由引擎"
type: feat
status: completed
date: 2026-06-03
origin: docs/brainstorms/2026-06-03-dispatch-backlinks-requirements.md
claims:
  paths:
    - src/backlink_publisher/cli/dispatch_backlinks.py
    - src/backlink_publisher/dispatch/routing.py
    - src/backlink_publisher/dispatch/signals.py
    - src/backlink_publisher/dispatch/__init__.py
    - tests/test_dispatch_backlinks.py
  shas: []
---

# feat: dispatch-backlinks 自動平台路由引擎

## Summary

新增 `dispatch-backlinks` CLI 命令，作為 `plan-backlinks | dispatch-backlinks | publish-backlinks` pipeline 的中間層。讀取 plan-backlinks 輸出的 JSONL，根據即時信號（registry metadata、channel binding、canary health、ledger coverage）自動為每行分配最佳發布平台，輸出帶 `platform` 欄位的 JSONL 給 publish-backlinks。

---

## Problem Frame

Operator 目前需手動指定 `--platform` 或逐行設 `platform` 欄位才能將文章發到不同平台。工具已產出足夠的信號（equity-ledger、channel-scorecard、canary-targets）但沒有人把它們串成發布決策。路由引擎填補這個 gap：讓"自動分配到正確的平台"成為 pipeline 中的一環，不必人工干預。

---

## Requirements

- R1. 新增 `dispatch-backlinks` CLI 命令，stdin JSONL → stdout JSONL
- R2. 路由決策考量：dofollow_status、referral_value、channel_status、canary status、language whitelist、visibility、ledger 覆蓋分布
- R3. 三種 strategy（balanced/quality/spread），預設 balanced
- R4. 輸出帶 `_dispatch` 元資料塊（strategy, candidates, reason, engine_version）
- R5. `--platform` 手動覆蓋保留
- R6. 信號即時讀取（不緩存）
- R7. 無 equity-ledger 數據時降級（round-robin + stderr WARN）
- R8. canary 數據過期保護（--canary-stale-days，降級 dofollow 信賴度）

**Origin actors:** A1 (Operator), A2 (Routing engine), A3 (Signal sources)
**Origin flows:** F1 (自動路由), F2 (信號感知路由)
**Origin acceptance examples:** AE1 (基本路由), AE2 (平台不可用), AE3 (全部排除), AE4 (--platform 覆蓋)

---

## Scope Boundaries

- **WebUI 路由配置/可視化**：v1 純 CLI
- **並發發布**：不改 publish-backlinks 執行模型
- **跨平台內容差異化**：同一內容發到所有平台
- **時間排程**：不引入 cron 排程
- **新平台 adapter**：吃 registry，不新增

---

## Context & Research

### Relevant Code and Patterns

- **CLI entrypoint**: `cli/plan_gap.py` — reads stdin JSONL with `read_jsonl`, writes stdout with `write_jsonl`, argparse for flags, `config_echo.emit_banner`, `import adapters` to populate registry, exit 1 usage error style
- **pyproject.toml scripts**: add `dispatch-backlinks = "backlink_publisher.cli.dispatch_backlinks:main"` (line ~64)
- **Registry API**: `registered_platforms()`, `dofollow_status(name)`, `referral_value(name)`, `ui_meta(name).category`, `policy(name).language_whitelist`, `visibility(name)`, `active_platforms()` — all from `backlink_publisher.publishing.registry`
- **Canary health store**: `canary/store.py` — `get_health(platform)` returns `{status, quarantined, consecutive_failures, last_ok_at}`, `is_quarantined()`, `is_degraded()`, `list_all()`. Lives at `<config_dir>/canary-health.json`
- **Channel status**: `webui_store.channel_status` — `channel_status_store` (JsonStore at `<config_dir>/channel-status.json`) with entries like `{status: "bound"|"expired"|"unbound", ...}` for channels in {velog, medium, blogger}. Anon platforms (telegraph, txtfyi, renTry, notesio) are always bound.
- **Ledger coverage**: `from backlink_publisher.ledger import build_ledger` / `from backlink_publisher.ledger.model import LedgerRow` — `build_ledger(stale_days=N)` returns `list[LedgerRow]`; `LedgerRow.platforms` lists platforms with any link, `live_dofollow_platforms` lists only confirmed-live dofollow
- **publish-backlinks stdin**: reads per-row `platform` field at `args.platform or row.get("platform", "")` — confirming `dispatch-backlinks` output format is compatible
- **Test pattern**: mock stdin with list of dicts, mock signal stores (`canary_health_store`, `channel_status_store`), assert stdout JSONL + exit code

### Signal data shapes

- **`canary-health.json`** (`<config_dir>/canary-health.json`): `{platform: {status, consecutive_failures, last_ok_at, last_drift_at, consecutive_oks, quarantined}}`, sibling `_publish_path` key for forward-path drift (advisory)
- **`channel-status.json`** (`<config_dir>/channel-status.json`): `{channel: {status: "bound"|"expired"|"unbound", updated_at, ...}}` — platforms in `CHANNELS` only (`velog`, `medium`, `blogger`). Others are anon/always-bound.
- **`LedgerRow`** (from `ledger/model.py`): `.platforms` (list of platform names with any link), `.live_dofollow_platforms` (list of platforms with confirmed live dofollow), `.target_url`, `.total_links`, `.total_live`

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| 獨立 CLI 命令（非改 publish-backlinks） | 關注點分離；可獨立測試、獨立使用、獨立演進 |
| `dispatch-backlinks` 作為包（package） | 遵循 `publish_backlinks/` 模式，路由邏輯抽到 `dispatch/` 子包 |
| `--strategy` 三種模式 | 讓 operator 在品質與覆蓋之間權衡，不用改 code |
| 不建 `LedgerRow` 索引 | 文章數少（批次幾十行），線性掃描即可 |
| 匿名平台（anon auth_type）視為永久 bound | 不需 credential，所以 channel_status 永遠有效 |
| Ledger 數據選用 stdin 傳入 vs 即時聚合 | --equity-ledger PATH 讀預先跑好的輸出，或由 build_ledger() 即時聚合（無檔案時自動） |
| engine_version=1 寫死在 `_dispatch` 塊 | 未來改路由邏輯時可升版追溯 |

---

## Implementation Units

### U1. dispatch-backlinks CLI skeleton

**Goal:** 新增 `dispatch-backlinks` CLI entrypoint，註冊到 `pyproject.toml`。

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `src/backlink_publisher/cli/dispatch_backlinks.py`
- Modify: `pyproject.toml` (add script entry)

**Approach:**
- 單檔 CLI（非 package，初始內容夠小不超 150 行），依 `plan_gap.py` 模式
- `main(argv)` → argparse + `read_jsonl(sys.stdin)` → 後續 units 注入路由邏輯
- `config_echo.emit_banner(cfg, "dispatch-backlinks")`
- 初始只做 pass-through：stdin → stdout（不做任何路由），確保 CLI skeleton 可運行
- 使用 `import backlink_publisher.publishing.adapters` 填充 registry

**Patterns to follow:**
- `cli/plan_gap.py`（argparse 風格、exit code 慣例）
- `pyproject.toml` 其他 script entries（排序列末加）

**Test scenarios:**
- Happy path: pipe JSONL → stdout JSONL matches input
- Empty stdin → exit 0, empty stdout, stderr message
- Malformed JSONL → exit 2 (via `read_jsonl(strict=True)`)

**Verification:**
- `dispatch-backlinks --help` 顯示用法
- `echo '' | dispatch-backlinks` exits 0 with informational stderr
- `pyproject.toml` 有新的 script entry

---

### U2. 路由引擎核心（signal scoping + ranking）

**Goal:** 實作 `dispatch/routing.py` 中的 `route(row, ledger, opts) -> (platform, dispatch_meta)` 核心函數。

**Requirements:** R2, R3, R7, R8

**Dependencies:** U1

**Files:**
- Create: `src/backlink_publisher/dispatch/__init__.py`（empty, package marker）
- Create: `src/backlink_publisher/dispatch/signals.py`
- Create: `src/backlink_publisher/dispatch/routing.py`

**Approach:**

**`signals.py`** — 信號收集層
```python
# 收集所有 active platform 的信號摘要：
# - registry: dofollow_status, referral_value, visibility, policy.language_whitelist
# - channel_status: bound/expired (anon → always bound)
# - canary: is_quarantined, is_degraded, last_ok_at (from canary-health.json)
# Output: dict[str, PlatformSignal]  # platform → (dofollow, bound, quarantined, lang_ok, ...)
```

**`routing.py`** — 核心路由函數
```python
def route(
    row: dict,
    signals: dict[str, PlatformSignal],
    ledger_map: dict[str, LedgerRow] | None,
    strategy: str,
    canary_stale_days: int | None,
) -> tuple[str | None, dict]:
```

內部邏輯：
1. **Filter phase**: 排除 unavailable platforms（unbound/expired、retired/hidden、language mismatch、quarantined）
2. **Score phase**: 剩餘平台按 strategy 打分
   - `balanced`（預設）：dofollow tier (True=4, uncertain=2, False=1) + referral bonus (high=+1) + spread bonus（`live_dofollow_platforms` 越少分越高）+ random tiebreaker
   - `quality`：只用 dofollow tier + referral bonus，不打散
   - `spread`：dofollow tier 降權至 1，spread 分權重 3x
3. **Select phase**: 選最高分 → None 表示全部排除
4. **Meta**: 回傳 `(platform, {strategy, candidates, reason, engine_version})`

降級路徑（R7）：若 `ledger_map` 為 None/空 → balanced/spread 同 tier 內改 round-robin，stderr WARN。

過期保護（R8）：若 platform 的 canary `last_ok_at` 早於 `now - canary_stale_days`，將其 dofollow 信賴度降一級（True → uncertain, uncertain → 僅供參考）。

**Patterns to follow:**
- `backlink_publisher.publishing.registry` (`active_platforms()`, `dofollow_status()`, etc.)
- `canary/store.py` (`is_quarantined()`, `is_degraded()`, `get_health()`)
- `webui_store.channel_status` (`channel_status_store.load()`)

**Test scenarios:**
- **Happy path**: 3 active platforms, all bound, all alive → balanced 分散到最少覆蓋的平台
- **Filter expired**: 1/3 platforms expired → 該 platform 被排除
- **Filter quarantined**: 1/3 platforms quarantined → 排除
- **Filter language mismatch**: 2 platforms with `language_whitelist=("en",)` vs row language="zh" → 排除
- **All excluded**: 所有平台都被排除 → returns (None, error_meta)
- **No ledger data** → round-robin within tier + stderr WARN (test with mock stderr)
- **Stale canary** → dofollow downgrade applied
- **quality strategy**: 不分數只在最高分平台
- **spread strategy**: spread bonus 權重最高

---

### U3. 整合 CLI + 路由引擎

**Goal:** 在 `dispatch_backlinks.py` 中整合信號收集和路由引擎，完成完整 pipeline。

**Requirements:** R1, R2, R3, R4, R5, R6, R7, R8

**Dependencies:** U2

**Files:**
- Modify: `src/backlink_publisher/cli/dispatch_backlinks.py`（實作完整邏輯）

**Approach:**
- `main(argv)` 流程：
  1. argparse（`--strategy`, `--platform`, `--equity-ledger`, `--canary-stale-days`）
  2. 載入 config + echo banner + populate registry
  3. 收集信號（`signals.collect_all()`）
  4. 如果有 `--equity-ledger` path → 從檔案讀；否則呼叫 `build_ledger()`（無感）
  5. 對每行路由
  6. 輸出結果 JSONL + stderr summary

- `--platform` flag：如果給了，跳過路由，所有行強制設為該 platform，不跑路由邏輯（僅驗證 platform 存在）
- 輸出每行補 `platform` + `_dispatch` 塊
- stderr summary：`dispatch-backlinks: assigned N rows across M platforms; skipped N (no_candidates); engine_version=1`

**Exit codes:**
- 0: 成功（包括部分行無合適平台）
- 1: UsageError（arg parse 問題）
- 2: stdin 格式錯誤
- 6: 所有行都沒有合適平台（全部 `_dispatch_error`）

**Integration test scenarios:**
- Full pipeline: stdin JSONL → dispatch-backlinks → verify JSONL has `platform` and `_dispatch`
- `--platform` override: all rows forced to the given platform
- `--platform` invalid: exit 1
- All filtered out: exit 6
- No ledger: degraded round-robin, stderr WARN message
- Mix of bound/unbound: only bound platforms used

**Verification:**
- `echo '[{"url":"..."}]' | dispatch-backlinks --strategy balanced` 輸出含 `platform` 的 JSONL
- `dispatch-backlinks --platform notexist < in.jsonl` → exit 1
- All rows excluded → exit 6 with diagnostic stderr

---

### U4. 測試

**Goal:** 完整的測試套件覆蓋路由邏輯和 CLI 整合。

**Requirements:** All

**Dependencies:** U3

**Files:**
- Create: `tests/test_dispatch_backlinks.py`

**Approach:**
- 使用 `pytest` + `mocker` 模擬 signal stores
- 使用 conftest 中的 registry isolation fixtures（`fake_platform_registered`）控制測試的 platform 集合
- 測試分類：
  - **Unit**（純 routing/signals 邏輯，不依賴 CLI）
  - **Integration**（CLI entrypoint → stdout/stderr/exit_code）
  - **Signal corruption**（corrupt JSON 在 signal 檔案中 → graceful degradation）

**Test scenarios:**
- route(): 每種 strategy + 各種信號組合
- CLI: 完整 pipeline（含 --platform override）
- Exit code 6: 全部排除
- stderr WARN: 無 ledger 數據

**Patterns to follow:**
- `tests/test_plan_gap.py`（mock stdin、assert stdout JSONL）
- `tests/test_canary_store.py`（canary store test patterns）

**Verification:**
- `pytest tests/test_dispatch_backlinks.py -v` all green
- `pytest tests/` no regressions

---

## System-Wide Impact

- **Interaction graph**: No callback/middleware changes. New CLI reads existing stores read-only.
- **Error propagation**: routing failures (all platforms excluded) produce exit 6 + stderr; individual row routing failures produce `_dispatch_error` in that row's `_dispatch` block
- **State lifecycle risks**: Read-only — no writes to any store
- **API surface parity**: `equity-ledger` can now be consumed as a library call (`build_ledger()`) OR as a piped JSONL file
- **Unchanged invariants**: `publish-backlinks` unchanged; `plan-backlinks` unchanged; registry registration unchanged; signal stores unchanged

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `build_ledger()` 呼叫開銷大（掃 events.db） | 預設用 `build_ledger(stale_days=30)` 快取最近數據；operator 可傳預先跑好的 JSONL 跳過 |
| `channel_status_store` 只 cover {velog,medium,blogger} | 其他 platform 全都是 anon（永遠 bound），在 `signals.py` 中處理 |
| 20+ platforms 逐一掃 canary-health.json + channel-status 可能慢 | 數據都在同一兩檔案中（canary-health.json, channel-status.json），讀一次即可 |
| 無 equity-ledger 時 round-robin 分配品質低 | stderr 明確 WARN，operator 可選擇補上 `--equity-ledger` |

---

## Documentation / Operational Notes

- 新增 CLI 用法到 `README.md`（or 更新 `--help` text）
- Pipeline 範例：`cat planned.jsonl | dispatch-backlinks --strategy balanced | publish-backlinks --mode draft`
- 無需 rollout / 監控（read-only CLI 命令）

---

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-03-dispatch-backlinks-requirements.md](file:///Users/dex/YDEX/INPORTANT%20WORK/%E5%A4%96%E9%93%BE/backlink-publisher/backlink-publisher/docs/brainstorms/2026-06-03-dispatch-backlinks-requirements.md)
- Related code: `src/backlink_publisher/cli/plan_gap.py` (CLI pattern), `src/backlink_publisher/publishing/registry.py` (platform metadata), `src/backlink_publisher/canary/store.py` (canary health), `webui_store/channel_status.py` (channel binding), `src/backlink_publisher/ledger/` (coverage data)
