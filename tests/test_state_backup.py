"""Tests for cli.state_backup module."""


__tier__ = "unit"
from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher.cli.state_backup import (
    _backup_db,
    _backup_dir,
    _backup_file,
    _config_dir,
    _find_backups,
    _is_sqlite,
    _STATE_FILES,
    _timestamp,
)


@pytest.fixture
def config_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary config directory."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    with patch("backlink_publisher.cli.state_backup._resolve_config_dir", return_value=cfg_dir):
        yield cfg_dir


@pytest.fixture
def backup_dir(config_dir: Path) -> Path:
    """Create the backup directory."""
    bdir = config_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    return bdir


class TestTimestamp:
    """Tests for _timestamp() function."""

    def test_timestamp_format(self) -> None:
        ts = _timestamp()
        # Format: YYYYMMDD_HHMMSS
        assert len(ts) == 15
        assert ts[8] == "_"
        # Verify numeric parts
        date_part, time_part = ts.split("_")
        assert len(date_part) == 8
        assert len(time_part) == 6
        assert date_part.isdigit()
        assert time_part.isdigit()


class TestIsSqlite:
    """Tests for _is_sqlite() function."""

    def test_is_sqlite_true(self) -> None:
        assert _is_sqlite(Path("events.db")) is True
        assert _is_sqlite(Path("webui.db")) is True

    def test_is_sqlite_false(self) -> None:
        assert _is_sqlite(Path("config.toml")) is False
        assert _is_sqlite(Path("state.json")) is False
        assert _is_sqlite(Path("file.txt")) is False


class TestBackupDb:
    """Tests for _backup_db() function."""

    def test_backup_db_success(self, tmp_path: Path) -> None:
        # Create a source SQLite database
        src_path = tmp_path / "source.db"
        conn = sqlite3.connect(str(src_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO test (value) VALUES ('test_value')")
        conn.commit()
        conn.close()

        # Backup to destination
        dst_path = tmp_path / "dest.db"
        _backup_db(src_path, dst_path)

        # Verify backup
        assert dst_path.exists()
        conn = sqlite3.connect(str(dst_path))
        cursor = conn.execute("SELECT value FROM test WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "test_value"

    def test_backup_db_creates_parent_dirs(self, tmp_path: Path) -> None:
        # Create source database
        src_path = tmp_path / "source.db"
        conn = sqlite3.connect(str(src_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()

        # Backup to nested destination
        dst_path = tmp_path / "nested" / "dir" / "dest.db"
        _backup_db(src_path, dst_path)

        assert dst_path.exists()


class TestBackupFile:
    """Tests for _backup_file() function."""

    def test_backup_file_success(self, tmp_path: Path) -> None:
        src_path = tmp_path / "source.txt"
        src_path.write_text("test content")

        dst_path = tmp_path / "dest.txt"
        _backup_file(src_path, dst_path)

        assert dst_path.exists()
        assert dst_path.read_text() == "test content"

    def test_backup_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        src_path = tmp_path / "source.txt"
        src_path.write_text("test content")

        dst_path = tmp_path / "nested" / "dir" / "dest.txt"
        _backup_file(src_path, dst_path)

        assert dst_path.exists()


class TestFindBackups:
    """Tests for _find_backups() function."""

    def test_find_backups_empty(self, config_dir: Path) -> None:
        backups = _find_backups()
        assert backups == []

    def test_find_backups_sorted(self, backup_dir: Path) -> None:
        # Create some backup directories
        (backup_dir / "backup_20240101_120000").mkdir()
        (backup_dir / "backup_20240102_120000").mkdir()
        (backup_dir / "backup_20240103_120000").mkdir()

        backups = _find_backups()
        assert len(backups) == 3
        # Should be sorted by name, newest first (reverse=True)
        assert backups[0].name == "backup_20240103_120000"
        assert backups[1].name == "backup_20240102_120000"
        assert backups[2].name == "backup_20240101_120000"


class TestBackupMain:
    """Tests for backup_main() function."""

    def test_backup_main_all_files(self, config_dir: Path) -> None:
        # Create some state files - use SQLite for .db files, text for others
        for filename in _STATE_FILES[:3]:  # Create first 3 files
            filepath = config_dir / filename
            if filename.endswith(".db"):
                # Create a valid SQLite database
                conn = sqlite3.connect(str(filepath))
                conn.execute("CREATE TABLE test (id INTEGER)")
                conn.commit()
                conn.close()
            else:
                filepath.write_text("test content")

        with patch("sys.argv", ["backup-state"]):
            with pytest.raises(SystemExit) as exc_info:
                from backlink_publisher.cli.state_backup import backup_main
                backup_main()
            assert exc_info.value.code == 0

        # Verify backup was created
        backups = _find_backups()
        assert len(backups) == 1
        backup_path = backups[0]

        # Verify metadata
        meta_file = backup_path / "backup_meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text())
        assert len(meta["files_backed_up"]) == 3
        assert len(meta["files_missing"]) == len(_STATE_FILES) - 3

    def test_backup_main_no_files(self, config_dir: Path) -> None:
        with patch("sys.argv", ["backup-state"]):
            with pytest.raises(SystemExit) as exc_info:
                from backlink_publisher.cli.state_backup import backup_main
                backup_main()
            assert exc_info.value.code == 0

        # Verify backup was created but with no files
        backups = _find_backups()
        assert len(backups) == 1
        meta_file = backups[0] / "backup_meta.json"
        meta = json.loads(meta_file.read_text())
        assert len(meta["files_backed_up"]) == 0
        assert len(meta["files_missing"]) == len(_STATE_FILES)

    def test_backup_main_nonexistent_config_dir(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent"
        with patch("backlink_publisher.cli.state_backup._resolve_config_dir", return_value=nonexistent):
            with patch("sys.argv", ["backup-state"]):
                with pytest.raises(SystemExit) as exc_info:
                    from backlink_publisher.cli.state_backup import backup_main
                    backup_main()
                assert exc_info.value.code == 0


class TestRestoreMain:
    """Tests for restore_main() function."""

    def test_restore_main_list(self, backup_dir: Path) -> None:
        # Create a backup with metadata
        backup_path = backup_dir / "backup_20240101_120000"
        backup_path.mkdir()
        meta = {
            "timestamp": "20240101_120000",
            "created_utc": "2024-01-01T12:00:00Z",
            "files_backed_up": ["events.db"],
            "files_missing": [],
        }
        (backup_path / "backup_meta.json").write_text(json.dumps(meta))

        with patch("sys.argv", ["restore-state", "--list"]):
            with pytest.raises(SystemExit) as exc_info:
                from backlink_publisher.cli.state_backup import restore_main
                restore_main()
            assert exc_info.value.code == 0

    def test_restore_main_list_empty(self, config_dir: Path) -> None:
        with patch("sys.argv", ["restore-state", "--list"]):
            with pytest.raises(SystemExit) as exc_info:
                from backlink_publisher.cli.state_backup import restore_main
                restore_main()
            assert exc_info.value.code == 0

    def test_restore_main_no_args(self, config_dir: Path) -> None:
        with patch("sys.argv", ["restore-state"]):
            with pytest.raises(SystemExit) as exc_info:
                from backlink_publisher.cli.state_backup import restore_main
                restore_main()
            assert exc_info.value.code == 1

    def test_restore_main_nonexistent_backup(self, backup_dir: Path) -> None:
        with patch("sys.argv", ["restore-state", "nonexistent_backup"]):
            with pytest.raises(SystemExit) as exc_info:
                from backlink_publisher.cli.state_backup import restore_main
                restore_main()
            assert exc_info.value.code == 1
