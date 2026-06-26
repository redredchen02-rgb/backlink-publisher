---
title: "refactor: Codebase Decoupling — Complexity, Boundary & CLI Structure"
type: refactor
status: completed
date: 2026-06-24
origin: docs/brainstorms/2026-06-24-001-codebase-decoupling-requirements.md
---

# refactor: Codebase Decoupling — Complexity, Boundary & CLI Structure

## Overview

修改一個 bug 容易連帶破壞其他地方，根源是結構性耦合：7 個函數的 CC（Cyclomatic Complexity）高達 32–50 且被 grandfathered 進 `complexity_budget.toml`；`cli/` 目錄 65 個文件混雜；模組邊界靠慣例維持而非靜態強制。本計劃分三 Phase 有序解決：先拆函數（降低改動影響面），再固邊界（讓違規可見），最後重組目錄（提升可讀性）。

## Problem Frame

（見 origin: docs/brainstorms/2026-06-24-001-codebase-decoupling-requirements.md）

核心：7 個 grandfathered 函數的高 CC 使它們成為「萬能依賴點」——改一處必須理解整個函數，間接破壞所有呼叫方。

**Codebase 已驗證的 decomposition 先例：**
- Plan 2026-05-29-005 Unit 3：`_run_resume` CC 62 → thin shell CC 9 + helpers，entry 從 budget.toml 移除
- Wave 3 Unit 1 (2026-06-11)：`spray/core.py::main` CC 65 → 5，`_run_spray` 提出到 `_engine.py`
- `_project_checkpoint` CC 39 → 4 named handlers（2026-06-03）

本計劃遵循同一模式。

## Requirements Trace

- R1–R5: Phase 1 拆分高 CC 函數，每個函數獨立 PR，complexity_budget.toml 同步下調
- R6–R9: Phase 2 加 `__all__`，import-linter CI 靜態攔截違規 import
- R10–R13: Phase 3 CLI 子目錄重組，命令接口向後相容
- SC: Top CC 函數全降至 < CC 30（可從 budget.toml 移除），10,000+ tests 零回歸

## Scope Boundaries

- 不改任何 CLI 命令名稱、參數、輸出格式
- 不改 pipeline 架構（seeds → plan → validate → publish）
- 不加新功能
- WebUI（webui_app/、webui_store/）不在範圍
- Phase 3 重組：測試 import path 一併更新，但測試邏輯不動
- `webui_app/routes/sites.py::sites_save_three_url`（CC ceiling 38）不在本計劃範圍（WebUI 是獨立工作流）

## Context & Research

### Current Grandfathered CC Ceilings (Priority Order)

| 函數 | 文件 | CC Ceiling | 狀態 | 對應 Unit |
|---|---|---|---|---|
| `_generate_payload` | `cli/plan_backlinks/_payload.py` | 50 | grandfathered | U1 |
| `_run_spray` | `cli/spray_backlinks/_engine.py` | 48 | grandfathered | U2 |
| `run_cycle` | `keepalive/chain.py` | 45 | grandfathered | U3 |
| `_build_links` | `cli/plan_backlinks/_links.py` | 36 | grandfathered | U4 |
| `save_config` | `config/writer.py` | 36 | grandfathered | U4 |
| `_publish_one_row` | `cli/publish_backlinks/_engine.py` | 35 | grandfathered | U5 |
| `_enhance_payload` | `cli/_validate_payload.py` | 32 | grandfathered | U5 |

### Decomposition Pattern (Established in This Codebase)

```
BEFORE: _generate_payload() [CC 50]  ← monolithic assembler
        │ language resolution (zh-short, target_language variants)
        │ anchor resolution (type, keywords, source fallbacks)
        │ link density (paragraph placement logic)
        └─ validation gating (fetch_verify, domain checks)

AFTER:  _generate_payload() [CC ≤ 10]  ← thin coordinator
        ├── _resolve_language_config()    [CC ≤ 10]
        ├── _resolve_anchor_config()      [CC ≤ 10]
        ├── _compute_link_density()       [CC ≤ 8]
        └── _apply_validation_gate()      [CC ≤ 10]
```

Goal: orchestrator drops below backstop (CC 30) → entry **removed** from budget.toml.

### Relevant Patterns to Follow

- `src/backlink_publisher/cli/_resume.py` — prior decomposition: thin `_run_resume` shell + `_publish_one_resume_item` helpers
- `src/backlink_publisher/cli/spray_backlinks/core.py` — prior: `main()` delegating to `_engine.py`
- `src/backlink_publisher/events/_project_reducers.py` — prior: `_project_checkpoint` split into 4 handlers
- `complexity_budget.toml` — schema and rationale conventions to follow

### Existing Test Coverage for Target Functions

