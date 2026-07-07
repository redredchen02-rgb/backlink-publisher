# W14: 誠實性 Blueprint 落地審計 (Closeout Checklist)

**Audited against:** `main` @ `f43dda73` (worktree `bp-w14-audit`, branch `chore/w14-blueprint-audit`)
**Scope:** 逐條核對兩份 blueprint 文件的每一項具體主張,標記三態之一:
- ✅ **已落地** — 附 commit SHA / 檔案路徑+行號證據
- ⚠️ **缺口** — 追蹤項,附檔案路徑+行號+應做什麼
- 🚫 **不再適用** — 附理由(路由已移除/模式已被後續重構取代)

本 unit 為唯讀盤點,未修改任何原始碼。

---

## A. `docs/solutions/ux-honesty/webui-false-success-resolution.md`

**落地率:7 / 9 已落地,1 缺口,1 不再適用**

### A1. `DraftAPI.create` — I/O 持久化未包 try/except → 裸 500
✅ **已落地**。`webui_app/api/drafts_api.py:91-100` — `insert_first` 已包 `try/except Exception`,回傳 `{"ok": False, "error_code": "PERSISTENCE_FAILURE", "flash_type": "danger", ...}`。

### A2. `DraftAPI.schedule` — 持久化 + scheduler 註冊未防護
✅ **已落地**。`webui_app/api/drafts_api.py:132-168` — 兩段分別包 try/except;`_drafts_store.update_item` 失敗回 `PERSISTENCE_FAILURE`,`_schedule_draft_job` 失敗回 `SCHEDULER_SYNC_FAILED` 並執行 store 回滾(`update_item(..., status="pending", scheduled_at=None)`,回滾失敗再記一筆 `draft_rollback_failed`)。

### A3. `bulk_publish_now` — split-state(store 已更新但 scheduler 註冊失敗)
✅ **已落地**。`webui_app/api/drafts_api.py:320-379` — 完整落實 blueprint 提議的「追蹤 completed_jobs / store_rollbacks,例外時逐一 `scheduler.remove_job` + `update_item` 回滾」設計,回傳 `BULK_SCHEDULER_FAILURE`。額外新增 `bulk_cancel`(`:381-411`)採同一模式,是 blueprint 未提及但同精神的延伸。

