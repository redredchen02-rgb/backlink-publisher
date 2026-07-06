---
date: 2026-07-01
topic: phase3-signal-integrity-hardening
---

# Phase 3 優化計畫 — 訊號完整性強化修正案（Signal-Integrity Hardening Amendment）

## Problem Frame（問題框架）

這不是一次從零開始的「全面優化前後端」需求。`docs/optimization-history.md` 記錄了 11 個已完成的優化階段，`docs/plans/2026-06-30-001-opt-phase3-post-v050-iteration-plan.md`（以下簡稱「Phase 3 計畫」）已經是一份涵蓋前後端的完整計畫（5 個 sprint、預估 17–23 天，執行現況見下方 Dependencies/Assumptions）。這次的健檢動機是主動性的（沒有單一觸發事故），目的是在繼續依賴這個專案之前，建立「它真的穩」的信心，而不是重工。

掃描發現：Phase 3 計畫的驗收標準幾乎全是**數量指標**（`except Exception:` 計數降到 ≤80、測試檔 SLOC 降到 ≤600、未提交檔案數降到 0）。但 `docs/solutions/` 裡橫跨至少四個層次重複出現的根因模式——**訊號算對了，卻在子系統接縫被靜默丟掉**（DB 沒寫回、不確定的驗證結果被丟棄、WebUI 在部分失敗時仍回傳 `ok:true`）——不會被任何一個數量指標保證修好。一個 `except Exception:` 計數從 133 降到 80，如果降的是「無害」的 53 個、留下的正好是「有害」的 80 個，Phase 3 計畫會 100% 達標，但實際上什麼都沒解決。`docs/audits/2026-05-27-recurring-trap-eradication-audit.md` 自己也坦承有一類坑「無法機械化防護」（shape-only 測試掩護它想防的 bug），目前沒有任何機制在盯這件事。這不是假設性風險：即時 dofollow 連結曾因三重缺口被低估計數一段時間，語言不符的文章也曾因一個永遠回傳 True 的判斷式而「靜默發布了不明時長」才被發現——兩者根因都不是被吞掉的 except，而是資料/邏輯層的靜默遺漏，這也是本文件在 except 分類之外額外要求「訊號往返驗證」（見 R1a）的原因。

本文件不重寫 Phase 3 計畫，而是針對它的驗收標準做精準修正，並補上它自己的 E1/E2 文件整理清單漏掉的項目。

## Requirements（需求）

**接縫模組的靜默失敗分類（修正 Sprint D2）**
- R1. Sprint D2 的 except-Exception 窄化工作，對應到 `docs/solutions/` 研究中點名的接縫層——`ledger/`（含 `gap/`，ARCHITECTURE.md 將兩者並列為「read-side 聚合」，故合稱一層）、`events/projector.py` + `events/reconciler.py`、publish-dispatch 路徑 + `idempotency/store.py`、以及 `webui_app/api/*` 的回應建構——共四層、五個模組（`events/`、`gap/`、`idempotency/store.py`、`ledger/`、`webui_app/api/`）。每一個被觸碰或保留的裸 `except Exception:` 都必須分類為：(a) 確實需要靜默，附一句理由註解 + `debt_registry.toml` 對應條目；或 (b) 改為記錄（log）後往上拋或降級處理。原本「count ≤ 80」的目標保留，但不再是唯一驗收條件——沒有分類就不能算數。**〔2026-07-01 追加〕** 工作區目前已有未提交的機械式窄化，且已經觸及接縫模組：`events/reconciler.py`、`gap/events_gap.py` 被改為 `except (ValueError, TypeError):`，`webui_app/helpers/contexts.py` 被改為 `except (OSError, ValueError):` / `except (OSError, ValueError, KeyError):`——三者都只縮小了型別，沒有理由註解、沒有 log、沒有 `debt_registry.toml` 對應條目。這批未提交變更必須先套用本條規則完成分類，才能 commit；不能原樣提交後才回頭補分類。
- R1a.（新增）除了 except 分類，五個接縫模組各自至少需要一個「訊號往返驗證」測試：直接斷言訊號抵達下一階段的儲存或狀態（例如斷言 DB 欄位真的被更新、ledger 真的記錄了該事件），而非只斷言「沒有拋出例外」或「回傳了某個型別」。理由：dofollow-undercounting、language-matches-always-true 等歷史案例的根因都不是被吞掉的例外，而是資料/邏輯層的靜默遺漏——單靠 except 分類無法防止這類 bug 重演。
- R2. 在 D2 既有的 Batch 1（`events/`、`_util/`、`idempotency/store.py`）裡，上述接縫層模組視為優先子集，排在與接縫模式無關的通用 `_util/` 工具函數窄化之前處理。**〔2026-07-01 追加，同日 doc-review 後修正計數〕** 目前未提交的 `src/backlink_publisher/` 檔案有 15 個（`git status` 即時查證），其中 `events/reconciler.py`、`gap/events_gap.py` 已計入 R1，其餘 13 個（多數在 `cli/`、`cli/spray_backlinks/`、`cli/ops/` 下，另含 `config/tokens.py`、`optimization/rules.py`、`_util/net_safety.py`）尚未逐一確認是否屬於接縫層——規劃階段須先比對這 13 個檔案與 R1 的接縫層定義，屬於接縫層的併入 R1 優先分類，其餘才視為一般 `_util` 窄化。