| 函數 | 主要測試文件 |
|---|---|
| `_generate_payload` | `tests/test_plan_backlinks.py`, `tests/test_plan_backlinks_work_themed.py`, `tests/test_plan_backlinks_anchor_keywords.py` |
| `_run_spray` | `tests/test_cli_spray_backlinks.py`, `tests/test_spray_backlinks_*.py` (5 files) |
| `run_cycle` | `tests/test_keepalive_run.py`, `tests/test_keepalive_run_state.py` |
| `_build_links` | `tests/test_plan_backlinks.py` (link section) |
| `save_config` | `tests/test_config_three_url.py`, `tests/test_config_*.py` |
| `_publish_one_row` | `tests/test_publish_backlinks.py`, `tests/test_publish_backlinks_characterization.py` |
| `_enhance_payload` | `tests/test_validate_backlinks.py` |

## Key Technical Decisions

- **CC 30 backstop 是目標基準**：每個 decomposition 的目標是讓 orchestrator 降至 CC < 30，從而從 budget.toml 移除 entry。若確實無法降到 30（純粹 sequential gating 無法再拆），必須顯著降低 ceiling（≥ 40% 降幅），並更新 rationale。
- **Phase 順序不可逆轉**：先拆函數 → 再加 `__all__` → 再加 import-linter → 最後重組目錄。Phase 2 依賴 Phase 1 的函數邊界清晰；Phase 3 依賴 Phase 2 的模組合約確立。
- **每個函數拆分必須 run full test suite 才能合並**：破壞測試意味著拆分方式不對（隱式耦合未識別），不能 `--no-verify` 通過。
- **`__all__` 聲明公開 API，不設 import barrier**：Phase 2 的 `__all__` 是文檔性約束；import-linter 才是機器強制的 barrier。兩者都需要。
- **import-linter 初始配置採用 warn 模式**：首次加入 CI 時設 `warn_only = true`，讓現有違規可見但不阻塞。修復所有違規後切換 `warn_only = false`（在同一 PR 內）。
- **Phase 3 CLI 重組使用 shim re-export 保障向後相容**：移動文件後在原 `cli/<name>.py` 留 one-liner re-export，確保任何直接 import 不 break；pyproject.toml 更新到新 path。
- **每個 decomposition PR 同步降 complexity_budget.toml ceiling**：不允許拆了函數但 ceiling 不動（CI 防止回長）。目標：拆到 CC < 30 的 entry 必須從 budget.toml 刪除。

## Open Questions

### Resolved During Planning

- **R9: import-linter 是否已在 CI？** → 不在。需要新增。最輕量方案：`import-linter` PyPI 包 + `.importlinter` 配置文件 + `pyproject.toml [tool.importlinter]` 部分。加入 `[dev]` extras 即可，無需 pre-commit hook。
- **R10: CLI 重組是否需更新 pyproject.toml console_scripts？** → 是。30+ 條目需更新。使用 shim re-export（原路徑留 `from .new_path import main`）確保向後相容。
- **R11: domain 邏輯 vs orchestration 邏輯判斷標準？** → 判斷規則：若一個函數只需要 stdlib + 內部 domain 模組（無需 `argparse`/`click`/`sys.argv`），則屬於 domain 邏輯，應移到對應 domain subpackage。若它需要解析 CLI args 或直接讀寫 stderr/stdout 作為 UI，則屬於 CLI orchestration，留在 `cli/`。

### Deferred to Implementation

- 每個函數拆分的確切 sub-function 命名：實作時根據實際邏輯分組確定，計劃只定義拆分策略
- import-linter 首次執行後的實際違規數量：需執行後才知道
- Phase 3 中每個 CLI 文件的具體目標子目錄：需查看每個文件的職責確定

## High-Level Technical Design

> *下圖說明分解策略和模組依賴方向，為方向性指引而非實作規格。*

**Decomposition Strategy (applies to all Phase 1 units):**

```
STAGE 1 — Identify Concern Groups
  Read the function and mark regions:
  "A: input validation/normalisation"
  "B: state/config resolution"  
  "C: core transformation/assembly"
  "D: output/emission"

STAGE 2 — Extract Named Helpers
  Each concern group → private function _<verb>_<noun>()
  Orchestrator calls helpers in sequence
  Injectable test hooks remain as parameters to orchestrator

STAGE 3 — Verify CC
  python -m radon cc -s <file> → confirm orchestrator CC < 30
  If not: find the remaining branchy region, extract another helper

STAGE 4 — Update budget.toml
  CC < 30: delete entry entirely
  CC 30–35: update ceiling to new value + update rationale
```

**Module Dependency Direction (enforced by import-linter in Phase 2):**

