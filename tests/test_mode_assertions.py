"""Meta-test for the _mode_assertions helper (Plan 2026-07-07-005 Unit 5).

Verifies the helper's POSIX branch still enforces the exact mode (so it
cannot silently weaken CI's real Linux coverage) and its win32 branch is a
existence-only soft-check, not a false green on a missing file.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

import pytest

from _mode_assertions import assert_file_mode


def _fake_stat_result(mode: int):
    import os

    return os.stat_result((0o100000 | mode, 0, 0, 1, 0, 0, 0, 0, 0, 0))


def test_posix_branch_passes_on_matching_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real chmod semantics differ across platforms -- fake the stat result
    rather than relying on the host OS to actually apply 0o600, since this
    test must exercise POSIX-branch logic even when run on Windows."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(Path, "stat", lambda self: _fake_stat_result(0o600))
    target = tmp_path / "secret.json"
    target.write_text("{}", encoding="utf-8")

    assert_file_mode(target, 0o600)  # must not raise


def test_posix_branch_still_fails_loudly_on_wrong_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper must not weaken real POSIX/CI enforcement."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(Path, "stat", lambda self: _fake_stat_result(0o644))
    target = tmp_path / "secret.json"
    target.write_text("{}", encoding="utf-8")

    with pytest.raises(AssertionError, match="0o644"):
        assert_file_mode(target, 0o600)


def test_win32_branch_soft_passes_regardless_of_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    target = tmp_path / "secret.json"
    target.write_text("{}", encoding="utf-8")

    assert_file_mode(target, 0o600)  # must not raise -- mode bits are unrepresentable here


def test_win32_branch_still_fails_on_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    missing = tmp_path / "does-not-exist.json"

    with pytest.raises(AssertionError, match="does not exist"):
        assert_file_mode(missing, 0o600)
