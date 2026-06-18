---
title: "feat: Add bp CLI overview command"
type: feat
status: completed
date: 2026-06-11
origin: docs/brainstorms/2026-06-11-001-bp-cli-overview-requirements.md
---

# feat: Add bp CLI Overview Command

## Overview

新增 `bp` 命令作為 backlink-publisher 的統一 CLI 入口頁面。執行後按工作流分組顯示全部 41 個命令和一行描述，stdlib only，不動態 import 其他 CLI 模組，並加入 CI 測試確保靜態分組表不漂移。

## Problem Frame

backlink-publisher 有 41 個已登記的 CLI 命令（`pyproject.toml [project.scripts]`），以扁平 argparse 架構分佈，無任何統一發現入口。新貢獻者或回頭操作者需翻閱 54KB 的 AGENTS.md 才能找到正確命令。`bp` 是純加法——不重構現有命令名，不需遷移。

（see origin: `docs/brainstorms/2026-06-11-001-bp-cli-overview-requirements.md`）

## Requirements Trace

- R1. 新增 `bp` CLI 命令，執行後以分組方式顯示全部命令
- R2. `bp` 與 `bp --help` / `bp -h` 行為相同
- R3. 分組採六個工作流階段（Pipeline / Channel / Analysis / Diagnostics / State / WebUI）
- R4. 每個命令條目顯示：命令名稱 + 一行簡短描述
- R5. 末尾顯示提示行 `Run any command with --help for details.`
- R6. 分組表靜態定義在 `bp.py`，不動態 import 其他模組
- R7. AGENTS.md 補充維護規則
- R8. 純文字輸出，左欄固定寬度對齊
- R9. stdlib only，零外部依賴
- R10（審查補充）. CI 測試交叉驗證 bp.py 靜態表與 pyproject.toml [project.scripts] 的完整性

**成功標準：**
- 新貢獻者執行 `bp` 後無需查 AGENTS.md 即可識別正確分組
- `bp` 啟動延遲 < 100ms
- 現有 41 個命令名稱與行為不受影響

## Scope Boundaries

- 不包含：`bp <cmd>` 作為別名或轉發入口（方案 B 層級式調度器）
- 不包含：shell 補全（argcomplete）
- 不包含：搜尋/過濾功能
- 不包含：動態從 argparse description 讀取命令描述
- 不包含：WebUI Flask 路由、模板、靜態資源改動

## Context & Research

### Relevant Code and Patterns

- **最接近的先例：** `src/backlink_publisher/cli/keepalive_status.py` — 純讀取顯示命令，`main(argv=None)`，全部 `print()` 輸出，無副作用，可作為 bp.py 的結構範本
- **argparse 注意事項：** 既有 `audit_state.py`、`keepalive_status.py` 均在 `main()` 內部**延遲** `import argparse`（非模組頂層），bp.py 應遵循相同模式
- **meta-test 先例：** `tests/test_cli_python_m_entrypoints.py` — 維護 `_CLI_MODULES` 靜態 dict，手動同步，有明確 comment 說明不動態 import 的原因；新增 bp 後需把 `"bp"` 加入此 dict
- **tomllib 讀取先例：** `tests/test_no_monolith_regrowth.py` — 用 `tomllib.loads(BUDGET_FILE.read_text())` 解析 TOML，CI cross-check test 應仿照此模式讀 `pyproject.toml`
- **孤兒程式碼掃描：** `tests/test_no_orphan_code.py` — scanner 以 pyproject.toml entry points 為 import root；`bp` 在 pyproject.toml 登記後不需手動加入 ALLOWLIST（已確認：scanner 自動排除 pyproject entry points，無需 ALLOWLIST）
- **SLOC 預算：** `monolith_budget.toml` 只監控 >500 SLOC 檔案；bp.py 預估 80-120 行，**不需登記**

### Institutional Learnings

- `docs/solutions/logic-errors/argparse-choices-vs-usage-error-exit-clash-2026-05-20.md`：若 bp 將來要加 `--group` 過濾，不使用 argparse `choices=`，改用 post-parse validation 保持 exit code = 1
- `docs/solutions/logic-errors/python-m-needs-main-module-after-package-split-2026-05-19.md`：新 entrypoint 需更新 `test_cli_python_m_entrypoints.py`，否則 `python -m` 的 --help guard 測試不覆蓋 bp

### External References

無需外部研究。本地模式（keepalive_status、test_no_monolith_regrowth）已充分覆蓋。

## Key Technical Decisions