**WebUI 假成功防護（修正 Sprint B3）**
- R3. Sprint B3 對 6 個新 SPA 頁面（campaign、equityLedger、keepAlive、optimizationStatus、prQueue、survival）的人工錯誤模擬驗收，須新增以下明確檢查：
  - 負面條件：後端部分失敗時，前端收到的回應**不能**呈現為 `ok:true`／成功樣式（即「假綠」不能發生）。
  - 正面條件：部分失敗時，頁面必須顯示明顯、不會自動消失的錯誤指示（橫幅或區塊內訊息），標明是哪個部分失敗；已成功載入的其他資料必須保持顯示，不能整頁改為空白或通用錯誤畫面；失敗的區塊不能靜默 fallback 成該頁面原本合法的「空狀態」文案。
  - 組合情境：至少對一個多資料來源頁面，測試「部分區塊已成功渲染、另一部分才失敗」的情境，確認失敗區塊有獨立的錯誤指示，而不是卡在 loading 或誤顯示為空狀態——不能只靠 Sprint B1 各自獨立的 loading/error/empty 三態稽核來保證這個組合情境。
  - 至少一個自動化前端測試（component/unit）斷言：給定一個部分失敗或格式錯誤的 API 回應，頁面不會渲染成功樣式——讓「不能假 ok:true」和 R5 對後端一樣有 CI 迴歸保護，不是只靠一次性人工測試。

**測試斷言品質（修正 Sprint D1）**
- R4. Sprint D1 拆分大測試檔（`test_webui_three_url.py`、`test_cli_plan_check.py` 等）時，對被搬移、且涉及上述接縫層的斷言，需檢查是否只驗證型別/結構（如 `isinstance(x, list)`）而未驗證內容或數值；發現此類斷言須強化為驗證實際數值。範圍限於本次被搬動的測試，不做全測試套件的窮舉稽核。

**新增迴歸護欄**
- R5. 新增一個機械化檢查（測試或 lint 規則——機制留給規劃階段決定），在接縫層模組（`events/`、`gap/`、`idempotency/`、`ledger/`、`webui_app/api/`）出現新的、未分類的裸 `except Exception:`（沒有理由註解也沒有 debt 條目）時讓 CI 失敗。這是唯一的「新建」項目，呼應 Phase 3 計畫自己「10% 新建能降低未來維護成本的護欄」的方針——防的是下一個靜默失敗，不是只修現有的。

**文件同步缺口（補齊 Sprint E1/E2）**
- R6. Sprint E1 的死文檔歸檔清單目前只列了 3 份根目錄報告，漏了第 4 份 `OPTIMIZATION_PHASE3_REPORT.md`；另外兩支殘留的正則表達式批次改寫腳本 `.fix_webui.py`、`.fix_webui2.py`（用來批次修 mypy 錯誤，從未清理）也應一併歸檔或刪除。
- R7. Sprint E2 目前只同步兩份 `AGENTS.md`，範圍須擴大到 `CLAUDE.md` 與 `webui_app/AGENTS.md`：`CLAUDE.md` 現況完全沒提到 Vue 3 SPA、`frontend/` 或 `BACKLINK_PUBLISHER_SPA` 旗標的存在，而 `ARCHITECTURE.md` 已經正確記載這些；`webui_app/AGENTS.md` 有相同的缺口，且其 Structure 表完全沒列出 `api/` 目錄——即 R1/R5 點名的接縫層之一。三份文件都需要對齊。

