---
title: "fix: telegra.ph dispatch weight discount"
type: fix
status: active
date: 2026-06-03
---

# fix: telegra.ph dispatch weight discount

## Overview

telegra.ph 目前在 dispatch routing 中與其他 dofollow 平台同分競爭，但實測顯示 57 篇文章中有 23 篇（40%）在發布時錨就沒進去（born_stripped），另有 1 篇事後翻轉。依 Iron Law，根因仍在「平台 anti-spam 清理」vs「publish body 錨丟失」之間，無法確定，所以不修 instant_web.py。

正確的收斂路徑是：**在 dispatch routing 層對 telegra.ph 施加固定可信度折扣**，讓路由引擎在有更可靠平台可選時自動繞開它。equity-ledger 已正確計量損耗（只把 alive 計入 live_dofollow），所以測量面不需改動。

---

## Problem Frame

- `dispatch/routing.py` 的 Phase 2 Score 不含任何 per-platform 可信度權重
- telegra.ph 被登記為 `dofollow=True`，路由引擎依此給它最高 tier 分 (4)
- 但 23/57 (40%) 的鏈在發布時就未進去，equity-ledger 已正確計量（live_dofollow=33, born_stripped≈23）
- 根因未確認（anti-spam vs publish body）→ Iron Law 不允許捏造修補
- 策略層修法：`dispatch_weight` 折扣讓引擎在有選擇時優先其他平台

---

## Requirements Trace

- R1. `RegistryEntry` 新增 `dispatch_weight: float = 1.0` 欄位，由 `register()` 接收，並有 accessor `dispatch_weight(name)`
- R2. `PlatformSignal` 新增 `dispatch_weight: float = 1.0`，由 `collect_all()` 從 registry 讀取
- R3. `routing.py` Phase 2 Score 對每個 candidate 乘以 `sig.dispatch_weight`（apply to final score，不區分 strategy）
- R4. `TELEGRAPH_MANIFEST` 設 `dispatch_weight=0.6`，附帶實測根因說明（23/57 born_stripped）
- R5. `ENGINE_VERSION` 升至 2（路由輸出不向後相容）
- R6. 不改 `instant_web.py` / `recheck` / `equity-ledger` — 損耗度量面不動

---

## Scope Boundaries

- **不修 telegraph publish body（instant_web.py）** — 根因未確認，Iron Law
- **不改 recheck/equity-ledger** — 已正確計量
- **不調整 canary 數據** — canary 只看 link-alive，born_stripped 不會觸發 canary
- **不為 dispatch_weight 引入 CLI flag** — v1 純 registry 宣告
- **不為 `dispatch_weight` 新增獨立 rationale gate** — dofollow=True 時 rationale 非必填（與現有 register gate 一致）

---

## Context & Research

### Relevant Code and Patterns

- **`RegistryEntry`** (`registry.py:118`): frozen dataclass，現有 optional 欄位（`rationale`, `referral_value`, `credential_saver`）都有 default。新增欄位 `dispatch_weight: float = 1.0` 遵循同樣 default-safe 模式
- **`register()`** (`registry.py:291`): explicit kwarg list，每個欄位都有對應 validation。`dispatch_weight` 需加驗證（`0.0 < dispatch_weight <= 1.0`）
- **accessor 模式**: `dofollow_status(name)`, `referral_value(name)`, `visibility(name)` — 全部從 `_REGISTRY[name]` 讀一個欄位。`dispatch_weight(name)` 遵循同樣模式，缺 entry 回傳 `1.0`
- **`PlatformSignal`** (`signals.py:27`): pure dataclass，所有欄位有 default。`dispatch_weight: float = 1.0` 按同樣方式添加
- **`collect_all()`** (`signals.py:78`): 逐一讀 registry，此時增加一行 `dispatch_weight=dispatch_weight(name)` 即可
- **`routing.py` Phase 2 Score** (line 173–207): 現有 `score = base_score + ...`。乘以 `sig.dispatch_weight` 加在每個 strategy 的 final score 計算後
- **`TELEGRAPH_MANIFEST`** (`_manifests.py:99`): 現有鍵：ui, bind, policy。新加 `dispatch_weight=0.6` 是第四個頂層鍵
- **`_manifests.py` import guard** (`_manifests.py:11`): `if TYPE_CHECKING:` 區塊 import `Policy`/`UiMeta`，`dispatch_weight` 是 float 不需 import