```
┌──────────────────────────────────────────────────────┐
│  cli/                                                 │
│  (argparse, sys.argv, stdout/stderr)                  │
└──────────────────────┬───────────────────────────────┘
                       │ may import from ↓
┌──────────────────────▼───────────────────────────────┐
│  Domain Packages                                      │
│  (publishing/, keepalive/, events/, anchor/, etc.)   │
└──────────────────────┬───────────────────────────────┘
                       │ may import from ↓
┌──────────────────────▼───────────────────────────────┐
│  _util/                                               │
│  (errors, io, safe_write, secrets)                    │
└──────────────────────────────────────────────────────┘

Forbidden: domain packages importing from cli/
Forbidden: _util importing from domain or cli
```

**Phase 3 CLI Proposed Subdirectory Structure:**

```
cli/
├── plan/          # plan-backlinks, plan-gap, plan-check, generate-backlink-text
├── publish/       # publish-backlinks, dispatch-backlinks, publish-metrics, report-anchors
├── spray/         # spray-backlinks, canary-seed, canary-targets
├── admin/         # bind-channel, *-login, audit-state, state-backup, phase0-seal
├── reporting/     # equity-ledger, footprint, channel-scorecard, recheck-overlay, decay-alert
├── ops/           # gate-probe, preflight-targets, cull-channels, platform-health, health-check
└── [top-level keep] # bp.py (entry point aggregator)
```

## Implementation Units

```mermaid
TB
  U1[U1: _generate_payload\nCC 50 → <30] --> U2
  U2[U2: _run_spray\nCC 48 → <30] --> U3
  U3[U3: run_cycle\nCC 45 → <30] --> U4
  U4[U4: _build_links + save_config\nCC 36, 36 → <30] --> U5
  U5[U5: _publish_one_row + _enhance_payload\nCC 35, 32 → <30] --> U6
  U6[U6: __all__ across 50+ packages] --> U7
  U7[U7: import-linter CI setup\n+ fix violations] --> U8
  U8[U8: CLI subdirectory\nreorganization]
```

---

- [x] **U1: Decompose `_generate_payload()` (CC ceiling: 50)**

**Goal:** 將 220 行的 payload assembly 函數拆分為職責單一的 helpers，orchestrator 降至 CC < 30，從 complexity_budget.toml 移除 entry。

**Requirements:** R1, R2, R3, R4

**Dependencies:** 兩個未 push 分支（refactor/webui-api-v1、perf/parallel-safe-lanes）合入 main 之後開始。

**Files:**
- Modify: `src/backlink_publisher/cli/plan_backlinks/_payload.py`
- Update: `complexity_budget.toml` (remove `_payload.py::_generate_payload` entry)
- Test: `tests/test_plan_backlinks.py`, `tests/test_plan_backlinks_work_themed.py`, `tests/test_plan_backlinks_anchor_keywords.py`, `tests/test_plan_cover_image_fields.py`

**Approach:**
- 識別 4 個關注點群組：(a) 語言/variant 解析（zh-short、target_language 分支）、(b) anchor 配置解析（source、type、keywords fallback）、(c) link density 計算（段落位置邏輯）、(d) validation gating（fetch_verify、domain checks）
- 每個群組提取為 `_resolve_language_config()`, `_resolve_anchor_config()`, `_compute_link_density()`, `_apply_validation_gate()` 四個 private functions
- `_generate_payload()` 成為薄 coordinator，依序呼叫這些 helpers
- injectable test hooks（`fetch_verify_enabled` 等）保留在 orchestrator 層

**Patterns to follow:**
- `src/backlink_publisher/cli/_resume.py` — thin `_run_resume` + `_publish_one_resume_item` 先例
- `complexity_budget.toml` entry 格式和 rationale 寫法慣例

**Test scenarios:**
- Happy path: en seed → payload 含 correct anchor type / link count / language fields
- Happy path: zh-CN seed with short-form → `zh_short` fields populated, character count correct
- Happy path: multi-platform seed → platform-specific anchor type variations preserved
- Edge case: `target_language` missing → fallback to `language` field
- Edge case: empty `topic` → no topic-driven anchor modification
- Error path: `fetch_verify` fails on domain → `ExternalServiceError` raised with clear message
- Regression: `test_plan_backlinks.py` full suite passes without modification

**Verification:**
- `python -m radon cc -s src/backlink_publisher/cli/plan_backlinks/_payload.py` shows orchestrator CC ≤ 10, all helpers CC ≤ 15
- `_generate_payload` entry removed from `complexity_budget.toml`
- `pytest tests/test_plan_backlinks.py tests/test_plan_backlinks_work_themed.py` passes

---

- [x] **U2: Decompose `_run_spray()` (CC ceiling: 48)**

**Goal:** 將多 seed 的 spray coordinator 拆薄，orchestrator 降至 CC < 30。

**Requirements:** R1, R2, R3, R4

**Dependencies:** U1（建立信心後繼續；也可並行，但建議序列以熟悉 decomposition 模式）