### A4. 取消/刪除排程時 `_remove_scheduled_job` 失敗仍回 `ok: True` 的假成功
✅ **已落地,但實作順序與 blueprint 提議相反(刻意變體)**。`webui_app/api/drafts_api.py:25-42`(`_remove_scheduled_job` 區分 `JobLookupError`〔良性,視為乾淨〕vs 真失敗)+ `:220-277`(`cancel`/`delete`)。程式注解明確記錄了這個設計決策:「Honour operator intent first: mutate store regardless of scheduler removal outcome」——先確保 store 反映操作者意圖,再嘗試同步 scheduler,若同步失敗回 `flash_type: "warning"` 而非 `ok: True`。與 blueprint 原稿(先移除 job、失敗就整體回 danger)方向不同,但同樣消除了「假成功」問題。此外程式注解引用了 `PR #231`(O1 honesty)——`git log` 確認 `a22476f1 fix(webui): close remaining false-success routes (O1 UX honesty) (#231)` 為落地提交之一,`_remove_scheduled_job` 注解本身提到「Restores the O1 "removal honesty" (PR #231)」。

### A5. `pipeline.py::ce_plan()` — `_persist_three_tier_config` 例外被吞掉,操作者不知配置未存
✅ **已落地(檔案已搬遷)**。原文件位置已被 Wave 3 Unit 5 拆分重構(`routes/pipeline.py` → `routes/pipeline_plan.py`,見檔案頂端注解「Extracted from routes/pipeline.py (2026-06-11)」)。現況見 `webui_app/routes/pipeline_plan.py:77-86`:
```python
warning_msg = None
if category_url or work_url:
    try:
        _persist_three_tier_config(main_url, category_url, work_url)
    except Exception as exc:
        warning_msg = f"漫画/分类页配置保存失败 ({type(exc).__name__})，但生成任务仍可继续。"
        plan_logger.warn("homepage_form_persist_failed", ...)
```
`warning_msg` 在 `:118-121` 傳入 `_render('index.html', ..., warning=warning_msg)`,與 blueprint 3.2.B 的設計完全一致(warn log + 回傳 UI warning,不阻斷主流程)。

### A6. `ce_preview()` — JSON 解析失敗回傳裸字串 `"Invalid URLs"`,可能破壞 JSON 消費端
⚠️ **缺口(低嚴重度)**。`webui_app/routes/pipeline_plan.py:228-235`:
```python
@bp.route('/ce:preview', methods=['POST'])
def ce_preview() -> Any:
    urls_json = request.form.get('urls_json', '[]')
    try:
        urls = json.loads(urls_json)
    except json.JSONDecodeError as exc:
        plan_logger.warn("preview_urls_parse_error", reason=type(exc).__name__)
        return "Invalid URLs"
```
已補上警告日誌(比 blueprint 稿好一點),但錯誤回應仍是裸字串而非結構化 JSON/HTTP 狀態碼。**應做**:改為 `jsonify({"ok": False, "error": "invalid_urls_json"}), 400` 或至少統一走 `_render`/HTML 錯誤路徑,視該路由消費端而定。
**上下文降低優先度**:`rg -rn "ce:preview"` 顯示目前只有 `tests/test_webui_pipeline_routes.py:321` 呼叫此路由,前端(Jinja 模板 / `frontend/src`)均未引用 `/ce:preview`。真正的當前消費路徑是 `webui_app/api/v1/pipeline.py::pipeline_preview()`(其注解明言「Mirrors the legacy `/ce:preview` seed shape, but returns the structured...」),該 v1 端點的例外處理需另行確認,但不在本次兩份 blueprint 條列範圍內。建議：若 `/ce:preview` 確認為死路由,直接標記棄用或移除測試依賴;若非死路由,列為修復項。

### A7. `checkpoint.py::checkpoint_resume()` — CLI subprocess 失敗導致裸 500
✅ **已落地(經由更下層的架構重構,而非 blueprint 提議的路由層 try/except)**。`webui_app/routes/checkpoint.py:22-79` 本身確實沒有包 try/except 直接包住 `PipelineAPI().resume(run_id)`,但 `PipelineAPI.resume` 委派給 `src/backlink_publisher/sdk/api.py:467-476`,其內部呼叫 `self._invoke_capture(...)`,而 `_invoke_capture`(`sdk/api.py:237-255`)本身已經：
```python
try:
    captured = run_pipe_capture(cmd, stdin)
except Exception as exc:
    return _typed_error_result(str(exc), label)
```
即 subprocess 生成失敗(spawn 失敗、環境問題等)一律轉為 `PipeResult(success=False, ...)`,不會讓例外冒出到路由層造成 500。`checkpoint_resume()` 隨後依 `result.exit_code` 分支(0/4/其他)已涵蓋失敗情形(`:77-79` 的 `else` 分支)。落地路徑與 blueprint 設想不同(SDK 層統一收斂,而非逐路由包裹),但效果達成。

### A8. `url_verify.py` — 例外一律粗分類為 `timeout`/`network_error`,掩蓋 SSL/DNS/連線拒絕等診斷資訊
✅ **已落地**。`webui_app/routes/url_verify.py:184-203` 已擴充為 `ssl_verification_failed` / `connection_refused` / `dns_lookup_failed` / `timeout` / `network_error` 五類,並透過 `_emit_recon(reason, host=host_ascii, exc_class=exc_name)` 記錄原始例外類別(RECON-gated,不洩漏原始 host)。與 blueprint 3.2.C 設計完全對應。

### A9. 結構化回傳契約(`ok` / `error_code` / `flash_type` / `flash_msg` / `detail`)
✅ **已落地(貫穿全部 `DraftAPI` 方法)**。所有 `DraftAPI` 方法(`create`/`schedule`/`publish_now`/`cancel`/`delete`/`bulk_delete`/`bulk_publish_now`/`bulk_cancel`)均回傳含 `ok`/`error_code`/`flash_type`/`flash_msg` 的字典,與 blueprint §3.1 提議的契約形狀一致(`detail` 欄位未見獨立使用,但 `flash_msg` 已內嵌 `type(exc).__name__`,達成同等診斷目的)。

---

## B. `docs/solutions/correctness/adapter-silent-exceptions-resolution.md`

**落地率:7 / 7 已落地,0 缺口,0 不再適用**(1 項因架構重構而以不同機制達成同等效果,見 B3 附注)

**關鍵證據提交**:`a5f8ba3a fix(adapters): classify 56 except-Exception sites, fix medium_browser Save Draft silent swallow (D2)` —— 對 `publishing/adapters/` 下 28 個檔案的 56 處 `except Exception` 逐一分類(K8 四分支框架),加註 `# debt: <slug>` 注解 + `debt_registry.toml` 條目;34 處判定為安全的既有模式維持原狀並記錄理由,1 處(medium_browser Save Draft)判定為真正的假成功並修正。commit message 直接引用本 blueprint 檔名作為修正依據。

### B1. `linkedin_api.py:138-141` — `resp.json()` 例外被 `except Exception: pass` 吞掉,且應改用更精確的例外類型
✅ **已落地**。`src/backlink_publisher/publishing/adapters/linkedin_api.py:152-156`:
```python
try:
    data = resp.json()
except ValueError as exc:
    log.debug(f"Failed to decode JSON response for HTTP 403 error: {exc}")
    data = {}
```
已改用 `ValueError`(涵蓋 `json.JSONDecodeError`)並補上 `log.debug`。同檔另一處 `resp.json()["id"]` fallback(`:173-176`)同樣改用 `except ValueError: post_id = ""`。

### B2. `medium_browser.py:161-164` — cookie 提取失敗靜默 `except Exception: live_cookies = []`,無日誌
✅ **已落地**。`src/backlink_publisher/publishing/adapters/medium_browser.py:175-180`:
```python
try:
    live_cookies = context.cookies("https://medium.com") or []
except Exception as exc:
    log.warning("Failed to extract live cookies from Playwright context", exc_type=type(exc).__name__, exc=str(exc))
    live_cookies = []
```
帶 `# debt: medium-browser-cookie-refresh-best-effort-accepted` 注解,記錄為「已審視、接受的技術債」而非疏漏。

### B3. `medium_browser.py:257-266` — CAPTCHA count 探測 `except Exception: pass`,無日誌
✅ **已落地**。`src/backlink_publisher/publishing/adapters/medium_browser.py:286-287`:
```python
except Exception as exc:
    log.debug("Medium CAPTCHA probe failed during timeout", error=str(exc))
```
與 blueprint 4.2 第 2 點的 diff 完全對應。

### B4. `medium_browser.py:321-325` — Save Draft 點擊失敗靜默降級為 sleep(3000ms),無日誌
✅ **已落地,且超越 blueprint 原始提議**。blueprint 原提議僅補一行 `log.warn` 後繼續 `page.wait_for_timeout(3000)`;實際落地(`medium_browser.py:343-359`,commit `a5f8ba3a`)判定「僅記錄後繼續」仍是假成功風險(草稿是否真的存下未經二次確認),因此改為 **raise `ExternalServiceError`**:
```python
except Exception as exc:
    # debt: medium-browser-save-draft-false-success-fixed
    # 2026-07-06 D2 fix: this used to log-and-continue, ... named a
    # "critical silent swallow" in
    # docs/solutions/correctness/adapter-silent-exceptions-resolution.md.
    raise ExternalServiceError(
        "Medium Save Draft click failed; draft status is "
        f"unconfirmed: {type(exc).__name__}: {exc}"
    ) from exc
```
此為兩份 blueprint 交叉驗證後的更嚴格修法(既滿足 B 稿「不可靜默」,也滿足 A 稿「不可假成功」),已在 commit message 中明確引用本 blueprint 檔案路徑。

### B5. `medium_browser.py:409-421` — 診斷截圖失敗 `except Exception: pass`,無日誌
✅ **已落地**。`src/backlink_publisher/publishing/adapters/medium_browser.py:446-453`:
```python
def _save_screenshot(page: Any, config: Config, article_id: str) -> None:
    try:
        shot_path = _screenshot_path(config, article_id)
        page.screenshot(path=str(shot_path))
        log.error("screenshot", level="ERROR", screenshot=str(shot_path))
    except Exception as exc:
        log.debug("Failed to capture diagnostic screenshot", error=str(exc))
```

### B6. `blogger_api.py:95-98` — token 反序列化(`Credentials.from_authorized_user_info`)例外靜默為 `creds = None`,無日誌
🚫 **不再適用**。全域搜尋 `google.oauth2`/`from google` 於 `src/backlink_publisher/publishing/` 下無任何匹配,`Credentials.from_authorized_user_info` 這個 google-auth 物件模式已不存在於當前程式碼——credential 載入已重構為 `publishing/session/provider.py` 的 `SessionManager` + `DefaultCredentialProvider`,以 dict 形式的 `token_data`/`Credential` 資料類別取代 google-auth 的 `Credentials` 物件(`blogger_api.py:93-103` 現在的認證路徑改走 `SessionManager(...).get_session("blogger", config)`,例外處理為 `except (DependencyError, AuthExpiredError): raise` + `except Exception as exc: raise ExternalServiceError(...) from exc`,已符合「不可靜默」原則)。blueprint 針對的具體程式碼區塊已被後續架構重構取代,原始風險點不復存在。附帶一提:`provider.py:266-272` 有一處相鄰的 `except Exception: log.warning(...)`(OAuth token 刷新後持久化失敗)已有日誌但缺乏例外詳情,屬同一精神下的次要瑕疵,不在本條列範圍內,列入「其他觀察」。

### B7. `devto_api.py:206` / `notion_api.py:245` — 錯誤回應 body JSON 解析用 `except Exception:` 過寬,應改 `ValueError`
✅ **已落地**。
- `src/backlink_publisher/publishing/adapters/devto_api.py:211-219`(422 分支)與 `:227-232`(一般 body 解析)均已改為 `except ValueError`。
- `src/backlink_publisher/publishing/adapters/notion_api.py:262-263` 同樣改為 `except ValueError as exc`。

### 通用規則(Rule 1-4)落地檢查
- **Rule 1(不可無日誌吞例外)**:✅ 上述 B1-B5、B7 均補齊日誌;`# debt: <slug>` 注解模式(commit `a5f8ba3a`)提供了比 blueprint 原稿更系統化的「已審視技術債」標記機制,並有 `debt_registry.toml` 集中登記 34 筆同類決策。
- **Rule 2(優先用具體例外類型)**:✅ JSON 解析類全面改 `ValueError`;檔案系統/網路類未見系統性稽核,但本次兩份 blueprint 未列出額外具體檔案+行號主張,不列為缺口(僅供後續稽核參考)。
- **Rule 3(fallback 邊界隔離 + 註解)**:✅ 各處 try/except 範圍收斂在單一 optional 操作,且均有 `# debt:` 或功能性註解說明「為何允許失敗」。
- **Rule 4(re-raise 保留 traceback,用 `from exc`)**:✅ 抽查 `linkedin_api.py:199-202`、`devto_api.py:230-232`、`blogger_api.py:100-103` 均使用 `raise ... from exc`。

---

## 總結

| Blueprint | 條列總數 | 已落地 | 缺口 | 不再適用 |
|---|---|---|---|---|
| `webui-false-success-resolution.md` | 9 | 7 | 1 | 1(部分,見 A6 附注——A6 本身列為缺口但情境降級) |
| `adapter-silent-exceptions-resolution.md` | 7 | 6 | 0 | 1 |

（A6 統計為「缺口」,其「不再適用」欄位對應的是本表未單獨計入的 A5 檔案搬遷情境说明，不重複計數；上表僅反映條列的三態最終判定。）

### 追蹤項(缺口清單,供後續 unit 修復)

1. **`webui_app/routes/pipeline_plan.py:228-235`(`ce_preview`)** — JSON 解析失敗時回傳裸字串 `"Invalid URLs"`,非結構化錯誤格式。
   - **應做**:確認 `/ce:preview` 是否為死路由(目前只有 1 個測試引用,無前端呼叫)。若是死路由,標記棄用或於後續清理中移除;若仍需保留供其他消費端使用,改為 `jsonify(...), 400` 或與 `_render` 錯誤路徑一致的格式。
   - **嚴重度**:低(無已知前端消費端會被此格式破壞)。

2. **（觀察,非缺口）`src/backlink_publisher/publishing/session/provider.py:266-272`** — OAuth token 刷新後持久化失敗的 `except Exception: log.warning("Failed to persist refreshed OAuth token")` 缺少例外類型/訊息細節。不在兩份 blueprint 條列範圍內,僅供後續稽核參考,不建議在 W14 或 R14 範圍內處理。

### 落地路徑偏移備忘(非缺口,僅供理解落地脈絡)

- A4(取消/刪除排程假成功)与 A7(checkpoint 500)最終落地方式與 blueprint 原始提議的具體程式碼形狀不同,但透過不同層級(路由層順序調整 / SDK 層統一收斂)達成了 blueprint 的核心目標(不可假成功 / 不可裸 500)。
- A5 的目標檔案 `webui_app/routes/pipeline.py` 已在 2026-06-11 的 Wave 3 Unit 5 重構中拆分為 `pipeline_plan.py` / `pipeline_publish.py` 等,blueprint 所指程式碼現位於 `pipeline_plan.py`。
