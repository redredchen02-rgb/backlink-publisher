---
title: "feat: Phase 0 calibrated implementation plan"
type: feat
status: completed
date: 2026-06-10
origin: docs/plans/2026-06-10-002-feat-full-automation-upgrade-plan.md
claims:
  paths:
    - src/backlink_publisher/optimization/
    - src/backlink_publisher/cli/weights.py
    - src/backlink_publisher/publishing/registry.py
    - src/backlink_publisher/dispatch/signals.py
    - src/backlink_publisher/dispatch/routing.py
    - scripts/run-optimization.sh
    - tests/test_optimization_rules.py
    - tests/test_dispatch_weight_optimization.py
    - tests/test_optimization_e2e.py
    - tests/test_optimization_state.py
  shas:
    - HEAD
---

# Phase 0 Calibrated Implementation Plan

> **基於 2026-06-10 的 codebase 實地調查重新校準的 Phase 0 計劃。**
> 發現原計劃（2026-06-10-002）中的 U1.1–U1.4 實際上**已全部實作完畢**。
> 本計劃反映真實差距，不做已經完成的工作。

---

## 0. 原始碼調查總結

### 0.1 原計劃聲稱 vs 實際狀況

| 項目 | 原計劃聲稱 | 實際狀況 | 原始碼證據 |
|---|---|---|---|
| U1.1 preferred_dispatch() 接入動態權重 | ❌ 未實作 | ✅ **已實作** | `registry.py` L528-574 `dispatch_weight()` 已讀 `optimization_state.json`；`signals.py` L123 呼叫；`routing.py` L207 使用 |
| U1.2 optimize-weights 移除 dry-run + safety gate | ❌ 需新增 safety gate | ✅ **已實作** | `weights.py` L85-136 `_safety_check()` 完整；`--dry-run` 是 opt-in；腳本已生產模式 |
| U1.3 Rule 3: 存活率統計閾值 | ❌ 需要新增 | ✅ **已實作** | `rules.py` L248-322 `_rule_aggregated_stats()` 完整 + 已註冊 |
| U1.4 Canary cooldown auto-recovery | ❌ 需要新增 cooldown | ✅ **已實作** | `rules.py` L96-128 cooldown + slow-start 完整 |
| U1.5 雙語權重分離 | ❌ 需要實作 | ⏳ **未實作** | `models.py` L58-64 `OptimizationStateData` version 1 flat schema |
| U1.6 測試驗證 | - | ⚠️ 測試存在但需確認 green | 4 個測試檔案存在 |

### 0.2 核心發現：優化循環已經閉合

```
run-optimization.sh
  → weights collect（收集 recheck/canary/equity signals）
  → weights optimize（執行 Rule 1/2/3，寫入 weights）
    → optimization_state.json（weights + stats）
      → dispatch_weight() 讀取動態權重（registry.py L528）
        → signals.py 在收集訊號時帶入權重
          → routing.py 用權重計算最終分數
            → 影響平台選擇順序
```

這個循環的每一環都已實作。缺的只是：
- **U1.5** 雙語分離（extension to version 2 schema）
- **讓它真正啟動**：確認 launchd 有排程 `run-optimization.sh`

---

## 1. 真實 Phase 0 範圍（4 個工作項目）

### W1: 雙語權重分離（唯一開發工作）

**目標**：讓 `optimization_state.json` 支援 `{"zh-CN": {...}, "en": {...}}` 雙語言權重空間。

#### 1.1 Schema 版本升級

**檔案**：`optimization/models.py`

```python
# 當前 version 1（flat）
{
    "version": 1,
    "weights": {"blogger": {"base": 1.0, "current": 0.8, ...}},
    "stats": {"blogger": {"alive_count": 5, ...}},
}

# 目標 version 2（bilingual）
{
    "version": 2,
    "weights": {
        "zh-CN": {
            "blogger": {"base": 1.0, "current": 0.8, ...}
        },
        "en": {
            "devto": {"base": 1.0, "current": 1.2, ...}
        }
    },
    "stats": {
        "zh-CN": {
            "blogger": {"alive_count": 5, ...}
        },
        "en": {
            "devto": {"alive_count": 3, ...}
        }
    },
}
```

**變更點**：
1. `default_state()` 回傳 `version=2` 新格式
2. 新增 `_upgrade_v1_to_v2()` 遷移函數：將 flat 權重包裝為 `{"default": {...}}`
3. `OptimizationState.load()` 在讀取後自動檢查 version 並升級
4. `OptimizationStateData` dataclass 可選更新（或保持 dict 靈活）

#### 1.2 State 層支援 language 參數

**檔案**：`optimization/state.py`

所有公開方法追加可選 `language: str = "default"` 參數：