- **argparse with `add_help=False` + 手動 --help 攔截**：為滿足 R2（`bp` 和 `bp --help` 輸出相同），bp.py 的 parser 用 `add_help=False`，在 main() 最前方檢查 `not argv` 或 `-h/--help` 旗標，直接呼叫 `_print_overview()` 並 `return`。這比完全繞開 argparse 更符合既有模式，也避免 argparse 預設 --help 格式與自訂分組輸出的衝突。（see origin: Key Decisions）
- **靜態 GROUPS 結構**：`bp.py` 頂層定義一個 `GROUPS: list[tuple[str, list[tuple[str, str]]]]` — 外層 tuple 是（分組名, 命令列表），內層 tuple 是（命令名, 描述）。這讓 CI cross-check test 可以直接 `import` 並讀取 GROUPS 的命令名集合，無需文字解析。（see origin: R6）
- **左欄寬度 28**：最長命令名 `keepalive-reset-exhausted` = 24 字元，固定左欄 28（加 4 空格 padding），用 `f"{cmd:<28}{desc}"` 對齊。（planning 解決了 R8 outstanding question）
- **pipeline-orchestrator 歸入 WebUI 分組但加注**：它是 CLI 命令也是 WebUI 後端啟動器；WebUI 分組加括號說明「(launches WebUI backend)」以消除歧義。（決定於 brainstorm 文件審查階段）
- **phase0-seal 歸入 Pipeline 後段**：AGENTS.md pipeline 圖把 phase0-seal 列為 `publish-backlinks` 之後的輸出，語意更接近 Pipeline 後處理而非 Diagnostics。（planning 解決了 review 指出的矛盾）

## Open Questions

### Resolved During Planning

- **完整命令清單**：從 pyproject.toml 確認共 **41 個命令**，所有命令已分配分組（見 Unit 1 的 GROUPS 草稿）
- **左欄寬度**：`keepalive-reset-exhausted` = 24 字元，設為 28（確定）
- **pipeline-orchestrator 分組**：歸 WebUI，加注說明
- **phase0-seal 分組**：歸 Pipeline（後段），移出 Diagnostics
- **backup/restore 入口名**：pyproject 中 value 為 `state_backup:backup_main` / `state_backup:restore_main`，但命令名（key）是 `backup-state` / `restore-state`，cross-check test 只比對 key，無影響

### Resolved During Planning（補充）

- **`test_no_orphan_code.py` scanner 行為**：scanner（`scripts/scan_orphan_code.py` lines 91-103）自動以 pyproject.toml entry points 作為 import root；bp 登記後**不需**加入 ALLOWLIST。

### Deferred to Implementation

- **描述文案最終審查**：41 條描述的品質在實作時由撰寫者審定，建議統一「命令式動詞開頭，≤55 字元」

## High-Level Technical Design

> *以下為意向性設計示意，供審查方向確認，非實作規格。實作代理應以此為背景脈絡，而非逐字複製的代碼。*

```
bp.py 結構示意：

GROUPS = [
    ("Pipeline", [
        ("plan-backlinks",    "Generate article payloads from seed URLs"),
        ("validate-backlinks","Validate planned payloads"),
        ...
    ]),
    ("Channel", [...]),
    ...
]

main(argv=None):
  argv = sys.argv[1:] if argv is None else list(argv)
  if not argv or argv[0] in ("-h", "--help"):
      _print_overview()
      return
  # unknown args → brief error + overview
  _print_overview()
  sys.exit(1)

_print_overview():
  header
  for group_name, cmds in GROUPS:
      print(group_name)
      for cmd, desc in cmds:
          print(f"  {cmd:<28}{desc}")
  footer hint
```

CI 測試交叉驗證流程：

```
test_bp_registry.py

1. 讀 pyproject.toml → tomllib.loads()
2. 提取 [project.scripts] key set（不含即將新增的 "bp" 本身）
3. 從 bp.GROUPS 展開所有命令名 → set
4. assert pyproject_keys == bp_keys（雙向 diff）
```

## Implementation Units

```mermaid
TB
  A["Unit 1: bp.py + GROUPS 分組表\n+ pyproject.toml 登記"] --> B["Unit 2: test_cli_python_m 更新"]
  A --> C["Unit 3: test_bp_registry.py（CI cross-check）"]
  A --> D["Unit 4: AGENTS.md 更新"]
```

---

- [ ] **Unit 1: 建立 bp.py 並登記命令**

**Goal:** 建立 `bp` 命令主體——含完整 41 命令分組表、格式化輸出函式、main() 入口——並在 pyproject.toml 登記。

**Requirements:** R1, R2, R3, R4, R5, R6, R8, R9

**Dependencies:** 無

**Files:**
- Create: `src/backlink_publisher/cli/bp.py`
- Modify: `pyproject.toml`（[project.scripts] 新增 `bp = "backlink_publisher.cli.bp:main"`）

