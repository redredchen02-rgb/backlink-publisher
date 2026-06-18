---
date: 2026-06-11
topic: bp-cli-overview
---

# bp — CLI Overview Command

## Problem Frame

backlink-publisher 擁有 40+ 個獨立 CLI 命令，以扁平 argparse 架構分佈。新貢獻者或回頭操作者面對這組命令時沒有任何入口導引——需要翻閱 54KB 的 AGENTS.md 或靠記憶才能找到正確命令。沒有分組、沒有工作流視角、沒有一眼可見的「從這裡開始」。

這造成的直接後果是：操作者在調試或啟動新工作流時，會先跑去文件而非直接問 CLI，降低執行效率。

## Requirements

**Overview Display**
- R1. 新增 `bp` CLI 命令（加入 `[project.scripts]`），執行後以分組方式顯示全部 40+ 命令
- R2. `bp` 與 `bp --help` 行為相同，都觸發分組總覽
- R3. 分組採用以下六個工作流階段標籤：

  | 分組 | 包含命令（代表性列舉） |
  |---|---|
  | Pipeline（核心流程） | plan-backlinks, validate-backlinks, publish-backlinks, recheck-backlinks, dispatch-backlinks, spray-backlinks |
  | Channel（渠道管理） | bind-channel, velog-login, medium-login, frw-login, cull-channels, keepalive-run, keepalive-status, keepalive-reset-exhausted |
  | Analysis（策略分析） | plan-gap, pr-opportunities, weights, equity-ledger, report-anchors, footprint, click-track |
  | Diagnostics（診斷） | gate-probe, platform-health, health-check, audit-state, preflight-targets, canary-targets, canary-seed, channel-scorecard, phase0-seal, plan-check |
  | State（狀態管理） | backup-state, restore-state |
  | WebUI | pipeline-orchestrator |

- R4. 每個命令條目顯示：命令名稱 + 一行簡短描述（靜態維護於 `bp.py`）
- R5. 末尾顯示提示行：`Run any command with --help for details.`

**Maintenance Contract**
- R6. 分組表靜態定義在 `src/backlink_publisher/cli/bp.py`，不動態 import 其他模組
- R7. 新增 CLI 命令時，貢獻者需同步更新 `bp.py` 分組表；AGENTS.md 加入此規則說明

**Output Format**
- R8. 輸出格式為純文字，對齊命令名與描述（左欄固定寬度）
- R9. 不依賴 Rich 或任何外部顯示庫（stdlib only，保持零額外依賴）

## Success Criteria

- 新貢獻者執行 `bp` 後，可在 10 秒內找到所需命令，無需查閱 AGENTS.md
- `bp` 啟動延遲 < 100ms（不 import 其他 CLI 模組）
- 現有 40+ 命令的名稱與行為不受任何影響

## Scope Boundaries

- **不包含**：`bp <cmd>` 作為命令別名或轉發入口（方案 B 的層級式調度器）
- **不包含**：Shell 補全（argcomplete），這是獨立優化點
- **不包含**：搜尋/過濾功能（如 `bp --grep login`），留待後續評估
- **不包含**：動態從 argparse description 讀取命令描述
- **不包含**：WebUI 改動

## Key Decisions

- **靜態表 vs 動態讀取**：選靜態，理由是啟動快（無模組 import 開銷）、分組由人工決定更合理（argparse description 不總是適合作為摘要）。代價是新增命令時需手動同步，接受這個維護成本。
- **不重構現有命令名**：保留所有現有命令名不變，bp 是純加法，無遷移成本。

## Dependencies / Assumptions

- pyproject.toml `[project.scripts]` 新增 `bp` 條目
- 需在 AGENTS.md「Adapter Recipe」或「Dev Commands」區塊加入維護說明

## Outstanding Questions

### Deferred to Planning

- [Affects R3][Technical] 現有 40 個命令的完整清單與最終分組歸屬，需從 pyproject.toml `[project.scripts]` 提取並逐一確認
- [Affects R8][Technical] 命令名稱最長為幾個字元（決定左欄寬度），需掃描確認

## Next Steps

→ `/ce:plan` for structured implementation planning