### Evidence Basis for 0.6

- 57 篇文章 recheck 結果：33 stable_alive / 23 born_stripped / 1 flipped
- born_stripped rate = 23/57 ≈ 40% → 可信度 ≈ 60% → `dispatch_weight=0.6`
- 此值是保守近似，不是精確測量（sample size 57）；後續 recheck 數據累積後可調整

---

## Key Technical Decisions

| 決策 | 理由 |
|------|------|
| weight 乘在 final score（策略分之後，含 spread bonus） | 最簡單且跨三種 strategy 一致；uniform discount 確保 telegraph 在所有策略下都輸給等分對手，包含 spread 場景；一行改動。注意：spread bonus 也被折扣，這是故意的——低可靠度平台即使恰好「缺覆蓋」也應讓路 |
| weight 放 TELEGRAPH_MANIFEST 而非 register() 直接傳 | manifest 是 per-platform 元資料包，與 ui/policy 同層；未來其他低可信度平台可照樣設 |
| weight 不分 strategy | 可靠度折扣是 platform 事實，不因 operator 選 quality/spread/balanced 改變 |
| `dispatch_weight(name)` 缺 entry 回傳 1.0（不 raise） | 新欄位 optional，舊 register() 呼叫不用改；1.0 = no discount，安全降級 |
| ENGINE_VERSION 升 2 | 相同輸入下 output 的 platform 選擇可能不同，v2 標記方便 audit |
| weight 驗證: `0.0 < weight <= 1.0` | 0.0 = 永遠不選（等同 retired），用 visibility 表達；>1.0 無意義（boost 路徑不在此計畫） |
| signals.py 用 `registry_dispatch_weight` alias import | `PlatformSignal.dispatch_weight` 與 `registry.dispatch_weight()` 函數同名；alias 必須保留，不得移除 |

---

## Implementation Units

- [ ] **Unit 1: registry infrastructure**