**Files:**
- Modify: `src/backlink_publisher/cli/spray_backlinks/_engine.py`
- Create: `src/backlink_publisher/cli/spray_backlinks/_engine_helpers.py` ← helpers 放新 sibling 文件，避免 `_engine.py` 打到 370-SLOC ceiling（當前 333 SLOC）
- Update: `complexity_budget.toml` (remove or lower `_engine.py::_run_spray` entry)
- Test: `tests/test_cli_spray_backlinks.py`, `tests/test_spray_backlinks_audit.py`, `tests/test_spray_backlinks_dispatch.py`, `tests/test_spray_backlinks_draft.py`, `tests/test_spray_backlinks_gate.py`

**Approach:**
- `_run_spray()` 目前 CC 48，已比 `core.py::main`（CC 65）拆過一次，但 seed-loop 本體仍複雜
- 識別 3 個可提取區塊：(a) input validation（platform selection、seed parsing）→ `_validate_spray_inputs(args)`；(b) per-seed loop body（expand → gate → draft → audit → dispatch）→ `_process_seed_batch(seeds, config, ...)`；(c) result emission（JSONL write, error envelope）→ `_emit_spray_output(results)`
- injectable hooks（`_checkpoint_path`, `_generate_run_id` 等）已在 `_gates.py`，保持不動
- orchestrator 成為：validate → load checkpoint → process seeds → emit
- **⚠️ 必須使用 `_engine_helpers.py`**：helpers 加入 `_engine.py` 會使其超過 monolith_budget.toml ceiling（370 SLOC）；新 sibling 文件不在 budget 中（< 500 SLOC threshold）

**Patterns to follow:**
- `src/backlink_publisher/cli/spray_backlinks/core.py` — 先前從 main() 提取 `_run_spray` 的模式
- `src/backlink_publisher/cli/spray_backlinks/_gates.py`, `_dispatch.py` — 現有 helper 模組

**Test scenarios:**
- Happy path: 2 seeds → 2 JSONL rows emitted to stdout
- Resume: checkpoint exists for seed 1 → seed 1 skipped, seed 2 processed
- Error path: invalid platform name → clear argparse error, exit non-zero
- Edge case: empty seed list (empty stdin) → empty output, exit 0
- Edge case: all seeds gated out → empty output with stderr summary
- Regression: `test_cli_spray_backlinks.py` full suite unchanged

**Verification:**
- `python -m radon cc -s src/backlink_publisher/cli/spray_backlinks/_engine.py` → `_run_spray` CC ≤ 12
- Entry removed or ceiling ≤ 12 in `complexity_budget.toml`
- `pytest tests/test_cli_spray_backlinks.py tests/test_spray_backlinks_*.py` passes

---

- [x] **U3: Decompose `run_cycle()` (CC ceiling: 45)**

**Goal:** 將 keepalive 5-stage coordinator 拆薄至 CC < 30。

**Requirements:** R1, R2, R3, R4

**Dependencies:** U2（序列推進）

**Files:**
- Modify: `src/backlink_publisher/keepalive/chain.py`
- Update: `complexity_budget.toml` (remove or lower `chain.py::run_cycle` entry)
- Test: `tests/test_keepalive_run.py`, `tests/test_keepalive_run_state.py`

**Approach:**
- 現有 budget rationale 說「All sub-stage logic is already extracted to private helpers (_effective_sticky, _update_opt_stats, KeepaliveRunState); 剩餘 CC 是 sequential gating」
- 目標：提取顯式 stage functions：`_run_recheck_stage(state, ...)`, `_run_planning_stage(state, ...)`, `_run_publish_stage(state, ...)`，每個對應一個具名的 keepalive 生命週期步驟
- dry-run 和 lock-contention 的 early-exit gates 可提取為 `_check_cycle_preconditions(state)` → returns `CyclePreconditionResult`
- orchestrator 變為：precondition check → recheck stage → planning stage → publish stage → finalize
- **⚠️ 4 個裸 `except Exception` loop 的去向必須決定**：函數體內有 4 個獨立的 try/except 對（分別在 recheck probe、status derivation、planning、publish loop 中），各自貢獻約 2 個 CC。這些 loop 必須移入對應的 stage function（例如 probe try/except 移入 `_run_recheck_stage`），否則 coordinator 只能降到 CC 31–33，無法達到 < 30 目標。若移入 stage 後每個 stage CC > 20，則 budget entry 改為 stage 函數而非 coordinator（ceiling 設為實測值 + 0 headroom）。**若最終無法降到 CC 30，可接受 CC 32–35，但必須在 PR description 說明原因，並更新 budget ceiling 到新值。**

**Patterns to follow:**
- `src/backlink_publisher/keepalive/chain.py` 現有 `KeepaliveRunState` dataclass 模式
- injectable function parameters（`select_candidates_fn`, `probe_fn` 等）保持在 orchestrator signature

**Test scenarios:**
- Happy path: dry-run → no publish calls, stats emitted
- Happy path: 2 gap targets → 2 publish events emitted
- Lock contention: cycle already running → early exit with lock message
- Empty gaps: no exhausted targets → no publish stage entered
- Probe failure: recheck probe raises → cycle survives with error logged
- Regression: `tests/test_keepalive_run.py` full suite passes

