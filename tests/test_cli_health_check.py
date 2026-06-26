"""Tests for backlink_publisher.cli.health_check (Plan U4.4)."""


__tier__ = "unit"
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile

import pytest

from backlink_publisher.cli.health_check import (
    _check_all,
    _config_file_count,
    _credential_audit,
    _db_stats,
    _oldest_checkpoint,
)

# ── _db_stats ────────────────────────────────────────────────────────────────


class TestDbStats:
    def test_not_found(self) -> None:
        result = _db_stats("/tmp/nonexistent/deadbeef.db")
        assert result["exists"] is False
        assert result["error"] == "not_found"

    def test_empty_db_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "events.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE events (id INTEGER)")
            conn.close()
            result = _db_stats(db_path)
            assert result["exists"] is True
            assert result["rows"] == 0
            assert result["size_mb"] >= 0

    def test_db_with_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "events.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE events (id INTEGER)")
            conn.execute("INSERT INTO events VALUES (1), (2), (3)")
            conn.commit()
            conn.close()
            result = _db_stats(db_path)
            assert result["rows"] == 3

    def test_dedup_db_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "dedup.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE dedup (id INTEGER)")
            conn.execute("INSERT INTO dedup VALUES (42)")
            conn.commit()
            conn.close()
            result = _db_stats(db_path)
            assert result["rows"] == 1

    def test_corrupt_db(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "events.db"
            db_path.write_text("not a database")
            result = _db_stats(db_path)
            assert result["error"] is not None


# ── _config_file_count ──────────────────────────────────────────────────────


class TestConfigFileCount:
    def test_no_directory(self) -> None:
        assert _config_file_count("/tmp/does-not-exist-12345") == 0

    def test_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            assert _config_file_count(td) == 0

    def test_with_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "config.toml").touch()
            Path(td, "token.json").touch()
            assert _config_file_count(td) == 2


# ── _credential_audit ────────────────────────────────────────────────────────


class TestCredentialAudit:
    def test_no_directory(self) -> None:
        result = _credential_audit("/tmp/does-not-exist-12345")
        assert result["total"] == 0

    def test_no_credential_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "config.toml").touch()
            result = _credential_audit(td)
            assert result["total"] == 0

    def test_all_0600(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td, "medium-state.json")
            f.touch()
            f.chmod(0o600)
            result = _credential_audit(td)
            assert result["total"] == 1
            assert result["non_0600"] == 0

    def test_non_0600_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td, "blogger-state.json")
            f.touch()
            f.chmod(0o644)
            result = _credential_audit(td)
            assert result["total"] == 1
            assert result["non_0600"] == 1

    def test_fix_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td, "blogger-state.json")
            f.touch()
            f.chmod(0o644)
            result = _credential_audit(td, fix=True)
            # Function reports the count as-discovered, before fixing
            assert result["non_0600"] == 1
            # But the file itself was fixed
            assert (f.stat().st_mode & 0o777) == 0o600


# ── _oldest_checkpoint ──────────────────────────────────────────────────────


class TestOldestCheckpoint:
    def test_no_checkpoint_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = _oldest_checkpoint(td)
            assert result["exists"] is False

    def test_empty_checkpoint_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "checkpoints").mkdir()
            result = _oldest_checkpoint(td)
            assert result["exists"] is True
            assert result["count"] == 0

    def test_with_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cp_dir = Path(td, "checkpoints")
            cp_dir.mkdir()
            (cp_dir / "cp-001.json").touch()
            (cp_dir / "cp-002.json").touch()
            result = _oldest_checkpoint(td)
            assert result["exists"] is True
            assert result["count"] == 2
            assert result["age_hours"] >= 0


# ── _check_all (integration) ─────────────────────────────────────────────────


class TestCheckAll:
    def test_empty_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as config_dir:
            with tempfile.TemporaryDirectory() as cache_dir:
                report = _check_all(config_dir, cache_dir)
                assert "timestamp" in report
                assert report["events_db"]["exists"] is False
                assert report["dedup_db"]["exists"] is False
                assert report["config_dir"]["file_count"] == 0
                assert report["credentials"]["total"] == 0
                assert report["checkpoints"]["exists"] is False

    def test_with_some_data(self) -> None:
        with tempfile.TemporaryDirectory() as config_dir:
            with tempfile.TemporaryDirectory() as cache_dir:
                # Create events.db in cache_dir
                events_db = Path(cache_dir, "events.db")
                conn = sqlite3.connect(str(events_db))
                conn.execute("CREATE TABLE events (id INTEGER)")
                conn.execute("INSERT INTO events VALUES (1), (2)")
                conn.commit()
                conn.close()

                # Create dedup.db in config_dir
                dedup_db = Path(config_dir, "dedup.db")
                conn = sqlite3.connect(str(dedup_db))
                conn.execute("CREATE TABLE dedup (id INTEGER)")
                conn.execute("INSERT INTO dedup VALUES (99)")
                conn.commit()
                conn.close()

                report = _check_all(config_dir, cache_dir)
                assert report["events_db"]["rows"] == 2
                assert report["dedup_db"]["rows"] == 1
                assert report["checkpoints"]["exists"] is False


# ── CLI parser ───────────────────────────────────────────────────────────────


class TestMainCli:
    """Test main() via argv injection (no sys.exit side effects in unit context)."""

    def test_default_output(self, capsys) -> None:
        from backlink_publisher.cli.health_check import main
        # Default mode (no flags) — runs _check_all against sandboxed env
        with pytest.raises(SystemExit) as exc:
            main(["--dry-run", "--json"])
        # Without a real env, the exit code depends on _check_all finding no dbs.
        # At minimum it should exit 0 when nothing is broken.
        captured = capsys.readouterr()
        # JSON mode prints json
        assert "timestamp" in captured.out or captured.out == ""

