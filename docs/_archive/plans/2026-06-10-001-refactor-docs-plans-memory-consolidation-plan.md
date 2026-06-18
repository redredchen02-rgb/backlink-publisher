---
title: "refactor: docs / plans / memory 全面整並計劃"
type: refactor
status: completed
date: 2026-06-10
origin: workspace-root 全面掃描
claims: {}
---

# docs / plans / memory 全面整並計劃

> 將 workspace 根目錄（git 之外）和 canonical repo 內雙層歸檔的文檔碎片統一收編，
> 消除冗餘，建立文檔健康檢查防止再碎片化。

---

## 現狀全景

### Level 1 — Workspace 根目錄（不在 git 中，不可追溯）

| 文件/目錄 | 數量 | 說明 |
|---|---|---|
| 根 `CLAUDE.md` | 1 | 104 行，與 repo 內 `CLAUDE.md` 部分重疊 |
| 根 `AGENTS.md` | 1 | 33 行，navigation-only — 正常 |
| 根 `docs/brainstorms/` | 3 文件 | 批次優化 + 持續優化 requirements + 審查 JSON |
| 根 `docs/plans/` | 3 文件 | 批次優化計劃 + 持續優化計劃 + 全面升級計劃（共 **1733 行**）|
| 根 `plans/` | 0 | 空目錄 |

**問題**：這 6 個文檔放在 git 外面，無法享受 versioning、plan-claims gate、plan-check。`plan-check` 找不到它們，`plan-claims-gate` 也管不到。它們的 `status: active` 聲明在 repo 內無法被驗證。

### Level 2 — Canonical Repo（雙層歸檔碎片）

| 目錄 | 文件數 | 說明 |
|---|---|---|
| `docs/plans/` | **1** | 唯一活躍計劃（v0.40 operator autonomy） |
| `docs/plans-archive/` | **23** | 2026-06-04~06-08 歸檔 |
| `docs/_archive/plans/` | **~120+** | 2026-05-11~06-04 歷史 |
| `docs/_archive/brainstorms/` | **~55+** | 歷史頭腦風暴 |
| `docs/_archive/ideation/` | **~12** | 歷史構思 |

**問題**：
- `plans-archive/` 和 `_archive/plans/` 功能相同但分兩層 —— 新增歸檔時有人放到前者、有人放到後者，沒有統一規則
- 根目錄 `docs/brainsstorms/` 的 `2026-06-02-batch-optimization-requirements.md.review.json` 是 6-reviewer 審查的合成記錄，屬於 repo 外的平行產物

### 文檔重疊分析

根目錄的 3 個計劃與 repo 內現有文檔存在明顯內容重疊：

| 根目錄文檔 | 重疊對象 | 重疊程度 |
|---|---|---|
| `docs/plans/全面升级优化计划-2026-06-02.md`（675 行） | `backlink-publisher/docs/plans-archive/2026-06-05-099-optimization-analysis-plan.md`（318 行） | **高**：兩份都是「全面優化分析」，後者是前者的精煉版 |
| `docs/plans/2026-06-02-001-feat-batch-optimization-plan.md`（482 行） | 無直接對應 | 可能來自平行會話，與 repo 現有 batch/campaign 功能無直接衝突 |
| `docs/plans/2026-06-05-001-feat-continuous-optimization-plan.md`（576 行） | 部分對應 `plans-archive/` 中的 optimization 計劃 | 其 design (rules engine + adaptive weights) 已被 `weights` CLI 實現 |

---

## Phase 1：根目錄文檔收編（第一優先）

將 git 外面的文檔拉回 canonical repo，恢復可追溯性。

### 1.1 根目錄 `docs/brainstorms/` → repo `docs/_archive/brainstorms/`

| 來源 | 目標 | 理由 |
|---|---|---|
| `docs/brainstorms/2026-06-02-batch-optimization-requirements.md` | `backlink-publisher/docs/_archive/brainstorms/` | 批次優化需求 → 已歸檔（對應 plan 沒有實現的 claims 記錄） |
| `docs/brainstorms/2026-06-02-batch-optimization-requirements.md.review.json` | **不保留** | 6-reviewer 審查合成，屬於 session artifact，非持久文檔 |
| `docs/brainstorms/2026-06-05-backlink-continuous-optimization-requirements.md` | `backlink-publisher/docs/_archive/brainstorms/` | 持續優化需求 → 已歸檔 |