**Verification:**
- `python -m radon cc -s src/backlink_publisher/keepalive/chain.py` → `run_cycle` CC ≤ 12
- `complexity_budget.toml` entry removed or ceiling ≤ 12
- `pytest tests/test_keepalive_run.py tests/test_keepalive_run_state.py` passes

---

- [x] **U4: Decompose `_build_links()` and `save_config()` (CC ceilings: 36, 36)**

**Goal:** 分別拆分 link 建構函數和 config 寫入函數，雙雙降至 CC < 30。

**Requirements:** R1, R2, R3, R4, R5

**Dependencies:** U3

**Files:**
- Modify: `src/backlink_publisher/cli/plan_backlinks/_links.py`
- Modify: `src/backlink_publisher/config/writer.py`
- Update: `complexity_budget.toml` (remove both entries)
- Test: `tests/test_plan_backlinks.py`, `tests/test_config_three_url.py`, `tests/test_config_*.py`

**Approach:**
- **`_build_links()`**：branches over anchor source、language、dofollow tiering、link-density placement。提取：`_select_anchor_variant()`, `_apply_dofollow_tier()`, `_place_link_in_paragraph()`。orchestrator 成為 3-step pipeline。
- **`save_config()`**：branches over blogger/medium/ghpages/mastodon/targets sections。提取：`_write_blogger_section()`, `_write_medium_section()`, `_write_targets_section()`, `_write_image_gen_section()`（參考 budget rationale 說這些已部分提取過）。識別剩餘 inline branches 並提取。

**Patterns to follow:**
- `src/backlink_publisher/config/writer.py` 現有 section-emitter helpers 慣例

**Test scenarios:**
- `_build_links`: en + dofollow → link with correct rel="dofollow" attribute
- `_build_links`: zh-CN + nofollow tier → link without dofollow, correct zh paragraph position
- `_build_links`: blogger platform → blogger-specific anchor variant selected
- `save_config`: full config → round-trip (write then read = same values)
- `save_config`: unknown sections preserved (non-destructive write)
- `save_config`: targets with site_urls correctly emitted under [targets.*]
- Regression: `test_config_three_url.py` full suite passes

**Verification:**
- `python -m radon cc -s src/backlink_publisher/cli/plan_backlinks/_links.py` → `_build_links` CC ≤ 12
- `python -m radon cc -s src/backlink_publisher/config/writer.py` → `save_config` CC ≤ 12
- Both entries removed from `complexity_budget.toml`
- `pytest tests/test_plan_backlinks.py tests/test_config_three_url.py` passes

---

- [ ] **U5: Decompose `_publish_one_row()` and `_enhance_payload()` (CC ceilings: 35, 32)**

**Goal:** 拆分 publish pipeline 的兩個 gatekeeper 函數，降至 CC < 30；同時修復預先存在的 layer violation（`validate/engine.py` importing from `cli/`）。

**Requirements:** R1, R2, R3, R4, R5, R7 (pre-existing layer violation)

**Dependencies:** U4

**Files:**
- Modify: `src/backlink_publisher/cli/publish_backlinks/_engine.py`
- Modify: `src/backlink_publisher/cli/_validate_payload.py`
- Create: `src/backlink_publisher/validate/_payload.py` ← 移入 `_enhance_payload` + `_extract_hrefs_from_html`（解決 `validate/engine.py → cli/` layer violation）
- Modify: `src/backlink_publisher/validate/engine.py` ← 改 import 到新位置
- Update: `complexity_budget.toml` (remove both entries; `_engine.py::_publish_one_row` and `_validate_payload.py::_enhance_payload`)
- Test: `tests/test_publish_backlinks.py`, `tests/test_publish_backlinks_characterization.py`, `tests/test_publish_backlinks_banner_integration.py`, `tests/test_validate_backlinks.py`

**Approach:**
- **`_publish_one_row()`** (CC 35)：budget rationale 說 "sequential pre-condition gates"。提取：`_check_publish_preconditions(row)` → returns early-exit verdict (canary fail / reachability fail / bad platform / dedup hit / dry-run)；`_dispatch_to_adapter(row, config)` → handles actual adapter call + try/except。orchestrator: preconditions → dispatch → record event。
- **`_enhance_payload()` + `_extract_hrefs_from_html()`**：目前 `validate/engine.py` 直接從 `cli/_validate_payload.py` import 這兩個函數（layer violation：validate domain → cli）。正確做法是將這兩個函數移到 `validate/_payload.py`（純 validate domain），`cli/_validate_payload.py` 改為 thin wrapper 呼叫 `validate._payload`。`_enhance_payload` decompose 拆出 `_resolve_banner_path()` helper。這樣同時降低 CC 和修復 layer violation，避免 U7 再次動同一文件。
- `cli/_validate_payload.py` 保留 shim re-export（`from ..validate._payload import _enhance_payload`）確保其他 CLI 呼叫方不 break。