**Approach:**
- `GROUPS` 定義在模組頂層，型別為 `list[tuple[str, list[tuple[str, str]]]]`，供 CI test 直接讀取
- main() 內部延遲 `import sys`（實際上 sys 在標準模組初始化時已載入，但保持與其他 CLI 的 `import argparse` 在函式內的風格一致）
- `add_help=False` 或完全不用 argparse（純 sys.argv 解析），以確保 `bp` 與 `bp --help` 輸出相同
- 左欄寬度固定 28，用 f-string 對齊
- 末尾固定顯示 `Run any command with --help for details.`
- 遵循 `keepalive_status.py` 的結構：`def main(argv: list[str] | None = None) -> None:`，末尾加 `if __name__ == "__main__": main()`

**完整分組表（41 命令）：**

| 分組 | 命令 |
|---|---|
| Pipeline | plan-backlinks, validate-backlinks, publish-backlinks, recheck-backlinks, dispatch-backlinks, spray-backlinks, phase0-seal, report-anchors |
| Channel | bind-channel, velog-login, medium-login, frw-login, cull-channels, keepalive-run, keepalive-status, keepalive-reset-exhausted |
| Analysis | plan-gap, pr-opportunities, weights, equity-ledger, footprint, click-track, generate-backlink-text, canonical-expand, comment, probe-citations |
| Diagnostics | gate-probe, platform-health, health-check, audit-state, preflight-targets, canary-targets, canary-seed, channel-scorecard, plan-check, verify-dofollow, recheck-overlay, debt-report |
| State | backup-state, restore-state |
| WebUI | pipeline-orchestrator |

**Patterns to follow:**
- `src/backlink_publisher/cli/keepalive_status.py`（整體結構）
- `src/backlink_publisher/cli/audit_state.py`（argparse 在 main() 內延遲 import 的模式）

**Test scenarios:**
- Happy path: `main([])` → stdout 包含 6 個分組標題和 41 個命令名
- Happy path: `main(["--help"])` 和 `main(["-h"])` → 輸出與 `main([])` 相同，exit 0
- Happy path: `main([])` → 末尾含 `Run any command with --help for details.`
- Happy path: `main([])` → 最長命令名 `keepalive-reset-exhausted` 的描述正確對齊（命令名與描述之間有空格）
- Edge case: `main(["--unknown"])` → exit 非零（或顯示 overview 後 exit 1）
- Edge case: stdout 輸出不依賴任何 backlink_publisher 外的模組 import（靜態 import 分析）

**Verification:**
- `bp` 安裝後可執行，輸出包含所有 6 個分組標題
- `bp --help` 輸出與 `bp` 相同
- `python -c "import backlink_publisher.cli.bp"` 成功，無副作用

---

- [ ] **Unit 2: 更新 test_cli_python_m_entrypoints.py**

**Goal:** 把 `bp` 加入 `_CLI_ONLY_MODULES` dict，讓現有的 python -m guard 測試覆蓋新命令。

**Requirements:** R1（間接）

**Dependencies:** Unit 1

**Files:**
- Modify: `tests/test_cli_python_m_entrypoints.py`（在 `_CLI_ONLY_MODULES` 或 `_CLI_MODULES` dict 加入 `"bp": "backlink_publisher.cli.bp"`）

**Approach:**
- 確認 `_CLI_ONLY_MODULES` vs `_CLI_MODULES` 的語意差異（前者為純展示型，無資料副作用），`bp` 應歸 `_CLI_ONLY_MODULES`
- 只加一行 dict entry，不改既有測試邏輯

**Patterns to follow:**
- 現有 `_CLI_ONLY_MODULES` 的其他條目（如 keepalive_status）

**Test scenarios:**
- Integration: 既有的 `test_cli_python_m_entrypoints.py` parametrize 測試在加入 bp 後繼續全數通過
- Happy path: `python -m backlink_publisher.cli.bp` 輸出分組總覽，exit 0

**Verification:**
- `pytest tests/test_cli_python_m_entrypoints.py` 全數通過，包含 bp 的 parametrize case

---

- [ ] **Unit 3: 建立 test_bp_registry.py（CI cross-check）**

**Goal:** 新增 CI 測試，讀取 pyproject.toml 的 [project.scripts] key set，與 bp.GROUPS 展開的命令名做雙向差集比對，差集非空則失敗。防止靜態表漂移。

**Requirements:** R10

**Dependencies:** Unit 1

**Files:**
- Create: `tests/test_bp_registry.py`

