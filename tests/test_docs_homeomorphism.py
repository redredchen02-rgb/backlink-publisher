"""防止文檔碎片化的測試門禁。

Root-level (workspace root, outside canonical repo) docs/plans/ 和 docs/brainstorms/
不應存在 — 所有文檔應在 canonical repo 內。

plans-archive/ 是已廢棄的歸檔位置，應只包含 README.md。
"""

__tier__ = "unit"

import pathlib

# workspace root = backlink-publisher/tests/ 往上有 2 層
# tests/ → backlink-publisher/ → workspace root
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_WORKSPACE_ROOT = _REPO_ROOT.parent


def test_no_root_level_plans():
    """根目錄 docs/plans/ 不應存在（文檔應在 canonical repo 內）。"""
    forbidden = _WORKSPACE_ROOT / "docs" / "plans"
    assert not forbidden.exists(), (
        f"根目錄 docs/plans/ 仍然存在！"
        f"文檔應放在 {_REPO_ROOT}/docs/ 內。"
    )


def test_no_root_level_brainstorms():
    """根目錄 docs/brainstorms/ 不應存在。"""
    forbidden = _WORKSPACE_ROOT / "docs" / "brainstorms"
    assert not forbidden.exists(), (
        f"根目錄 docs/brainstorms/ 仍然存在！"
        f"文檔應放在 {_REPO_ROOT}/docs/_archive/brainstorms/ 內。"
    )


def test_no_root_level_empty_plans_dir():
    """根目錄 plans/ 不應存在（即使是空的）。"""
    forbidden = _WORKSPACE_ROOT / "plans"
    assert not forbidden.exists(), (
        f"根目錄 plans/ 仍然存在！"
        f"即使為空也不應存在（混淆 agent）。"
    )


def test_plans_archive_only_readme():
    """plans-archive/ 應只包含 README.md 和 .gitkeep 類文件。

    所有歸檔計劃已遷移至 _archive/plans/。
    """
    archive = _REPO_ROOT / "docs" / "plans-archive"
    if not archive.exists():
        return  # 目錄本身不存在視為通過

    allowed = {"README.md"}
    files = [f.name for f in archive.iterdir()
             if f.is_file() and f.name not in allowed and not f.name.startswith(".")]

    assert not files, (
        f"plans-archive/ 包含非 README 文件: {files}"
        f"請將它們遷移至 docs/_archive/plans/。"
    )