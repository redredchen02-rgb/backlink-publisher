---
date: 2026-06-02
topic: risk-hardening
---

# Risk Hardening: Dependency Constraints, tomli Cleanup, WebUI Rate Limiting

## Problem Frame

稽核發現 4 個原始風險點中有 2 個已解決（憑證權限 ✓、URL 驗證並發 ✓），真實需修復的有 3 項：

1. playwright/requests/beautifulsoup4 無上限版本約束，major 版本升級可能靜默破壞 adapter suite
2. canary/store.py 與 config/loader.py 有 `import tomli` fallback 但 pyproject.toml 未宣告 tomli，Python <3.11 會靜默 ImportError
3. WebUI API 的 publish/plan 等狀態變更端點無速率限制，ALLOW_NETWORK=1 暴露時無防護

## Requirements

**Dependency Constraints**
- R1. pyproject.toml 中 `playwright`、`requests`、`beautifulsoup4` 加入 major 版本上限（分別 `<2`）

**tomli Cleanup**
- R2. 刪除 `canary/store.py` 與 `config/loader.py` 中的 `import tomli as tomllib` fallback，改為直接 `import tomllib`（stdlib，Python ≥3.11）
- R3. 確認不再有任何 `import tomli` 殘留

**WebUI Rate Limiting**
- R4. 新增 `flask-limiter` dependency（`>=3.5,<4`）
- R5. 在 `webui_app/__init__.py` 的 `create_app()` 中初始化 Limiter，預設 60 次/分鐘/IP，適用於所有 POST/PUT/PATCH/DELETE 端點
- R6. 已有自製限速的 URL verify 路由（`/api/url-verify/*`）不加 flask-limiter decorator，避免雙重限速
- R7. GET 端點、靜態資源免速率限制

## Success Criteria
- CI `pytest tests/` 全過（無因 import 變動而 fail）
- `python -m py_compile` 通過所有修改檔案
- WebUI 啟動後對 POST 端點施壓 >60 次/分鐘時收到 429

## Scope Boundaries
- 不修 rentry/http_form_post 的 connection pooling（低流量 adapter，風險可接受，留後續 PR）
- 不升 flask/apscheduler 等已有上限的依賴
- Rate limiter 只用 in-memory storage，無 Redis 依賴

## Key Decisions
- 刪 tomli fallback（非宣告 conditional dep）：CI 在 3.11+3.12 跑，`tomllib` 是 stdlib，無向後相容需求
- flask-limiter `<4`：與現有 flask `<4` 約束對齊，避免依賴跨大版本漂移

## Next Steps
→ 直接執行，無需 `/ce:plan`（所有技術決策已定）
