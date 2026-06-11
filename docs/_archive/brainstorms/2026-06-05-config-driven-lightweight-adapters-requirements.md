---
date: 2026-06-05
topic: config-driven-lightweight-adapters
---

# Config-Driven Lightweight Adapter Framework + Dofollow Priority Tier

## Problem Frame

目前系統有 24 個發布平台，其中只有 4–5 個真正達到「免登入 + dofollow」的最佳組合
（telegraph、txtfyi、notesio、rentry）。每新增一個類似平台都要寫一個獨立的 Python adapter
檔案，即使它們的邏輯幾乎相同（GET 表單 → 擷取隱藏欄位 → POST 內容 → 追蹤重導向）。

這造成兩個問題：
1. **擴充摩擦高**：找到新的免登入 dofollow 平台後，要幾天才能接入。
2. **優先級不可見**：CLI 和 WebUI 平等對待所有平台，dofollow 確認的高價值渠道不會自動優先。

```
今日平台分佈：

dofollow=True (5)      : blogger / medium / telegraph / velog / ghpages
dofollow=uncertain (11): wordpresscom / hashnode / substack / hatena / hackmd /
                         mataroa / gitlabpages / writeas / rentry / txtfyi / notesio
dofollow=False (8)     : linkedin / tumblr / livejournal / devto / notion /
                         mastodon / qiita / zenn

免登入 + dofollow：telegraph(確認) + txtfyi/notesio/rentry(uncertain)
```

## Requirements

**Config-Driven Adapter Format**

- R1. 在 `src/backlink_publisher/publishing/adapters/catalog/` 新增 YAML catalog
  格式，每個輕量平台一個 `.yaml` 入口，描述：slug、endpoint、auth_type（`none` 或
  `api_key_header` 或 `api_key_query`）、content_field、csrf_prefetch（布林）、
  csrf_field_names（可選清單）、permalink_via（`redirect` | `json_path` | `regex`）、
  permalink_arg（對應 json path 或 regex string）、min_delay_s。

- R2. 支援 auth_type=`none`（完全匿名 HTTP form-POST，如 txtfyi/notesio）和
  auth_type=`api_key_header` / `api_key_query`（REST API + token，如 mataroa/hackmd 同類）。
  不支援 OAuth 或瀏覽器型登入（由現有 adapter 覆蓋）。

- R3. `ConfigDrivenAdapter` 類別：讀取一個 catalog YAML 入口，組合既有
  `http_form_post.py` 的 `fetch_form` / `extract_hidden_fields` / `submit_form` 完成發布；
  REST API 路徑使用 `requests.post` + Authorization/api-key header。

- R4. adapters `__init__.py` 在啟動時自動掃描 `catalog/` 目錄並呼叫 `register()`，
  新增平台不需要修改任何 Python 檔案，只加 YAML 即可。

- R5. Catalog YAML 入口必須宣告 `dofollow: uncertain | true | false` 和
  `rationale`（≥ 80 字元，對應既有 `_nofollow_rationales.py` 契約）；
  初始值預設為 `uncertain`，由人工或 canary 結果覆蓋。

**Dofollow 驗證流程整合**

- R6. 新加入 catalog 的平台 dofollow 預設 `uncertain`；系統在第一次發布成功後
  自動記錄發布 URL 到一個待驗清單（`$BACKLINK_PUBLISHER_CONFIG_DIR/verify-queue.jsonl`，
  預設 `~/.config/backlink-publisher/verify-queue.jsonl`）。

- R7. `verify-dofollow <slug>` CLI 子命令：從待驗清單讀取最新的發布 URL，
  呼叫既有 `verify_link_attributes` 做屬性探查，輸出 `dofollow=True/False`，
  並寫回 catalog YAML 的 `dofollow` 欄位（原子寫入）。

- R8. dofollow 狀態改為 `true` 後，下次啟動時重新掃描 catalog 即反映新 tier；
  WebUI 長期運行中需重啟才能生效（registry RegistryEntry 為 frozen dataclass，
  無運行時 hot-reload 機制）。

**Tier 優先調度**

- R9. 平台 tier 定義：
  - Tier 1 = `dofollow=True`（已確認傳遞 PageRank）
  - Tier 2 = `dofollow=uncertain`（尚待驗證）
  - Tier 3 = `dofollow=False`（僅流量 / 品牌信號）

