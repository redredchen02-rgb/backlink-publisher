---
date: 2026-06-15
topic: webui-store-base-sqlite
---

# WebUI Store 泛型化：抽出 BaseSqliteStore + RowTableMixin

## Problem Frame

`webui_store/` 下的 SQLite store 模組長期以「複製貼上」方式增長。5 個主要 store（campaign / channel_status / drafts / profiles / queue）外加 3 個 blob store（schedule / publish_defaults，profiles 亦屬此類）各自手寫了**結構幾乎相同**的 `_init_table` / `load` / `save` / `migrate_from_json` 模板。現有 `sqlite_base.py` 只抽到了 `SqliteStore`（提供 `update()` + RLock）與 `WebUIDatabase`（連接工廠），CRUD 模板本身尚未抽取。

影響：

- 新增 store 要重抄整套樣板（~150 行起跳），成本高、易出錯。
- 同一段 migration / JSON 序列化 / DELETE+bulk-INSERT 邏輯散在 8 個檔案，任何修正（如鎖語義、錯誤處理）要改 8 處。
- 約 800 行重複模板，撐高多個檔案的 SLOC 預算占用。

受影響者：維護 WebUI store 層的工程師、未來新增 store 的人。終端使用者**不應**感知任何行為變化。

## Requirements

**基類抽取**
- R1. 在 `sqlite_base.py` 新增 `BaseSqliteStore`，抽出全部 SQLite store 共用的：`__init__`（`WebUIDatabase | Path` 相容性檢查）、`_init_table`（模板方法，子類提供 table 名 / CREATE SQL / index SQL）、`load`、`save`（DELETE + bulk INSERT）、`migrate_from_json`（標準遷移流程，子類提供 JSON 檔名 / sentinel 名 / 預期型別 / 預設值）。
- R2. 新增 `RowTableMixin`，抽出項級 CRUD：`get_item` / `update_item` / `delete_item` / `bulk_delete` / `bulk_update`（子類提供主鍵欄位名與 `data_json` 約定）。
- R3. 共用工具（`_retry_sqlite`、WAL sidecar 收緊、transient error 判斷）繼續復用 `events/_store_sqlite.py`，不重複實作；如有必要僅調整 import 路徑，不搬遷。

**Store 遷移（全部 8 個）**
- R4. blob store（profiles / schedule / publish_defaults）改為繼承 `BaseSqliteStore`，僅實作 `_default_value()` 與 schema 設定點，刪除冗餘 `load` / `save`。
- R5. 行表 store（campaign / drafts / queue / channel_status）改為繼承 `BaseSqliteStore`（+ `RowTableMixin` 視需要），**保留**各自特異邏輯不抽取：campaign 的 `update_seed_status` + progress 重算、drafts 的 `inserted_at` 保序 + `bulk_publish_now`、queue 的 `get_runnable` 重試篩選、channel_status 的 `extra_json` blob 合併 + `mark_*` 業務方法 + `reconcile_on_load`。
- R6. WAL deadlock 規則維持：特異邏輯（如 `update_seed_status`）內不得產生嵌套連接。

**行為保真**
- R7. 所有對外公開方法的簽名與返回值不變；route 層呼叫端零修改。
- R8. 既有 store 測試（test_campaign_store / channel_status / drafts / profiles / queue 等，合計 ~1,545 行）全綠，且**不放寬**斷言。遷移過程不得新增 skip/xfail。
- R9. JSON→SQLite 遷移路徑（sentinel / `.json.migrated` / 0o600 權限）行為與當前一致。

**預算與文檔**
- R10. 重構後相關檔案 SLOC 下降；同 PR 內更新 `monolith_budget.toml` 對應 ceiling（下調，不需 rationale）。若任何檔案反而上升至超標，須在同 PR 提供 ≥80 字 rationale。
- R11. 若此重構閉合了 `debt_registry.toml` 中相關條目，於同 PR 標記 `resolved` + `resolved_date`。

## Success Criteria

- 全測試套件綠燈（~11,000 tests），store 相關測試零放寬、零新增 skip。
- `webui_store/` 淨減約 ~800 行；新增 store 的樣板成本從 ~150 行降至「繼承 + 實作 ≤5 個方法」。
- 對外 API diff 為零（route 層無改動可佐證）。
- 受影響檔案的 SLOC 預算占用下降並已在 budget 檔同步。

## Scope Boundaries

- **不**新增 route 層 query helper（`filter_by_status` / `get_latest_n` 等）——那是獨立改進，留待後續。
- **不**改變任何 store 的對外 API、schema 或 JSON 遷移語義。
- **不**觸碰 `history.py`（混合 JSON + events.db）與 `batch_ops.py`（無 load/save，特異）——除非遷移過程證明零成本可納入。
- **不**搬遷 `events/_store_sqlite.py` 的共用工具。
- 純內部重構，無使用者可見變化。

## Key Decisions

- 全面掃、只保行為（非試點漸進）：依賴 ~1,545 行既有 store 測試作為行為護網，一次完成避免基類設計被半套需求扭曲。
- 復用既有 `SqliteStore` / `WebUIDatabase`，`BaseSqliteStore` 為其擴展而非取代——降低 blast radius。
- 特異邏輯一律留在子類，基類只收「結構相同」的部分；抗拒過度泛型化。

## Dependencies / Assumptions

- 假設既有 store 測試覆蓋足以鎖定行為差異；若某 store 測試偏薄（profiles 138 行），規劃階段需評估是否先補特徵測試（characterization test）再重構。

## Outstanding Questions

### Deferred to Planning
- [Affects R5][Technical] `RowTableMixin` 的主鍵抽象如何同時容納 UUID 主鍵（campaign/drafts/queue）與 slug 主鍵（channel_status）——以可配置 `_pk_column` 解決，或 channel_status 不套用 mixin？
- [Affects R8][Technical] profiles store 測試僅 138 行，是否需先補 characterization test 再重構？
- [Affects R4][Technical] blob store 的 schema 設定點該用類屬性、抽象方法、或 dataclass metadata？取最簡可行。
- [Affects R1][Needs research] `migrate_from_json` 各 store 的細微差異（預期型別 list vs dict、預設值）能否完全參數化，或殘留少量 override。

## Next Steps
→ `/ce:plan` for structured implementation planning
