"""CI cross-check: bp.py GROUPS must stay in sync with pyproject.toml [project.scripts].

Adding a new CLI command requires updating bp.py at the same time.
This test enforces that contract at CI time.
"""
from __future__ import annotations

__tier__ = "unit"
from pathlib import Path
import tomllib

import pytest

from backlink_publisher.cli.bp import GROUPS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def _pyproject_commands() -> set[str]:
    data = tomllib.loads(_PYPROJECT.read_text())
    scripts: dict[str, str] = data["project"]["scripts"]
    return set(scripts.keys()) - {"bp"}


def _bp_commands() -> set[str]:
    return {cmd for _group, cmds in GROUPS for cmd, _desc in cmds}


def test_bp_groups_cover_all_pyproject_commands() -> None:
    pyproject_keys = _pyproject_commands()
    bp_keys = _bp_commands()
    missing = pyproject_keys - bp_keys
    assert missing == set(), (
        f"Commands in pyproject.toml but missing from bp.py GROUPS: {sorted(missing)}\n"
        f"Update src/backlink_publisher/cli/bp.py to add them."
    )


def test_bp_groups_contain_no_unknown_commands() -> None:
    pyproject_keys = _pyproject_commands()
    bp_keys = _bp_commands()
    extra = bp_keys - pyproject_keys
    assert extra == set(), (
        f"Commands in bp.py GROUPS but not in pyproject.toml [project.scripts]: {sorted(extra)}\n"
        f"Either add them to pyproject.toml or remove from bp.py GROUPS."
    )