**現況重新校準（修正 Sprint A1）**
- R8. Sprint A1 與計畫自己的成功指標表都引用「174 個未提交檔案」，但這是 6/30 當天的快照。截至 2026-07-01 即時查證，工作區只剩 25 個 dirty 檔案（20 修改 + 5 新增），且集中在 `_util/net_safety.py`、`cli/_dedup_gate.py`、`events/reconciler.py`、`gap/events_gap.py`、`webui_app/__init__.py` 等模組，加上 5 個新的 `tests/test_webui_store_pkg/` 測試檔。執行 A1 前必須用當下的 `git status` 重新分類，不能沿用計畫文件裡的舊數字。

**測試訊號可信度（新增，修正 Sprint C1 的 CI 變更）**
- R9. 未提交的 `.github/workflows/ci.yml` 變更為 `pytest` 加上了 `--reruns 2 --reruns-delay 1`（失敗自動重跑兩次），且是套用在整個 `-m "unit"` job 的單一全域 flag。這與本文件的核心關切是同一種風險的新變種：間歇性失敗本身可能就是接縫層 race/silent-drop 的訊號，自動重跑會讓它從 CI 結果中消失而不是被看見。**現況已違反本條**：`test_events_projector_idempotency.py`、`test_webui_equity_ledger_route.py`、`test_ledger_model.py`、`test_dedup_enforce_reconcile.py`、`test_gate_verdicts_ledger.py`、`test_idempotency_backfill.py` 等直接測試接縫層行為的檔案目前都是 `unit` tier，已經被這個全域 flag 涵蓋。套用範圍必須限定為只用於已知受外部/基礎設施雜訊影響的測試，且要有文件化理由；涵蓋接縫層模組行為的測試不得套用自動重跑。**已知阻礙**：全專案目前沒有任何 `pytest.mark.flaky` 或其他逐測試重跑開關的先例，且 CI 命令已有 `--strict-markers`，臨時加 marker 會直接失敗——規劃階段必須先選定具體機制（見 Outstanding Questions）才能讓這條規則真的可執行，不能只加一句「已限定範圍」的理由註解就當作達標。

### 對照表：既有項目 → 本次修正

| Phase 3 既有項目 | 原驗收標準 | 本次修正 |
|---|---|---|
| Sprint D2（except 窄化） | `grep` 計數 ≤ 80 | + 接縫模組逐一分類（R1），加訊號往返驗證（R1a），接縫模組優先處理（R2) |
| Sprint B3（SPA 錯誤處理） | 手動模擬顯示友善錯誤，非白屏 | + 正面規範、組合情境、自動化迴歸測試（R3） |
| Sprint D1（大測試檔拆分） | 最大檔案 SLOC ≤ 600 | + 被搬移的 shape-only 斷言強化為驗證數值（R4） |
| Sprint E1（死文檔歸檔） | 3 份根報告歸檔 | + 第 4 份報告 + 2 支殘留腳本（R6） |
| Sprint E2（AGENTS.md 同步） | 兩份 AGENTS.md 一致 | + `CLAUDE.md` 與 `webui_app/AGENTS.md` 納入同步範圍（R7） |
| Sprint A1（積壓提交） | 174 → 0 | 先以即時 `git status`（現為 25）重新校準（R8） |
| Sprint C1（CI 合規矩陣） | 驗證既有檢查項目齊全 | + 新增的 `--reruns` 套用範圍需限定並附理由，接縫層測試禁用（R9） |
| （新增） | — | 接縫模組靜默失敗迴歸護欄（R5） |

## Success Criteria（成功指標）