**Patterns to follow:**
- `src/backlink_publisher/cli/_resume.py::_publish_one_resume_item` — prior publish row decomposition

**Test scenarios:**
- `_publish_one_row`: canary gate fail → row skipped, event emitted with skip reason
- `_publish_one_row`: dedup gate hit → row skipped, dedup event emitted
- `_publish_one_row`: dry-run flag → no adapter called, draft event emitted
- `_publish_one_row`: adapter raises `AuthExpiredError` → correct error event, no crash
- `_enhance_payload`: valid banner path → payload updated with resolved path
- `_enhance_payload`: banner path outside allowed dir → `ValueError` raised (path traversal guard)
- `_enhance_payload`: missing optional fields → defaults applied, no KeyError
- Regression: `test_publish_backlinks_characterization.py` passes (behavioral spec)

**Verification:**
- `python -m radon cc -s src/backlink_publisher/cli/publish_backlinks/_engine.py` → `_publish_one_row` CC ≤ 12
- `python -m radon cc -s src/backlink_publisher/cli/_validate_payload.py` → `_enhance_payload` CC ≤ 28
- Both entries removed from `complexity_budget.toml`
- `pytest tests/test_publish_backlinks*.py tests/test_validate_backlinks.py` passes

---

- [ ] **U6: Add `__all__` Declarations Across All Subpackages**

**Goal:** 為 50+ 個 subpackage 的 `__init__.py` 加入 `__all__`，使公開 API 顯式化。

**Requirements:** R6

**Dependencies:** U5（Phase 1 完成後再做邊界聲明，確保 API 面清晰）

**Files:**
- Modify: All `__init__.py` files under `src/backlink_publisher/` that export symbols (excluding `__pycache__`)
- Test: 無需新增測試（靜態聲明）；執行 `pytest tests/` 確認無 import 回歸

**Approach:**
- 用 `python -c "import pkgutil; ..."` 或 AST 掃描列出每個包目前從 `__init__.py` 暴露的名稱
- 對每個 `__init__.py`：若有 `from .something import X` 或 `from . import X`，加入 `__all__ = [...]`
- 排除 `_` 開頭的符號（它們是 internal，不進 `__all__`）
- 若 `__init__.py` 是空文件或只有 docstring，加 `__all__ = []`
- 批量操作可用腳本生成 draft，逐一 review

**Patterns to follow:**
- 無先例（這是 codebase 首次系統性加 `__all__`），参考 Python 慣例

**Test scenarios:**
- Test expectation: 無需新測試，但執行完整套件確認無 `ImportError`
- 額外 smoke check：`python -c "from backlink_publisher.publishing import *"` 等各主要包 wildcard import 無警告

**Verification:**
- `grep -r "^__all__" src/backlink_publisher/` 覆蓋 50+ 文件
- `pytest tests/` 零回歸

---

- [ ] **U7: Add import-linter CI Enforcement + Fix Violations**

**Goal:** 在 CI 中加入 import-linter，靜態攔截跨層 import 違規；首次啟用 warn-only，修復所有違規後切換強制模式。

**Requirements:** R7, R8, R9

**Dependencies:** U6（`__all__` 完成後邊界清晰，violation 更少）

**Files:**
- Create: `.importlinter` (import-linter 配置文件)
- Modify: `pyproject.toml` (add `import-linter` to `[project.optional-dependencies.dev]`, add `[tool.importlinter]` section)
- Modify: CI 配置（如有 `.github/workflows/` 或 `Makefile`）加入 `lint-imports` 步驟
- Fix: 任何被 import-linter 發現的違規 import（execution-time 確定具體文件）
- Test: 無需新測試，CI 步驟本身是驗證

**Approach:**
- 安裝：`import-linter` 加入 `[dev]` extras in `pyproject.toml`
- **⚠️ 使用 `forbidden` contracts，不用 `layers`**：`layers` contract 將 domain 包視為同一 tier 並禁止互相 import，但 domain 包互相 import 是合法設計（例如 `gap` → `publishing.registry`、`content` → `anchor`）。應改用 `forbidden` 合約，只禁止特定方向的違規：
  ```toml
  [importlinter]
  root_packages = backlink_publisher

  [importlinter:contract:no-domain-to-cli]
  name = Domain packages must not import from cli/
  type = forbidden
  source_modules = backlink_publisher.publishing
                   backlink_publisher.keepalive
                   backlink_publisher.events
                   backlink_publisher.anchor
                   backlink_publisher.validate
                   backlink_publisher._util
  forbidden_modules = backlink_publisher.cli
  warn_only = true  # 初始，修復後移除

  [importlinter:contract:no-util-to-domain]
  name = _util must not import from domain or cli
  type = forbidden
  source_modules = backlink_publisher._util
  forbidden_modules = backlink_publisher.cli
                      backlink_publisher.publishing
                      backlink_publisher.keepalive
  warn_only = true
  ```
