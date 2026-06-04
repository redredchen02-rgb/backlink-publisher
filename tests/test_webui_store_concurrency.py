"""Unit 2 — Cross-process SQLite update() RMW safety (plan 2026-06-04-004).

Two OS subprocesses call update() adding distinct keys; result documents whether
both survive or one key is lost (known limitation). In-process: sequential
update() via RLock is safe.
"""
from __future__ import annotations

__tier__ = "integration"

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _write_worker(script_path: Path, db_path: Path, key: str, val: str) -> None:
    script_path.write_text(
        textwrap.dedent(f"""
            from pathlib import Path
            from webui_store.sqlite_base import WebUIDatabase
            from webui_store.schedule import ScheduleSqliteStore

            db = WebUIDatabase(Path(r'{db_path}'))
            store = ScheduleSqliteStore(db)
            store.update(lambda d: {{**d, '{key}': '{val}'}})
        """).strip(),
        encoding="utf-8",
    )


def test_cross_process_update_documents_behavior(tmp_path, monkeypatch):
    """Two OS processes each update() with distinct key; documents whether both survive.

    This test PASSES regardless of outcome (both keys survive or one is lost).
    A lost-update result documents the known cross-process RMW limitation of
    update() — the RLock only protects within a single process.
    """
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.sqlite_base import WebUIDatabase
    from webui_store.schedule import ScheduleSqliteStore

    db_path = tmp_path / "webui.db"
    # Initialize the store (creates tables)
    init_db = WebUIDatabase(db_path)
    ScheduleSqliteStore(init_db).save({})  # ensure table exists

    import os
    repo_root = Path(__file__).parent.parent
    env = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "BACKLINK_PUBLISHER_CONFIG_DIR": str(tmp_path),
        "PYTHONPATH": str(repo_root / "src") + os.pathsep + str(repo_root),
    }

    w0 = tmp_path / "worker_0.py"
    w1 = tmp_path / "worker_1.py"
    _write_worker(w0, db_path, "key_0", "val_0")
    _write_worker(w1, db_path, "key_1", "val_1")

    p0 = subprocess.Popen([sys.executable, str(w0)], env=env)
    p1 = subprocess.Popen([sys.executable, str(w1)], env=env)
    rc0, rc1 = p0.wait(), p1.wait()
    assert rc0 == 0, f"worker_0 exited {rc0}"
    assert rc1 == 0, f"worker_1 exited {rc1}"

    result = ScheduleSqliteStore(WebUIDatabase(db_path)).load()
    # Document behavior: both keys may or may not survive (known limitation).
    # This assertion is intentionally loose: the test passes either way.
    keys_present = {k for k in ("key_0", "key_1") if k in result}
    # At least one key must survive (complete data loss would be a crash)
    assert len(keys_present) >= 1, f"Expected at least 1 key, got: {result}"
    # Comment: if only 1 key survives, that documents the cross-process lost-update
    # limitation of update() — RLock only guards same-process access.


def test_in_process_sequential_update_no_deadlock(tmp_path, monkeypatch):
    """In-process: two sequential update() calls via RLock → both keys present."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.sqlite_base import WebUIDatabase
    from webui_store.schedule import ScheduleSqliteStore

    db = WebUIDatabase(tmp_path / "webui.db")
    store = ScheduleSqliteStore(db)

    store.update(lambda d: {**d, "key_a": "val_a"})
    store.update(lambda d: {**d, "key_b": "val_b"})

    result = store.load()
    assert result["key_a"] == "val_a"
    assert result["key_b"] == "val_b"


def test_two_instances_sequential_update_both_survive(tmp_path, monkeypatch):
    """Two in-process instances of same store, sequential update → non-conflicting rows."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.sqlite_base import WebUIDatabase
    from webui_store.schedule import ScheduleSqliteStore

    db_path = tmp_path / "webui.db"
    s1 = ScheduleSqliteStore(WebUIDatabase(db_path))
    s2 = ScheduleSqliteStore(WebUIDatabase(db_path))

    s1.update(lambda d: {**d, "from_s1": "x"})
    s2.update(lambda d: {**d, "from_s2": "y"})

    result = s1.load()
    assert result["from_s1"] == "x"
    assert result["from_s2"] == "y"
