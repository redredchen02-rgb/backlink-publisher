---
date: 2026-06-03
topic: dispatch-backlinks
---

# dispatch-backlinks: 自動平台路由引擎

## Summary

新增 `dispatch-backlinks` CLI 命令，根據平台健康度、dofollow 狀態、referral value 和現有覆蓋數據，自動將每篇文章路由到最佳發布平台。插入在 `plan-backlinks` 和 `publish-backlinks` 之間，讓使用者不需要手動指定 `--platform`。

---

## Problem Frame

目前發一篇外鏈文章，使用者在 seed JSONL 中手動指定 `platform`（或靠 `--platform` 覆蓋整批）。要做多平台輪動發布時，要麼人工分配、要麼重複跑多次 pipeline —— 但每個平台今天的綁定狀態是否有效、dofollow 是否還活著、這篇文章的語言這平台是否支援、這個 target 是不是已經在這個平台上有太多連結 —— 這些信號在決定時都沒被考慮。

工具目前已經產出這些信號（equity-ledger、channel-scorecard、canary-targets），但它們只停留在「報表層面」，沒有人把它們串起來變成發布決策。

路由引擎把這些既有信號匯聚成一個決定：**這篇文章發哪個平台最好**。

---

## Actors

- A1. **Operator**: 運行 CLI 指令的使用者。需要 `dispatch-backlinks` 指令，輸入規劃好的 JSONL，拿到已分配平台的 JSONL。
- A2. **Routing engine** (`dispatch-backlinks`): 讀取信號、分配平台。無狀態，每次執行重新評估。
- A3. **Signal sources**: equity-ledger、channel-scorecard、canary-targets、channel-status、registry metadata。提供路由決策所需的輸入數據。

---

## Key Flows

### F1. 自動路由

- **Trigger**: Operator 執行 `dispatch-backlinks < planned.jsonl`
- **Actors**: A1, A2, A3
- **Steps**:
  1. 從 stdin 讀取 JSONL（plan-backlinks 輸出）
  2. 收集信號：active platforms + registry metadata + channel-status + canary-health
  3. 對每行決定最佳平台
  4. 在每行填入 `platform` 欄位
  5. 輸出帶 `platform` 的 JSONL 到 stdout
- **Outcome**: stdout 是可直接餵給 `publish-backlinks` 的 JSONL
- **Covered by**: R1, R2, R3, R4

### F2. 信號感知路由

- **Trigger**: Routing engine 評估某一行時
- **Actors**: A2, A3
- **Steps**:
  1. 取得所有 active platforms（排除 visibility=retired/hidden）
  2. 對每個 platform 查詢：dofollow 狀態、referral_value、channel 綁定狀態、canary 存活、policy/language 限制
  3. 過濾掉無法發布的平台（unbound、expired、language mismatch）
  4. 對剩餘平台排序：dofollow True > uncertain > nofollow_high > nofollow_low
  5. 考慮 equity-ledger 覆蓋量（避免同一個 target 集中在一個平台）
  6. 選擇最佳平台
- **Outcome**: 每行分配到一個 platform
- **Covered by**: R2, R3, R4

---

## Requirements

### 路由引擎（R1-R5）

**R1. 新增 `dispatch-backlinks` CLI 命令**
從 stdin 讀取 JSONL（與現有 pipeline 相容），逐行分配平台，輸出到 stdout。
- Input: `plan-backlinks` 產出的 JSONL（可含或不含 `platform` 欄位）
- Output: 同 input 但每行補上 `platform` 欄位，包含 `_dispatch` 元資料塊
- 非破壞性：若某行已有 `platform` 且 strategy 為 `preserve`，則保留

**R2. 多維度路由決策**
對每個候選 platform 考慮以下信號決定最佳平台：
- `dofollow_status`（True/uncertain/False）
- `referral_value`（high/low — 只對 nofollow 適用）
- `channel_status`（bound/expired/unbound）
- `canary` 存活狀態（從 canary-health.json）
- `language` 適配（若 Policy 有 language_whitelist）
- `visibility`（排除 retired/hidden）
- 該 target 在 equity-ledger 中的 `live_dofollow_platforms` 分布

策略應避免將同一 target 的所有文章都集中到同一個平台。

**R3. 平台排序邏輯**
預設排序規則（可由 `--strategy` flag 覆蓋）：
1. 排除：channel expired、language 不匹配、platform retired
2. 排序分 tier：dofollow=True > dofollow=uncertain > nofollow referral=high > nofollow referral=low
3. 同 tier 內：優先選 `live_dofollow_platforms` 最少的那個（分散覆蓋）
4. 若所有平台都被排除 → 輸出 `_dispatch_error` 並 exit 6

開放策略 choices（`--strategy`）：
- `balanced`（預設）：如上所述，兼顧品質與分散度
- `quality`：純粹以 dofollow/referral 品質排序，不考慮分散度
- `spread`：最優先分散平台負載，品質其次

**R4. 輸出格式**
每行添加 `_dispatch` 塊：
```json
{
  "...原始欄位...": {},
  "platform": "blogger",
  "_dispatch": {
    "strategy": "balanced",
    "candidates": ["blogger", "medium", "velog"],
    "reason": "dofollow=True, live_dofollow_platforms=['medium']",
    "engine_version": 1
  }
}
```
- `_dispatch` 塊僅 stdout 輸出使用，不影響 publish-backlinks
- engine_version 讓未來變更路由邏輯時可追溯