- `events/`、`gap/`、`idempotency/store.py`、`ledger/`、`webui_app/api/*`（共五個模組）中每一個被觸碰或保留的裸 `except Exception:`，都能在 PR 描述或程式碼註解中找到明確分類（理由或修正方式）。
- 上述五個模組各自至少有一個訊號往返驗證測試，直接斷言訊號抵達下一階段的儲存或狀態（R1a）。
- 新的迴歸護欄已接入 CI，且能在刻意重新引入一個未分類的接縫模組裸 except 時真的讓檢查失敗（不是裝飾性測試）。
- campaign、equityLedger、keepAlive、optimizationStatus、prQueue、survival 六個 SPA 頁面各自有一筆記錄在案的手動測試結果（含模擬的失敗情境、UI 截圖、實際 API 回應、測試者與日期），證明部分失敗會正確顯示為錯誤而非假成功；且至少一個自動化前端測試涵蓋同樣的斷言。
- Sprint D1 拆分測試檔時被搬移、涉及接縫層的斷言，已檢查並強化 shape-only 斷言為驗證實際數值（R4）。
- `CLAUDE.md`、`webui_app/AGENTS.md` 的 WebUI/架構描述與 `ARCHITECTURE.md` 一致，明確提及雙前端並存現況。
- 4 份根目錄優化報告與 2 支 `.fix_webui*.py` 腳本都已歸檔或刪除。
- Phase 3 計畫自己原有的數量化成功指標（如錯誤計數、SLOC、CI gate 等）在重新校準後依然達成。
- `pytest tests/ -x` 全程維持全過。
- `.github/workflows/ci.yml` 的 `--reruns` 套用範圍有文件化理由，且接縫層模組的測試（見 R9 已知清單）不在套用範圍內。
- 目前未提交的 15 個 `src/backlink_publisher/` 檔案（扣除 R1 已列的 2 個後剩 13 個）已依 R1/R2 完成分類或確認不屬於接縫層，才允許 commit。

## Scope Boundaries（範圍邊界）

- 不新增獨立的 Sprint F，也不打亂 Phase 3 計畫既有的 A→E 執行順序；所有修正都內嵌在既有 sprint 裡執行。
- 不擴大 Phase 3 計畫原本「明確排除」的項目——新 adapter、Python 3.13、APScheduler 4.x、PyPI 發布、完整 E2E 套件、「完整」SPA 遷移收尾，都維持排除。
- 不做全測試套件（613 個測試檔）的窮舉 shape-only 斷言稽核，只涵蓋 Sprint D1 本來就要拆分/搬動的測試。
- 不處理 `STEWARDSHIP.md` 目前所有領域皆為 `[unassigned]` 的治理缺口——這是真實存在的問題，且與本文件要求的判斷（R1 的分類品質是否足夠、R5 護欄設計是否足夠）剛好落在 STEWARDSHIP.md 標記為 unassigned 的「Debt governance」「Invariant hardening」「Observability」領域，代表這些判斷目前只有通用 CODEOWNERS 審查、沒有領域專家把關。這是本文件明確接受的殘留風險，不在本次範圍內解決。
- 不改變 Phase 3 計畫整體 17–23 天的架構性估算，但 R1/R2 的分類前置作業實際上會把部分工作提前到 Sprint A1 完成之前才能 commit，而不只是讓 D1／D2／B3 各自的工時「略增」；D1／D2／B3 本身的工時仍可能因為「分類」比「計數」慢而略增。
- `publishing/adapters/` 是否納入 R1/R1a/R5 範圍，明確留待規劃階段決定（見 Outstanding Questions）——Phase 3 計畫原本以「adapters 確需 broad catch」為由排除，但 `adapter-silent-exceptions-resolution.md` 正是本文件核心佐證文件之一的主角，這個排除是否還站得住腳尚未重新檢視。
- 本文件本身已經從最初的 R1-R8，經過同日兩輪修正成長到 R1-R9 加 R1a——這符合本文件反覆強調的「範圍不該悄悄變大」原則。因此明確記錄：後續若再有新發現，應優先考慮是否該收斂進入規劃階段，而不是無限次修正這份需求文件。

## Key Decisions（關鍵決策）