**Goal:** 在 `RegistryEntry` + `register()` 中加 `dispatch_weight`；新增 `dispatch_weight(name)` accessor。

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/publishing/registry.py`
- Test: `tests/test_registry_dofollow_kwargs.py` （現有 registry 測試套件，驗證新 kwarg）

**Approach:**
- `RegistryEntry` 加欄位 `dispatch_weight: float = 1.0`（在 `credential_saver` 之後）
- `register()` 加 kwarg `dispatch_weight: float = 1.0`
- 驗證：`if not (0.0 < dispatch_weight <= 1.0): raise RegistryError(...)`
- `_REGISTRY[platform] = RegistryEntry(..., dispatch_weight=dispatch_weight)`
- 新增 accessor：
  ```python
  def dispatch_weight(name: str) -> float:
      entry = _REGISTRY.get(name)
      return entry.dispatch_weight if entry is not None else 1.0
  ```

**Patterns to follow:**
- `registry.py` 的 `referral_value(name)` accessor（L200 附近）
- `RegistryEntry` 現有 optional 欄位 default 模式

**Test scenarios:**
- Happy path: `register("x", ..., dispatch_weight=0.7)` → `dispatch_weight("x")` returns 0.7
- Default: register without `dispatch_weight` → `dispatch_weight("anyplatform")` returns 1.0
- Unknown platform: `dispatch_weight("nonexistent")` returns 1.0（not raise）
- Edge: `dispatch_weight=1.0` accepted
- Validation: `dispatch_weight=0.0` raises RegistryError
- Validation: `dispatch_weight=1.1` raises RegistryError
- Validation: `dispatch_weight=-0.1` raises RegistryError

**Verification:**
- Existing registry tests all green（新 kwarg default=1.0 不影響現有 register 呼叫）
- `dispatch_weight("telegraph")` 在 adapters 被 import 後可呼叫（U3 之後）

---

- [ ] **Unit 2: signals + routing integration**

**Goal:** 將 `dispatch_weight` 從 registry 傳入 `PlatformSignal`，並在 routing Phase 2 Score 中乘入。`ENGINE_VERSION` 升 2。

**Requirements:** R2, R3, R5

**Dependencies:** Unit 1

**Files:**
- Modify: `src/backlink_publisher/dispatch/signals.py`
- Modify: `src/backlink_publisher/dispatch/routing.py`
- Modify: `src/backlink_publisher/cli/dispatch_backlinks.py` （hardcoded `engine_version: 1` → `ENGINE_VERSION`）
- Test: `tests/test_dispatch_backlinks.py`

**Approach:**

`signals.py`:
- `PlatformSignal` 加 `dispatch_weight: float = 1.0`
- `collect_all()` 中新增 import `from backlink_publisher.publishing.registry import dispatch_weight as registry_dispatch_weight`（避免名稱衝突）
- 收集時加一行：`dispatch_weight=registry_dispatch_weight(name)`

`routing.py`:
- 把 `ENGINE_VERSION = 1` 改 `ENGINE_VERSION = 2`
- 在 Phase 2 Score 的三個 strategy 計算之後（現行 `scored.append((score, sig.name))`），改為：
  ```python
  final_score = score * sig.dispatch_weight
  scored.append((final_score, sig.name))
  ```
- dispatch meta 的 `reason` 中補上 `dispatch_weight=<value>` 當值 != 1.0 時

**Patterns to follow:**
- `signals.py` 現有 `canary_last_ok_at` / `language_whitelist` 收集模式
- `routing.py` Phase 2 現有 scored.append 模式

**Note:** `dispatch_backlinks.py:143` 有 `"engine_version": 1` 硬碼（非使用常數），此行需同步改為 `"engine_version": ENGINE_VERSION`。

**Test scenarios:**
- Happy path: `dispatch_weight=1.0`（default） → score 不變
- Discount: `dispatch_weight=0.6` → 原 score=5.0 變 3.0
- Discount wins tiebreak: platform A (tier=4, weight=0.6) vs platform B (tier=3, weight=1.0) → B 勝（4×0.6=2.4 < 3×1.0=3.0）
- Spread strategy explicit: telegra.ph (base_score=2, spread_bonus=9, weight=0.6) → (2+9)×0.6=6.6 vs ghpages (base=2, spread=9, weight=1.0) → 11.0 → ghpages 勝（確認 spread bonus 也被折扣）
- `ENGINE_VERSION` in dispatch metadata = 2
- `reason` 含 `dispatch_weight=0.6` when weight != 1.0

**Verification:**
- `pytest tests/test_dispatch_backlinks.py -v` all green
- 現有 `test_dispatch_backlinks.py` 的 Engine v1 scenario 改為 v2
- `dispatch_backlinks.py:143` `engine_version` 不再硬碼 1

---

- [ ] **Unit 3: telegraph weight declaration**

**Goal:** 在 `TELEGRAPH_MANIFEST` 設 `dispatch_weight=0.6`，附帶根因文字。

**Requirements:** R4

**Dependencies:** Unit 1 (registry 能接收此 kwarg)

**Files:**
- Modify: `src/backlink_publisher/publishing/_manifests.py`

**Approach:**
- 在 `TELEGRAPH_MANIFEST` dict 前（或 `ui=...` 之前）加 comment 說明 evidence：
  ```
  # 2026-06-03 recheck: 57 links -- 33 alive / 23 born_stripped / 1 flipped.
  # born_stripped rate ~40%; root cause unconfirmed (anti-spam vs publish body).
  # dispatch_weight=0.6 discounts routing score without blocking the platform.
  ```
- 在 dict 中加 `dispatch_weight=0.6,` 作為第一個鍵（在 `ui=` 之前）
- 不改 `dofollow=True`（仍屬 dofollow 平台；問題是可靠度，不是 dofollow 屬性）

**Patterns to follow:**
- `_manifests.py` 其他 manifest comment 風格（inline rationale above the dict）

**Test scenarios:**
- Integration: import adapters → `dispatch_weight("telegraph")` returns 0.6
- Existing adapter unit tests for telegraph all green（manifest 加欄位不影響現有行為）
- `tests/test_r9_extension_readiness.py` still green（新 kwarg 走 register() 不走 cli/*.py）

**Verification:**
- `from backlink_publisher.publishing import adapters; from backlink_publisher.publishing.registry import dispatch_weight; print(dispatch_weight("telegraph"))` → `0.6`
- Full test suite green

---

## System-Wide Impact

- **Interaction graph:** 純 read-only 信號鏈延長。`register()` → `RegistryEntry` → `dispatch_weight()` accessor → `collect_all()` → `PlatformSignal` → `route()` Phase 2 Score。沒有 callback/middleware/寫入。
- **Error propagation:** `dispatch_weight` 驗證在 import time（同 referral_value gate），錯誤為 RegistryError
- **State lifecycle risks:** 無狀態寫入。`_REGISTRY` 是 module-level dict，與現有欄位同生命週期
- **API surface parity:** `dispatch_weight(name)` 是 library 函數；WebUI 不消費它（no plan for UI display）
- **Unchanged invariants:** `dofollow=True` 宣告不變（影響 filter phase）；canary gate 不變；ledger 計量不變；recheck 不變；equity-ledger 不變
- **ENGINE_VERSION 升 2:** audit 確認：`engine_version` 在 `routing.py`（常數 + 2 個 dispatch 塊）、`dispatch_backlinks.py:143`（硬碼 1，需修）、`tests/test_dispatch_backlinks.py`（import ENGINE_VERSION 常數，自動跟隨）。無其他消費方
- **telegraph 的 Phase 1 binding:** telegra.ph 在 `signals._ALWAYS_BOUND` 中，`_get_binding()` 返回 `"bound"`，通過 Phase 1 filter → 確認進入 Phase 2 Score，`dispatch_weight` 有效

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `dispatch_weight=0.6` 設定的 0.6 不夠準確（sample=57） | 值是意圖，不是精確推論；附帶 recheck evidence；後續可基於更多數據在 manifest 調整 |
| `test_dispatch_backlinks.py` ENGINE_VERSION assertion | 測試 import `ENGINE_VERSION` 常數（非硬碼 1），升版後自動跟隨 |
| `dispatch_backlinks.py:143` 硬碼 `"engine_version": 1` | Unit 2 中同步改為 `"engine_version": ENGINE_VERSION` |
| `_manifests.py` 加新 kwarg 但 registry.py 未先更新（unit order） | Unit 1 先執行（add field），Unit 3 後執行（use field）；依賴序清晰 |
| complexity_budget.toml 中 routing.py 有 ceiling | routing.py 目前 239 行；加 2 行（final_score + import）遠低於任何合理 ceiling |

---

## Sources & References

- Dispatch routing engine: `src/backlink_publisher/dispatch/routing.py`
- Platform signals: `src/backlink_publisher/dispatch/signals.py`
- Registry: `src/backlink_publisher/publishing/registry.py`
- Telegraph manifest: `src/backlink_publisher/publishing/_manifests.py:99`
- Registry tests: `tests/test_registry_dofollow_kwargs.py`, `tests/test_dispatch_backlinks.py`
- Related plan (routing engine origin): `docs/plans/2026-06-03-002-feat-dispatch-backlinks-plan.md`