- R10. `publish-backlinks` 新增 `--tier-1` / `--dofollow-only` flag：
  dispatch 僅包含 Tier 1 平台；flag 互斥，`--tier-1` 是規範名稱，`--dofollow-only`
  為別名。未傳入 flag 時行為與現在相同（所有 tier）。

- R11. WebUI「渠道」頁面頂部新增「優先渠道」分組（Tier 1 + referral_value=high）；
  「一鍵僅發 Tier 1」按鈕呼叫 WebUI 的 publish 端點並帶 `tier=1` 查詢參數。

## Success Criteria

- 新增一個 HTTP form-POST 平台：只需新增一個 YAML 檔，執行 `pytest tests/` 全過，
  不需要修改任何 Python 檔案。
- 新增一個 api_key REST 平台：只需 YAML 檔 + `config.example.toml` 新增 api_key
  說明，不需改 Python。
- `verify-dofollow <slug>` 執行後，catalog YAML 的 `dofollow` 欄位自動更新為
  `true` 或 `false`，下次發布即反映在 tier 排序。
- `publish-backlinks --tier-1` 只對 dofollow=True 的平台投遞，exit code 0。
- WebUI「優先渠道」區塊列出 Tier 1 平台，並能一鍵僅發送。

## Scope Boundaries

- 不含 OAuth / 瀏覽器型登入平台（Medium、WordPress.com OAuth 等已有獨立 adapter 覆蓋）。
- 不含「自動發現新平台」（人工找到候選 URL，然後填 YAML；discovery pipeline 屬另一 brainstorm）。
- 不含將現有手寫 adapter（txtfyi、notesio、rentry）遷移到 config-driven 框架
  （現有 adapter 可共存；遷移是可選後續工作）。
- `verify-dofollow` 不自動排程，只在人工觸發時執行（排程是後續 canary 自動化的範疇）。

## Key Decisions

- **YAML catalog 而非 TOML**：現有 budget 文件用 TOML；adapter 配置用 YAML 以支援
  清單欄位（csrf_field_names）和多行 rationale 而不需轉義，格式更可讀。
- **不遷移現有 adapter**：txtfyi/notesio/rentry 保留現有 Python adapter；
  config-driven 框架從新平台開始，降低風險。
- **tier 定義綁 dofollow 欄位**：不引入新的 priority 欄位，tier 直接從 registry 的
  `dofollow` 推導，避免雙重維護。

## Dependencies / Assumptions

- `http_form_post.py` 的 `fetch_form` / `extract_hidden_fields` / `submit_form` 介面
  穩定（不改 signature），`ConfigDrivenAdapter` 直接 import 使用。
- Catalog YAML 由 `PyYAML`（已在生產依賴，`pyproject.toml [project.dependencies]`）解析。
- 所有 catalog YAML 解析必須使用 `yaml.safe_load()`（非 `yaml.load()`），
  防止 `!!python/object` 任意物件注入攻擊。
- `verify_link_attributes` 函數（`link_attr_verifier.py`）可接受任意 URL，
  不只是目前自有平台。

## Outstanding Questions

### Resolve Before Planning

- [影響 R4][User 決策] catalog 掃描 path 是 `catalog/` 子目錄（程式碼旁）
  還是 `~/.config/backlink-publisher/catalog/`（用戶可自行新增）？
  建議：程式碼內建 catalog + 用戶 override 目錄（類似 config.toml 機制），
  但需確認用戶是否同意。

### Deferred to Planning

- [影響 R3][Technical] `ConfigDrivenAdapter` 是 `Publisher` subclass 或 factory function？
  須看既有 adapter base contract（`base.py`）再決定。
- [影響 R7][Technical] 原子寫入 catalog YAML 需確認是否用既有 `safe_write.atomic_write`
  或直接 `tmp-rename`。
- [影響 R11][Needs research] WebUI publish 端點目前的 tier 過濾支援——確認是前端傳
  `tier=1` 給後端 `POST /publish`，還是新開一個端點。

## Next Steps

→ 先回答「catalog 路徑」問題，再 `/ce:plan`。