- **採用既有 Phase 3 計畫作為執行載體，不另寫新計畫**：它已經以高保真度涵蓋約 90% 的前後端優化範圍，重寫會浪費已投入的規劃工作。（使用者確認）
- **以修正既有 sprint 驗收標準的方式整合結構性工作，而非新增 Sprint F 或把它排到最前面**：直接修正 D2 現有的「達標但可能沒解決真問題」風險，且與計畫自身「10% 新建護欄」的方針一致。（使用者從三個方案中選定）
- **把「訊號在接縫被靜默丟棄」視為本專案最主要的重複性根因模式之一**：依據是交叉比對 `docs/solutions/` 中至少 5 份文件（dofollow-undercounting、webui-blocking-subprocess、language-matches-always-true、adapter-silent-exceptions、webui-false-success）。**修正**：這 5 份文件中，至少 language-matches-always-true（判斷式邏輯錯誤，無例外）與 dofollow-undercounting（DB 寫回／排程過濾／欄位傳遞三個邏輯缺口，無例外）的根因並非「例外被吞掉」，而是更廣義的「資料/邏輯層靜默遺漏」——這是新增 R1a（訊號往返驗證）而不只靠 except 分類的原因；R1-R9 的 except-classification 機制本身仍只覆蓋這個更廣模式裡「透過例外處理」的子集。
- **2026-07-01 第二次 session 沿用本文件、不重跑分析**：同一天有人以幾乎相同的措辭再次觸發 brainstorm；比對既有文件與當下 repo 狀態後，確認問題框架與 R1–R8 仍然成立，只有「Phase 3 計畫尚未執行」這個假設過時，予以修正（見 Dependencies/Assumptions）。（使用者確認）
- **在途的未分類 except 窄化與新增的 pytest 自動重跑，都併入 R1/R2/R9 處理，不另開 Sprint 或新文件**：兩者都是本文件已定義風險的具體案例，用既有修正框架涵蓋即可。（使用者從三個處理方式中選定）
- **2026-07-01 doc-review 後：套用全部 safe_auto／gated_auto 修正，以及有明確修法的 manual 發現；真正開放式的判斷題（adapters 是否納入範圍、`--reruns` 的技術替代方案、debt_registry schema 是否擴充、D3/C2/C3/E3 優先順序、R5 的時間預算）改列為 Outstanding Questions，不在本文件內單方面決定**。（使用者指示直接推進到底，交由本文件判斷取捨）

## Dependencies / Assumptions（依賴與假設）

- **〔2026-07-01 更新，取代原假設〕** Phase 3 計畫不是單純的空白 `draft`：截至查證當下，Sprint A（工作區清理）已完成並提交，工作區的未提交檔案數已從計畫文件記載的 174 降到 25（20 修改 + 5 新增），且部分 Sprint C1（CI 設定）、D2（except 窄化）與前端韌性強化（`frontend/src/api/client.ts` 標註「Phase 3+ T3.3」）的工作已經在進行中，尚未 commit。**這個 repo 目前正被至少一個其他 session／工具同時操作，狀態會持續變化**——`/ce-plan` 規劃時必須用當下即時的 `git log`／`git status` 重新核對，不能沿用本文件任何時間點記錄的具體數字或 commit hash 作為最終依據。
- `debt_registry.toml` 中 `largest-test-file-bloat` 條目標記為 `resolved`，但其自身理由欄位承認只調高了 SLOC 上限、檔案從未真的拆開——Sprint D1 實際完成拆分後，該 debt 條目狀態需要一併更正，否則會重演它自己曾經記錄過的「registry 與現實不符」問題（`debt-registry-staleness` 條目）。
- `debt_registry.toml` 目前的 schema（`slug/severity/rationale/discovered/owner/status`）沒有檔案/行號欄位，且 `test_debt_registry_format.py` 會拒絕未知欄位——R1 要求「每個保留的裸 except 對應一個 debt_registry 條目」目前無法機械驗證一對一對應，只能驗證「某個條目存在」。這個結構性限制需要在規劃階段解決（見 Outstanding Questions）。

## Outstanding Questions（未解問題）