操作：`git mv` 方式複製到 repo 內，然後刪除根目錄來源。

### 1.2 根目錄 `docs/plans/` → 重新定位

三個計劃各自命運不同：

#### Plan A：`全面升级优化计划-2026-06-02.md` 

**判定：不保留獨立副本。** 其內容與 `backlink-publisher/docs/plans-archive/2026-06-05-099-optimization-analysis-plan.md` 高度重疊，後者是前者的精煉版且已歸檔在 repo 內。

操作：
- 將原文件歸檔至 `backlink-publisher/docs/_archive/plans/`（保留歷史記錄）
- 在其 frontmatter 中加入 `status: superseded by plans-archive/2026-06-05-099-optimization-analysis-plan.md`

#### Plan B：`2026-06-02-001-feat-batch-optimization-plan.md`

**判定：歸檔需要 review。** 這份計劃（482 行，6 units）設計了完整的 batch/campaign 系統（CampaignStore、CampaignWorker、multi-seed spray 等），但 repo 內現有代碼的 batch 功能實現路徑可能不同。

操作：
- 複製到 `backlink-publisher/docs/_archive/plans/` 
- 在 frontmatter 中加入 `status: parked (awaiting convergence review against existing batch implementation)`

#### Plan C：`2026-06-05-001-feat-continuous-optimization-plan.md`

**判定：歸檔。** 其設計的 rules engine / adaptive weights 已被 `weights` CLI 覆蓋。

操作：
- 複製到 `backlink-publisher/docs/_archive/plans/`
- frontmatter 標記為 `status: parked (superseded by weights CLI subsystem)`

### 1.3 根目錄 `CLAUDE.md` 去重

**現狀**：根目錄 `CLAUDE.md`（104 行）和 `backlink-publisher/CLAUDE.md`（107 行）約 70% 內容重疊。

**操作**：
1. 保留根目錄 `CLAUDE.md` 的 workspace navigation 部分（前 15 行）
2. 移除與 repo 內 `CLAUDE.md` 重疊的部分（pip install / pytest / SLOC budget 等開發指令）
3. 在根目錄 `CLAUDE.md` 末尾加上「完整指引見 `backlink-publisher/CLAUDE.md`」
4. 根目錄 `AGENTS.md` 保持不變（它本身就是 navigation-only）

**合併後根目錄 `CLAUDE.md` 目標行數**：~20-25 行

### 1.4 Phase 1 驗收條件

```bash
# 確認根目錄 docs/ 已清空
ls -la docs/plans/ docs/brainstorms/ plans/
# → 應顯示「No such file or directory」或空目錄

# 確認文件已到達 repo 內
ls backlink-publisher/docs/_archive/plans/2026-06-02-*
ls backlink-publisher/docs/_archive/plans/2026-06-05-*
ls backlink-publisher/docs/_archive/brainstorms/2026-06-02-*
ls backlink-publisher/docs/_archive/brainstorms/2026-06-05-*

# 確認根目錄 CLAUDE.md 已精簡
wc -l CLAUDE.md
# → 應 ≤ 30 行
```

---

## Phase 2：Plans 歸檔層次統一化

**目標**：從雙層歸檔變成單層，清除「新歸檔放哪裡」的模糊性。

### 2.1 遷移 `plans-archive/` → `_archive/plans/`

| 步驟 | 操作 | 注意 |
|---|---|---|
| 2.1.1 | 將 `docs/plans-archive/` 全部 23 個文件複製到 `docs/_archive/plans/` | 保留原文件名不變 |
| 2.1.2 | 更新每個文件的 frontmatter，確認 `status:` 在 canonical set 內 | `active` / `completed` / `shipped` / `parked` |
| 2.1.3 | 為缺少 `claims:` 區塊的 post-cutoff 文件補充 | 按照 plan-claims contract |
| 2.1.4 | 更新 `plans-archive/` 的 README 為「此目錄已棄用，請見 `_archive/plans/`」 | |
| 2.1.5 | 從 `plans-archive/` 本地刪除（保留 git 歷史） | |