```python
class OptimizationState:
    def get_weight(self, adapter_name: str, default: float = 1.0,
                   language: str = "default") -> float:
        data = self.load()
        if data.get("version", 1) >= 2:
            lang_data = data.get("weights", {}).get(language, {})
            # fallback: 如果該語言沒有此平台，嘗試 "default"
            if adapter_name not in lang_data and language != "default":
                lang_data = data.get("weights", {}).get("default", {})
        else:
            lang_data = data.get("weights", {})  # version 1 backward compat
        entry = lang_data.get(adapter_name)
        ...

    def set_weight(self, adapter_name: str, weight: float,
                   rule: str, reason: str,
                   language: str = "default",
                   force: bool = False) -> None:
        # 寫入時指定語言空間
        ...

    def update_stats(self, adapter_name: str, stats_update: dict,
                     language: str = "default") -> None:
        # stats 也按語言分開
        ...
```

**關鍵設計決策**：
- `language="default"` = 該語言沒資料時的 fallback 空間
- `language="zh-CN"` / `"en"` = 真實語言空間
- version 1 → 2 升級時，整個 flat space 搬到 `{"default": ...}`
- version 2 讀到 `language="default"` 時直接查 weights.default
- 不修改版本號以外的 property，保持向後兼容

#### 1.3 Registry 層支援 language 傳遞

**檔案**：`publishing/registry.py`

```python
def dispatch_weight(name: str, language: str = "default") -> float:
    """Return the routing reliability discount for ``name``.

    New *language* parameter selects the language-specific weight space.
    Defaults to "default" (backward compatible).
    """
    entry = _REGISTRY.get(name)
    static = entry.dispatch_weight if entry is not None else 1.0

    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        dynamic = state.get_weight(name, default=None, language=language)
        if dynamic is not None:
            value = float(dynamic)
            # ... existing clamp logic ...
            return value
    except Exception:
        pass

    return static
```

#### 1.4 Signal 層收集時帶入語言

**檔案**：`dispatch/signals.py`

`PlatformSignal` 新增 `language: str = "default"` 欄位，`collect_all()` 接受 `language: str = "default"` 參數並傳遞。

```python
@dataclass
class PlatformSignal:
    name: str
    language: str = "default"
    # ... existing fields ...

def collect_all(channel_data=None, language: str = "default") -> dict[str, PlatformSignal]:
    # 所有 platform 帶入相同 language tag
    for name in platforms:
        sig = PlatformSignal(
            name=name,
            language=language,
            dispatch_weight=registry_dispatch_weight(name, language=language),
            ...
        )
```

#### 1.5 Dispatch/Routing 支援語言傳遞

**檔案**：`dispatch/routing.py`

如果 `RouteResult` 需要記錄語言，或者排序時帶入語言感知，輕量改造：

```python
def score_platforms(strategy, signals, language="default"):
    # 根據 language 篩選或有語言對應的 dispatch_weight
    pass
```

#### 1.6 CLI `weights` 支援 `--lang`

**檔案**：`cli/weights.py`

三個子命令都新增 `--lang` 參數：

```bash
weights collect --lang zh-CN    # 收集中文語種訊號
weights optimize --lang en      # 優化英文語種權重
weights show --lang zh-CN       # 顯示中文語種權重
```

實作方式：`_handle_collect` / `_handle_optimize` / `_handle_show` 將 `args.lang` 傳入對應的 state 方法。

#### 1.7 向後相容驗證

| 情境 | 預期行為 |
|---|---|
| 舊版 `version=1` json 存在 | 自動升級到 version 2，flat → `{"default": ...}` |
| 舊版讀取後寫入 | 寫入 version 2 格式 |
| 新版 `version=2` 不含 language | 讀 `weights.default` |
| 新版含 bilingual data | 按 language 讀取對應 weights |
| 所有現有測試 | 保持綠色（因為 `language="default"` 是預設值） |

---

### W2: 確保 Run-optimization 生產就緒

**目標**：確認 `run-optimization.sh` 在 launchd 下正確執行、有資料流入 `optimization_state.json`。

#### 2.1 審計 launchd plist

**檔案**：`scripts/com.dex.bp-optimization.plist`

- 確認 `ProgramArguments` 指向正確的 `run-optimization.sh` 路徑
- 確認 `StartInterval` 是否合理（現有應為每 6 小時：`21600` 秒）
- 確認 `StandardOutPath` / `StandardErrorPath` 指向可寫的 log 位置

#### 2.2 手動觸發一次完整 cycle

```bash
cd backlink-publisher
bash scripts/run-optimization.sh
```

預期：
- `logs/optimization.log` 出現 `=== optimization run starting ===` 和 `=== optimization run complete ===`
- `config_dir/optimization_state.json` 出現 `weights` / `stats` 資料
- `weights show` 顯示平台統計

#### 2.3 乾 run 模擬

如果 production 環境沒有實際的 recheck/canary 資料，新增一個模擬腳本或手動注入：

```bash
# 手動注入測試 stats
python -c "
from backlink_publisher.optimization import OptimizationState
s = OptimizationState()
s.update_stats('blogger', {'total_published': 10, 'alive_count': 8, 'dofollow_count': 7})
s.update_stats('telegraph', {'total_published': 15, 'alive_count': 12, 'dofollow_count': 10})
s.update_stats('medium', {'total_published': 5, 'alive_count': 1, 'dofollow_count': 0})
s.update_stats('velog', {'total_published': 8, 'alive_count': 6, 'dofollow_count': 5})
"
```