**Approach:**
- 用 `tomllib` 讀取 pyproject.toml（`Path(__file__).parents[1] / "pyproject.toml"` 路徑計算）
- 從 `[project.scripts]` 提取 key set，再減去 `{"bp"}` 本身（bp 不需要在自己的表裡）
- 從 `backlink_publisher.cli.bp.GROUPS` 展開所有命令名為 set
- `assert pyproject_keys - bp_keys == set(), f"Missing from bp.py: {missing}"`
- `assert bp_keys - pyproject_keys == set(), f"In bp.py but not in pyproject.toml: {extra}"`
- 不 import 任何其他 CLI 模組，只 import `bp`（符合 R6 精神）
- 仿照 `test_no_monolith_regrowth.py` 的 `tomllib.loads(...)` 模式

**Patterns to follow:**
- `tests/test_no_monolith_regrowth.py`（TOML 讀取方式）
- `tests/test_cli_python_m_entrypoints.py`（靜態 dict 比對結構）

**Test scenarios:**
- Happy path: 表格完整時，兩個 assert 都通過
- Error path: 假設在 pyproject 新增一個命令但未更新 bp.py → 第一個 assert 失敗，錯誤訊息明確列出缺漏命令名
- Error path: bp.py 有一個不在 pyproject 中的命令名 → 第二個 assert 失敗

**Verification:**
- `pytest tests/test_bp_registry.py` 通過
- 人工在 bp.py GROUPS 移除一個命令名 → 測試失敗，錯誤訊息可讀

---

- [ ] **Unit 4: 更新 AGENTS.md**

**Goal:** 在 AGENTS.md CLI 表格加入 bp，並在「Adding a new CLI command」或「Dev Commands」區塊加入維護規則。

**Requirements:** R7

**Dependencies:** Unit 1

**Files:**
- Modify: `backlink-publisher/AGENTS.md`（CLI entrypoints 表格 + 維護規則說明）

**Approach:**
- CLI 表格新增一行：`| \`bp\` | \`cli/bp.py\` | Show grouped overview of all CLI commands |`
- 維護規則加在「Adding a new publisher adapter」區塊旁邊，或在「Dev Commands」段落：
  「新增 CLI 命令時，需在 pyproject.toml [project.scripts] 登記的同時，同步更新 bp.py 的 GROUPS 表；test_bp_registry.py 會在 CI 中驗證兩者同步。」

**Test expectation:** none — 純文件編輯，無行為邏輯

**Verification:**
- AGENTS.md 的 CLI 表格能找到 bp 條目
- 維護規則說明可在搜尋「bp.py」或「GROUPS」時找到

## System-Wide Impact

- **Interaction graph:** 無。bp.py 不 import 其他 backlink_publisher 模組，不觸發任何 callback、middleware 或事件
- **Error propagation:** bp 的錯誤（如 unknown args）exit 1 並顯示 overview，不觸及任何狀態或外部服務
- **State lifecycle risks:** 無。純讀取靜態 dict，無資料寫入
- **API surface parity:** 現有 41 個命令的 CLI 介面完全不受影響（bp 是純加法）
- **Integration coverage:** `test_bp_registry.py` 的 tomllib + GROUPS import 是唯一的跨邊界整合點
- **Unchanged invariants:** 所有現有命令名、行為、exit code、stdout/stderr 格式均不變

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `test_no_orphan_code.py` scanner 行為 | ✅ 已確認：scanner 自動排除 pyproject entry points，無需任何 ALLOWLIST 改動 |
| `bp` 命令名與環境中現有系統工具衝突（罕見） | 安裝後用 `which bp` 確認；必要時改名為 `bpub` 或 `bp-overview`（低風險，留作執行時評估） |
| 靜態描述文案品質不一致 | 建議統一格式：命令式動詞開頭，≤55 字元，英文 |
| Unit 3 的 CI test import bp 模組 → 若 bp.py 有非 stdlib 頂層 import 會污染測試 | R6 和 R9 本身約束了這個風險；test 本身也作為驗證 |

## Documentation / Operational Notes

- bp 本身不需要 `monolith_budget.toml` 或 `complexity_budget.toml` 登記（SLOC 遠低於閾值）
- 首次安裝後需重新執行 `pip install -e .` 使 `bp` 命令生效（標準 CLI 登記流程）

## Sources & References

- **Origin document:** [docs/brainstorms/2026-06-11-001-bp-cli-overview-requirements.md](docs/brainstorms/2026-06-11-001-bp-cli-overview-requirements.md)
- Related code: `src/backlink_publisher/cli/keepalive_status.py`（結構範本）
- Related code: `tests/test_cli_python_m_entrypoints.py`（meta-test 先例）
- Related code: `tests/test_no_monolith_regrowth.py`（tomllib 讀取模式）
- Related solution: `docs/solutions/logic-errors/argparse-choices-vs-usage-error-exit-clash-2026-05-20.md`