- **已知預先存在的違規**（U5 應已修復的）：`_util/errors.py → cli/_bind.channels.CHANNELS` — 這個違規需要將 `CHANNELS` 移到 `_util/` 或 `publishing/` 非 cli 位置；在 U7 修復。
- 首次執行 `lint-imports` → 記錄所有違規（除了 U5 已修復的）
- 修復每個違規（移動函數 / 加 re-export / 反轉 import 方向）
- 全部修復後刪除所有 `warn_only = true`

**Patterns to follow:**
- `pyproject.toml` 現有 `[project.optional-dependencies.dev]` 格式（加 radon 的方式）

**Test scenarios:**
- Test expectation: CI `lint-imports` 步驟 passes（exit 0）
- 創建一個故意違規的 import（測試 CI 能攔截）→ 測試通過後刪除

**Verification:**
- `lint-imports` 命令 exit 0，zero violations
- `pytest tests/` 零回歸

---

- [ ] **U8: CLI Subdirectory Reorganization**

**Goal:** 將 `cli/` 的 65 個文件重組到 6 個子目錄，每個子目錄 ≤ 15 文件；命令接口向後相容。

**Requirements:** R10, R11, R12, R13

**Dependencies:** U7（import-linter 確立後重組不會 silently break 邊界）

**Files:**
- Create: `src/backlink_publisher/cli/plan/`, `cli/publish/`, `cli/spray/`, `cli/admin/`, `cli/reporting/`, `cli/ops/`（各加 `__init__.py`）
- Move: 各 `cli/*.py` 到對應子目錄
- Create: shim re-exports at original `cli/<name>.py` paths（one-liner `from .new_subdir.name import main`）確保向後相容
- Modify: `pyproject.toml` `[project.scripts]`：更新所有 import paths 到新位置
- Modify: 任何直接 import `backlink_publisher.cli.<name>` 的 non-test 代碼
- Update: `tests/` 中相應 import paths（邏輯不動）
- Update: `src/backlink_publisher/cli/bp.py` GROUPS 中的引用路徑

**Approach:**
- 按以下規則分組（`_bind/` 因被 `publishing/` heavy use，放 `publishing/` 而非 `admin/`）：
  - `plan/`：plan-backlinks、plan-gap、plan-check、generate-backlink-text、canonical_expand、_plan_check_*
  - `publish/`：publish-backlinks、dispatch-backlinks、publish-metrics、report-anchors、verify-dofollow
  - `spray/`：spray-backlinks、canary-seed、canary-targets
  - `admin/`：*-login（velog/medium/frw）、audit-state、state-backup、phase0-seal、_seal_init、resume、runs、_resume
  - `reporting/`：equity-ledger、footprint、channel-scorecard、recheck-overlay、decay-alert、debt-report、weights
  - `ops/`：gate-probe、preflight-targets、cull-channels、platform-health、health-check、recheck-backlinks、probe-*、keepalive-*
  - `_bind/` subpackage → **移到 `publishing/_bind/`**（bind-channel CLI 命令保留在 `cli/` 作為薄入口，import `publishing._bind`）
- **shim 策略**：shim re-export 不只需要 `main`，還需要每個被 tests 直接 import 的私有符號（例如 `cli/_dedup_gate.py` 的 `gate`, `record_failure`；`cli/_publish_helpers.py` 的多個 helper）。建立 shim 時需 grep `tests/` 確認每個被移動模組的所有外部 import 符號，逐一列入 shim 的 re-export 列表。
- 執行順序：(1) 移動文件 + 建 shim → (2) 跑全套 tests 確認 shim 覆蓋完整 → (3) 更新 `pyproject.toml` console_scripts → (4) 批量更新 `tests/` import paths → (5) 刪除 shim 文件 → (6) 再跑全套 tests
- `bp.py` 的 GROUPS 只含命令名稱字串，**不含 import paths，無需更新**；`test_bp_registry.py` 交叉比對 `pyproject.toml` scripts，steps (3) 後立即執行該測試確認一致性

**Test scenarios:**
- `bp` command runs → shows all groups and commands (test_bp_registry.py)
- Every CLI command callable by name → no `ModuleNotFoundError`
- `plan-backlinks --help` works after pyproject.toml update
- `publish-backlinks --help` works after pyproject.toml update
- All tests pass with updated import paths (no shim leakage)

**Verification:**
- `cli/` root 文件數（不含 `__init__.py` 和 shim 文件）≤ 10
- 每個子目錄文件數 ≤ 15
- `pytest tests/test_bp_registry.py` passes
- `pytest tests/` 零回歸

---

## System-Wide Impact