**驗證**：
```bash
# 確認所有文件都已遷移
diff <(ls backlink-publisher/docs/plans-archive/ | sort) <(ls backlink-publisher/docs/_archive/plans/ | sort) | head -20
# 在 plans-archive/ 中只留下 README
ls backlink-publisher/docs/plans-archive/
# → 只有 README.md
```

### 2.2 不活躍 plans 狀態統一

掃描 `_archive/plans/` 中 status 不是 `completed`/`shipped`/`parked` 的文件，統一修正：

```bash
python3 -c "
import re, pathlib
canon = {'active','completed','shipped','parked'}
for p in sorted(pathlib.Path('backlink-publisher/docs/_archive/plans').glob('*.md')):
    m = re.search(r'^status:\s*(\S+)', p.read_text(), re.MULTILINE)
    tok = m.group(1) if m else ''
    if tok not in canon:
        print(f'OFF-CANON  {p.name}: {tok!r}')
    elif tok == 'active':
        print(f'ACTIVE-IN-ARCHIVE  {p.name}')
"
```

### 2.3 活躍 plans 清理

`docs/plans/` 應只包含真正活躍的計劃。確認只剩 `2026-06-09-001-feat-v040-operator-autonomy-plan.md`。

---

## Phase 3：Brainstorms + Ideation 清理

### 3.1 Archive brainstorms 狀態標記

掃描 `_archive/brainstorms/` 的 ~55 個文件：

- 多數應標記為 `status: completed`（對應的 plan 已完成）
- 少數未實現的 → `status: parked`
- 與已刪除/退役平台相關的 → `status: parked (platform retired)`

### 3.2 Ideation 清理

`_archive/ideation/` 的 ~12 個文件多為低承諾文檔：
- 不需要 frontmatter 狀態更新（ideation 自然過期）
- 確認無敏感內容（operator domain names）後保持歸檔

### 3.3 活躍 brainstorm 確認

`docs/brainstorms/2026-06-09-v040-operator-autonomy-requirements.md`：
- 是對應 `docs/plans/2026-06-09-001-*` 的 requirements doc，關聯正確，不需要移動

---

## Phase 4：記憶層精簡（CLAUDE.md + AGENTS.md）

### 4.1 根目錄 `CLAUDE.md` 精簡

將根目錄 `CLAUDE.md` 從 104 行縮減到 ~25 行，保留：
1. Workspace shape 說明（行 5-13）— 「此目錄不是 git repo」
2. Golden rule 提示（行 9）— 「edit backlink-publisher/, not bp-*/」
3. 指向 canonical AGENTS.md + CLAUDE.md 的指針

移除全部與 repo 內 `CLAUDE.md` 重疊的開發指令、架構說明、frontend conventions。

目標內容：

```markdown
# CLAUDE.md

此目錄**不是** git repo。canonical git repo 是 `backlink-publisher/`。
Sibling `bp-<topic>/` 目錄是 `git worktree` checkout。

**黃金規則**：編輯 `backlink-publisher/`，不是 `bp-*/`。

開發指令、架構說明、adapter 擴展、complexity budget、frontend conventions：
→ 見 `backlink-publisher/CLAUDE.md`
→ 完整貢獻者指引見 `backlink-publisher/AGENTS.md`

根目錄 `AGENTS.md` 是 navigation-only。
```

### 4.2 Canonical `CLAUDE.md` 確認

`backlink-publisher/CLAUDE.md`（107 行）已有清晰架構：
- Commands section（行 8-34）
- Pipeline architecture（行 38-45）
- Adapter registry（行 47-49）
- Import paths（行 51-63）
- WebUI layout + anti-rot（行 65-81）
- Complexity budgets（行 83-89）
- Config & secrets（行 91-95）
- Plan governance（行 97-103）
- Bugfix discipline（行 105-107）