### Deferred to Planning
- [Affects R5][Technical] 新迴歸護欄的實作機制——`tests/test_events_r8_gates.py`（AST 掃描特定寫入模組，並自帶 `test_red_path_bare_literal_is_detected` 證明護欄有效的紅色路徑測試）是比 `test_no_monolith_regrowth.py`／`test_no_complexity_regrowth.py`（純粹是 SLOC/CC 數值對預算比較，不是形狀掃描）更接近的先例；三個選項（比照 test_events_r8_gates.py 的 AST 掃描模式、自訂 ruff 規則、或 pre-commit hook）取捨留給規劃階段，但無論選哪個，都必須像 test_events_r8_gates.py 一樣附一個永久的「證明護欄有牙齒」自我測試，不能只做一次性人工示範。
- [Affects R5][Planning] R5 是本文件唯一的「新建」項目，但沒有指定歸屬哪個 sprint 或時間上限——規劃階段需要明確估算 R5 的工時並指定歸屬的 sprint 或獨立時間框，避免它在「零額外工期」的框架下被低估。
- [Affects R9][Technical] `--reruns` 範圍限定的具體機制——逐測試 `pytest.mark.flaky` marker（需先在 `pyproject.toml` 註冊，因為 `--strict-markers` 會擋掉臨時 marker）、拆分 unit job 為兩個 pytest 呼叫（接縫層路徑不套用 reruns）、或 `--only-rerun <regex>` 限定錯誤特徵，三者取捨留給規劃階段；已知必須排除在 reruns 之外的檔案至少包含 `test_events_projector_idempotency.py`、`test_webui_equity_ledger_route.py`、`test_ledger_model.py`、`test_dedup_enforce_reconcile.py`、`test_gate_verdicts_ledger.py`、`test_idempotency_backfill.py`。
- [Affects R1][Needs research] 接縫層裸 `except Exception:` 的確切數量與位置——現有的 ~133 是全專案數字。2026-07-01 已確認 3 個檔案（`events/reconciler.py`、`gap/events_gap.py`、`webui_app/helpers/contexts.py`）在未提交變更中被觸碰但只窄化型別、未分類；R2 點名的其餘 13 個未提交 `src/` 檔案是否也屬於接縫層，尚未逐一確認。
- [Affects R1][Process] 如何防止 R1 的分類淪為「敷衍式合規」（一句籠統理由 + debt_registry stub 就通過所有現有檢查）——具體機制（要求理由引用特定例外型別與呼叫點、禁止理由文字重複、或要求第二審查者對每個「確實需要靜默」的分類簽核）留給規劃階段選擇。
- [Affects R4][Needs research] `test_webui_three_url.py`、`test_cli_plan_check.py` 拆分時會搬動哪些具體斷言、其中多少屬於 shape-only——尚未逐行盤點。
- [Affects Scope][Architectural] `publishing/adapters/` 是否納入 R1/R1a/R5 範圍——`adapters/` 下有 28 個檔案含裸 `except Exception:`（比四層加總的 23 個還多），且是本文件核心佐證文件之一（`adapter-silent-exceptions-resolution.md`）的主角，但 Phase 3 計畫以「adapters 確需 broad catch」為由排除。納入會顯著增加範圍與工期，不納入則本文件無法完整涵蓋自己引用的佐證案例——這個取捨需要使用者在規劃階段明確決定。
- [Affects R9][Consistency] 新發現的 `frontend/src/api/client.ts` 前端 timeout/dedup/retry 韌性強化（標註「Phase 3+ T3.3」）是否也該套用和 R9 對 `--reruns` 一樣的檢視標準——client-side 重試理論上也可能掩蓋失敗或重複的請求，讓 UI 看起來成功。
- [Affects Scope][Prioritization] Sprint A 已完成後，Phase 3 計畫裡與訊號完整性無關的 D3（韓語語料校準）、C2（效能基準 diff gate）、C3（SPA CI build）、E3（健康檢查增強）是否仍應維持原優先順序，或該讓位給本文件新增的分類/測試工作以保護 v0.6 啟動時程——留給規劃階段權衡。

## Next Steps

-> `/ce-plan`（帶入本文件〔2026-07-01 doc-review 修正版〕+ `docs/plans/2026-06-30-001-opt-phase3-post-v050-iteration-plan.md` 作為輸入；規劃時第一步須用即時 `git status`／`git log` 重新盤點當下狀態並依 R1/R2/R9 分類，而非沿用本文件任何時間點記錄的具體數字，再產出合併後的細化執行計畫）