- **Interaction graph:** Phase 1 的 decomposition 不改變任何公開函數 signature 或 event 格式；helpers 全是 private (`_` 前綴)。Phase 3 的 CLI 重組改變 Python import paths，但不改變 CLI 命令名稱 / 參數 / JSONL 輸出格式。
- **Error propagation:** 拆分後 helpers 的 exception 應透傳（不在 helper 層 catch-and-swallow），orchestrator 維持現有 error handling 邊界。
- **State lifecycle risks:** Phase 1 重構不觸碰 events store、idempotency store、checkpoint 的讀寫路徑；只改函數內部結構。
- **API surface parity:** SDK（`sdk/api.py`）若有 import 自 `cli/` 的路徑，Phase 3 的 shim re-export 確保不 break；SDK extraction 計劃完成後確認 import paths。
- **Integration coverage:** 每個 decomposition unit 的 regression test 是原有集成測試（test_plan_backlinks.py 等是端到端的，非 mock）。
- **Unchanged invariants:** pipeline 的 JSONL 格式、`complexity_budget.toml` 的 enforcement 機制、`monolith_budget.toml` 的 SLOC gating 全部不動。

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| 拆分時隱式狀態耦合（local variable 跨 helpers 共享）| 用 named dataclass 傳遞 state；若 state 太複雜則只提取 pure computation，不強制拆 |
| complexity_budget.toml key 格式錯誤 → silently miss block → 落入 backstop | 每次拆分後 `pytest tests/test_no_complexity_regrowth.py` 確認 key 格式，使用 `python -m radon cc -s <file>` 確認 fullname |
| U3 `run_cycle` 無法降到 CC < 30（4 個 except loop）| 可接受 CC 32–35；PR description 說明原因，更新 budget ceiling 到實測值 |
| U2 `_run_spray` helpers 加入 `_engine.py` 打到 370-SLOC ceiling | helpers 必須放 `_engine_helpers.py` 新文件（見 U2 approach）|
| Phase 3 shim 遺漏私有符號（tests import `_dedup_gate.gate` 等）| grep `tests/` 確認每個被移動模組的所有外部 import 符號，shim 逐一列入 |
| `_util/errors.py → cli/_bind.channels` 底層違規 | U7 將 `CHANNELS` 移到 `_util/` 或 `publishing/` 非 cli 位置 |
| import-linter `layers` contract 誤判 domain 互相 import | 使用 `forbidden` contracts（見 U7 approach），不用 `layers` |
| U5 + U7 重疊（`_enhance_payload` 在 cli/ 時 import-linter 會報 validate→cli 違規）| U5 已包含將 `_enhance_payload` 移到 `validate/_payload.py`，U7 無需再動 |
| 兩個未 push 分支衝突 | Phase 1 必須在 refactor/webui-api-v1 和 perf/parallel-safe-lanes merge 到 main 之後開始 |

## Dependencies / Prerequisites

- **前置條件（Plan 不可開始前）**：`refactor/webui-api-v1` 和 `perf/parallel-safe-lanes` 兩個分支 merge 到 main
- **CI 工具鏈**：`radon==6.0.1`（已在 [dev] deps）；`import-linter` 需在 U7 新增
- **Budget 測試**：`tests/test_no_complexity_regrowth.py` 和 `tests/test_no_monolith_regrowth.py` 全程保持綠色

## Phased Delivery

### Phase 1: Complexity Reduction (U1–U5)
7 個 grandfathered 函數全部降至 CC < 30；complexity_budget.toml 的 7 個 entry 全部移除。每個 unit 獨立 PR，合並前跑全套測試。

### Phase 2: Module Boundary Hardening (U6–U7)
50+ 個 `__init__.py` 加 `__all__`；import-linter 上 CI；現有違規全部修復。

### Phase 3: CLI Reorganization (U8)
CLI 目錄重組；pyproject.toml 更新；向後相容 shim 最後清除。

## Documentation / Operational Notes

- 每個 decomposition PR 的 description 應說明：原 CC → 新 CC（orchestrator + helpers），並引用本計劃
- `complexity_budget.toml` 每次移除 entry 時，PR description 加上 "CC budget: <function> entry removed (CC <N> < backstop 30)"
- Phase 3 完成後更新 `AGENTS.md` 的 CLI entrypoints 表格（路徑對應新目錄）

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-24-001-codebase-decoupling-requirements.md](docs/brainstorms/2026-06-24-001-codebase-decoupling-requirements.md)
- Prior decomposition: Plan 2026-05-29-005 (CC budget system + `_run_resume` decomp)
- Prior decomposition: Wave 3 Unit 1 (spray/core.py::main → _engine.py)
- Prior decomposition: 2026-06-03 `_project_checkpoint` → 4 handlers
- Budget enforcement: `tests/test_no_complexity_regrowth.py` + `complexity_budget.toml`
- AGENTS.md: CLI entrypoints table, adapter registry, maintenance contract