---

### W3: 整理現有測試 + 新增 U1.5 雙語測試

#### 3.1 確認現有測試全部 green

執行：

```bash
pytest tests/test_optimization_rules.py -v
pytest tests/test_dispatch_weight_optimization.py -v
pytest tests/test_optimization_e2e.py -v
pytest tests/test_optimization_state.py -v
```

#### 3.2 新增 U1.5 雙語測試

**檔案**：`tests/test_optimization_bilingual.py`

| 測試案例 | 涵蓋範圍 |
|---|---|
| `test_v1_to_v2_upgrade` | version 1 flat schema → 自動升級到 version 2 |
| `test_language_specific_weight` | zh-CN 和 en 相同平台不同權重 |
| `test_language_fallback_default` | 指定語言無資料時 fallback 到 default |
| `test_legacy_read_backward_compat` | 舊版 client 讀新版檔案不崩潰 |
| `test_dispatch_weight_with_language` | `dispatch_weight('blogger', language='zh-CN')` 正確讀取 |
| `test_cli_lang_flag` | `weights show --lang zh-CN` 正常運作 |

---

### W4: 端到端驗證（U1.6 驗收）

#### 4.1 離線 E2E

```bash
# 1. 注入測試資料
python -c "
from backlink_publisher.optimization import OptimizationState
s = OptimizationState()
s.update_stats('blogger', {'total_published': 10, 'alive_count': 8, 'dofollow_count': 7})
s.update_stats('medium', {'total_published': 5, 'alive_count': 1, 'dofollow_count': 0, 'drift_count': 4})
"
# 2. 執行 optimize，看規則是否觸發
python -m backlink_publisher.cli.weights optimize

# 3. 確認 dispatch_weight 反映權重
python -c "
from backlink_publisher.publishing import registry
print('blogger:', registry.dispatch_weight('blogger'))
print('medium:', registry.dispatch_weight('medium'))
"
```

#### 4.2 plan-backlinks 驗證（可選）

如果現有 fixture 可以跑完整 `plan → validate → publish --dry-run`：

```bash
cat fixtures/seed.jsonl | \
  python -m backlink_publisher.cli.plan_backlinks --dry-run 2>&1 | \
  python -m backlink_publisher.cli.validate_backlinks | \
  python -m backlink_publisher.cli.publish_backlinks --dry-run 2>&1 | \
  grep -E "dispatch_weight|platform="
```

#### 4.3 優化腳本 E2E

```bash
bash scripts/run-optimization.sh
weights show
# → 應顯示平台權重已調整
```

---

## 2. 預計工時

| 項目 | 規模 | 預計時間 |
|---|---|---|
| W1.1 Schema 版本升級 | S | 0.5h |
| W1.2 State 層 language 參數 | M | 1.5h |
| W1.3 Registry 層 language 傳遞 | S | 0.5h |
| W1.4 Signal 層 language 傳遞 | S | 0.5h |
| W1.5 CLI --lang 參數 | S | 0.5h |
| W2 run-optimization 生產就緒 | S | 0.5h |
| W3 整理現有測試 + 新增雙語測試 | M | 1.5h |
| W4 端到端驗證 | S | 0.5h |
| **總計** | | **~6h** |

---

## 3. 不做（明確 scope out）

| 不做 | 理由 |
|---|---|
| 重新實作 U1.1-U1.4 | 已經完成，不做重複工作 |
| 修改 dispatch/routing.py 的 routing 邏輯 | 已經用 `sig.dispatch_weight` 接入，不需要改 |
| 新增 `preferred_dispatch()` 函數 | 現有架構透過 signals → routing 路徑，不需要此函數 |
| 修改 `scripts/run-full-pipeline.sh` | 那是 Phase 1（U2.1 Pipeline Orchestrator）的範圍 |
| 生產環境部署 | 只做本地驗證，不碰 launchd / production |

---

## 4. 風險

| 風險 | 緩解 |
|---|---|
| version 1→2 升級時遺漏某個讀取路徑 | 每個 `OptimizationState` 公開方法都檢查 version |
| language 參數污染所有呼叫點 | 預設值 `"default"` 確保向後相容 |
| 雙語分離後 weights 管理變複雜 | WebUI 和 CLI `weights show` 按語言分別展示 |
| run-optimization.sh 在 launchd 下路徑不同 | 2.1 審計 plist + 2.2 手動觸發 |

---

## 5. 驗收標準

1. `pytest tests/test_optimization_*.py -v` 全部綠色
2. version 1 flat schema 自動升級到 version 2 不遺失資料
3. `weights show --lang zh-CN` 和 `weights show --lang en` 分別顯示
4. `dispatch_weight('blogger', language='zh-CN') != dispatch_weight('blogger', language='en')` 當設了不同權重
5. 所有現有測試不需要改動（向後相容）
6. `bash scripts/run-optimization.sh` 正常完成（exit 0）
7. weights show 顯示至少一個平台有權重調整
