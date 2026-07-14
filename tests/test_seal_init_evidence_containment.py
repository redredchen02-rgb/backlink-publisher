"""Regression: phase0-seal --evidence-log containment must reject sibling dirs.

Audit finding [29]: the relative-path branch of ``_build_manual_verdict_ref``
guarded repo-containment with ``str(full).startswith(str(repo_resolved))``,
which is a string-prefix test, not a directory-containment test. A sibling
directory whose name shares the repo basename as a prefix (e.g. ``repo`` vs
``repo-evil``) passes ``startswith`` and escapes the repo root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backlink_publisher.cli import _seal_init


def test_evidence_log_in_sibling_prefixed_dir_is_rejected(tmp_path: Path) -> None:
    # repo root and an adjacent dir that shares the repo's basename as a string prefix.
    repo = tmp_path / "repo"
    repo.mkdir()
    sibling = tmp_path / "repo-evil"
    sibling.mkdir()
    evidence = sibling / "notes.md"
    evidence.write_text("secret", encoding="utf-8")

    # ../repo-evil/notes.md resolves to a directory OUTSIDE the repo whose absolute
    # path is a string prefix-match of the repo root. Containment must still reject it.
    with pytest.raises(_seal_init._InitError) as excinfo:
        _seal_init._build_manual_verdict_ref("../repo-evil/notes.md", repo_root=repo)

    assert "resolves outside the repo" in str(excinfo.value)
    assert excinfo.value.exit_code == _seal_init.EXIT_WORKTREE