**不需要修改**。

### 4.3 根目錄 `AGENTS.md` 確認

根目錄 `AGENTS.md`（33 行）已經是 navigation-only，不需要修改。

---

## Phase 5：文檔健康檢查（防再碎片化）

### 5.1 CI 文檔健康檢查

在 `.github/workflows/ci.yml` 中加入檢查步驟：

```yaml
- name: 文檔健康檢查
  run: |
    # 根目錄不允許有 docs/plans/ 或 docs/brainstorms/
    test ! -d docs/plans || { echo "ERROR: 根目錄 docs/plans/ 不應存在"; exit 1; }
    test ! -d docs/brainstorms || { echo "ERROR: 根目錄 docs/brainstorms/ 不應存在"; exit 1; }
    # plans-archive/ 只允許 README
    test "$(ls -A backlink-publisher/docs/plans-archive/ 2>/dev/null | grep -v README | head -1)" = "" || { echo "ERROR: plans-archive/ 不應包含非 README 文件"; exit 1; }
```

### 5.2 `tests/test_docs_homeomorphism.py`（可選）

如果偏好 pytest 而非 shell script，可以寫一個測試：

```python
"""防止文檔碎片化的測試門禁。"""

import os
import pathlib

WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parents[2]  # 到 workspace root


def test_no_root_level_plans():
    """根目錄 docs/plans/ 不應存在（文檔應在 canonical repo 內）。"""
    assert not (WORKSPACE_ROOT / "docs" / "plans").exists(), \
        "根目錄 docs/plans/ 存在！文檔應在 backlink-publisher/docs/ 內。"


def test_no_root_level_brainstorms():
    """根目錄 docs/brainstorms/ 不應存在。"""
    assert not (WORKSPACE_ROOT / "docs" / "brainstorms").exists(), \
        "根目錄 docs/brainstorms/ 存在！文檔應在 backlink-publisher/docs/ 內。"


def test_plans_archive_only_readme():
    """plans-archive/ 應只包含 README。"""
    archive = WORKSPACE_ROOT / "backlink-publisher" / "docs" / "plans-archive"
    if archive.exists():
        files = [f for f in archive.iterdir()
                 if f.is_file() and f.name != "README.md" and not f.name.startswith(".")]
        assert not files, \
            f"plans-archive/ 包含非 README 文件: {[f.name for f in files]}"
```

---

## Phase 時間線與依賴

| Phase | 名稱 | 依賴 | 規模 | 風險 |
|---|---|---|---|---|
| **Phase 1** | 根目錄收編 | 無 | M | 低 — 純移動操作 |
| **Phase 2** | Plans 歸檔統一 | Phase 1（避免混淆） | M | 中 — 需確認 ~23 個文件的 frontmatter |
| **Phase 3** | Brainstorms 清理 | 無 | L | 中 — 需 review 55+ 文件 |
| **Phase 4** | 記憶層精簡 | 無 | S | 低 — CLAUDE.md 去重 |
| **Phase 5** | CI 門禁 | Phase 1（確保路徑正確） | S | 低 — 新增 CI step |

**建議執行順序**：
1. Phase 1（根目錄收編）— 立即，清除最大的碎片
2. Phase 4（記憶層精簡）— 可並行於 Phase 1
3. Phase 2（歸檔統一）— 較大工作，建議在 Phase 1 完成後
4. Phase 3（Brainstorms 清理）— review-heavy，可慢做
5. Phase 5（CI 門禁）— 最後做，確保前面不會再發生

---

## 不做清單

| 不做 | 理由 |
|---|---|
| 重寫根目錄計劃的 frontmatter 使其符合 plan-claims | 它們不屬於活躍計劃，歸檔即可 |
| 刪除根目錄 `AGENTS.md` 的 `docs/plans/` 引用 | 等 Phase 1 完成後再更新即可 |
| 一次式大規模 git mv | 每個階段分開 PR，方便 review 和 revert |
| 整理 `docs/solutions/`、`docs/runbooks/`、`docs/architecture/` | 這些目錄現狀清晰，不需要整並 |