**R5. --platform 覆蓋保留**
若使用者仍顯式指定 `--platform`（傳給 `dispatch-backlinks`），則覆蓋自動路由，所有行都用該 platform（相容既有行為）。

### 信號整合（R6-R8）

**R6. 即時信號讀取**
路由引擎在每次執行時即時讀取以下信號：
- `registry.active_platforms()` + dofollow/referral meta
- `channel_status_store`（bound/expired 狀態）
- `canary-health.json`（per-platform canary 存活）
- `equity-ledger` 輸出（透過選項傳入 stdin 或即時聚合）

不緩存信號 —— 每次跑都是最新狀態。

**R7. 無信號降級**
若 equity-ledger 數據不可用（沒有 ledger 數據或不傳入），路由仍可運作：
- 只用 registry meta + channel status + canary 做決定
- stderr 輸出 WARN 提示缺少 coverage 信號
- 同 tier 內改為 round-robin

**R8. 信號過期保護**
如果某 platform 的 canary 數據超過 N 天未更新（可設定 `--canary-stale-days`），該平台的 dofollow 信賴度降級為 `uncertain`。

---

## Acceptance Examples

### AE1. 基本路由
- **Given**: 3 行 JSONL，不帶 platform，3 個 active platform（blogger dofollow=true, medium dofollow=true, velog dofollow=true），channel 全部 bound，canary 全部 alive
- **When**: 執行 `dispatch-backlinks < input.jsonl`
- **Then**: 每行輸出帶有 `platform` 欄位，`_dispatch.reason` 說明選中原因，三行應分散到不同平台（不集中在一家）

### AE2. 平台不可用
- **Given**: 某行的 target 在 `live_dofollow_platforms` 中已有 blogger + medium
- **When**: 執行 dispatch-backlinks（balanced strategy）
- **Then**: 該行的 platform 為 velog（因為要分散覆蓋），`_dispatch.reason` 標明 "spread"

### AE3. 所有平台都被排除
- **Given**: 所有 active platform 都 expired，只有一個 nofollow platform
- **When**: 執行 dispatch-backlinks（quality strategy）
- **Then**: 輸出 `_dispatch_error`，exit 6，stderr 提示「無合適平台」

### AE4. --platform 覆蓋
- **Given**: 帶有不同 platform 需求的 JSONL
- **When**: `dispatch-backlinks --platform bloger < input.jsonl`（注意拼錯）
- **Then**: argparse 報錯（不存在的 platform），exit 1
- **And**: `dispatch-backlinks --platform blogger < input.jsonl`
- **Then**: 全部行強制設為 `blogger`，不跑路由邏輯

---

## Success Criteria

1. `dispatch-backlinks` CLI 可獨立執行，作為 pipeline 中的一環
2. 路由決策可被覆現（同樣的輸入 + 同樣的信號 → 同樣的輸出）
3. 對 20+ 已註冊平台，至少能正確過濾掉不可用平台並從可用中選擇
4. `cat planned.jsonl | dispatch-backlinks | publish-backlinks --mode draft` 完整走通
5. 所有信號源不可用的降級路徑有 stderr 警告 + 正常輸出（只是品質較差）

---

## Scope Boundaries

- **WebUI 路由配置/可視化**：v1 只做 CLI，路由決策透明靠 `_dispatch` 塊輸出，不做 WebUI 儀表板
- **並發發布**：路由引擎只分配平台，不改 publish-backlinks 的執行模型（仍然是順序發布）
- **跨平台內容差異化**：同樣的內容發到被選中的平台，不改內容模板
- **時間排程**：不引入 cron-based 排程，路由即時決定
- **新平台 adapter**：路由引擎吃 registry，不加新平台

---

## Key Decisions

- **獨立 CLI 命令 vs 改 publish-backlinks**：選擇獨立命令（`dispatch-backlinks`）。關注點分離，路由是路由、發布是發布。可獨立測試，可單獨使用。
- **策略模式**：`--strategy balanced|quality|spread` 替代單一演算法，讓 operator 視目標選擇。
- **信號即時讀取**：不建信號快取服務，簡化架構。每次執行即時聚合，開銷可接受（CLI 使用場景）。

---

## Dependencies / Assumptions

- `equity-ledger` 的 `build_ledger()` 可作為 library 調用（不依賴 CLI entrypoint）
- `channel_status_store` 可 programmatically 讀取（讀 `channel-status.json`）
- `canary-health.json` 檔案位置可從 config dir 推導
- 現有 `publish-backlinks` 已支援 per-row `platform` 欄位（確認可）
- 若某平台無 channel-binding 機制（如 telegraph 是 anon），視為永久 bound

---

## Outstanding Questions

- 信號品質：equity-ledger / canary / channel-scorecard 目前的可靠度是否足以支撐路由決策？若數據不足，balanced strategy 會退化為接近 round-robin
- language_whitelist 目前只在 Policy manifest 中，但並非所有 platform 都有宣告——無宣告的視為不限制？
