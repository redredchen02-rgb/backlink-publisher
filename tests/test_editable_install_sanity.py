"""Meta-test for the editable-install sanity guard (Plan 2026-07-07-005 Unit 1).

The shared .venv's editable install of backlink-publisher can end up pointing
at a worktree that no longer exists. pytest's own `pythonpath = [".", "src"]`
config masks this for in-process tests, so the only symptom was ~20+
unrelated-looking `ModuleNotFoundError` failures in tests that shell out to a
fresh interpreter. This test exercises the resolver in isolation and confirms
it distinguishes a correctly-rooted install from a misrooted one.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

# Import helpers from conftest (tests/ is not a package — from conftest import)
from conftest import _EXPECTED_PACKAGE_ROOT, _editable_install_root
import backlink_publisher


def test_current_install_resolves_inside_repo() -> None:
    """The real, currently-installed package must resolve under backlink-publisher/src."""
    found_root = _editable_install_root(backlink_publisher.__file__)
    assert found_root == _EXPECTED_PACKAGE_ROOT, (
        f"editable install points outside this repo ({found_root}) — "
        f"expected {_EXPECTED_PACKAGE_ROOT}. Run `pip install -e .` from "
        f"backlink-publisher/ to repoint it."
    )


def test_resolver_detects_a_mismatched_root(tmp_path: Path) -> None:
    """A __file__ from a deliberately different tree must not match the expected root."""
    fake_package_file = tmp_path / "some-other-worktree" / "src" / "backlink_publisher" / "__init__.py"
    fake_package_file.parent.mkdir(parents=True)
    fake_package_file.write_text("", encoding="utf-8")

    found_root = _editable_install_root(str(fake_package_file))

    assert found_root != _EXPECTED_PACKAGE_ROOT
