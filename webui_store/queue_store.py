"""QueueSqliteStore — background publishing task persistence backed by webui.db.

Replaces the ``publish-queue.json`` JsonStore with a proper row table keyed by
task id, with an indexed ``status`` column so ``get_runnable()`` is a single
SQL query instead of a Python loop over the whole list.

The public API (``update_task`` / ``get_runnable`` / inherited
``load`` / ``save`` / ``update``) is preserved exactly. The stored value is a
list of task dicts; each whole task dict is serialised into ``data_json`` and
its ``id`` / ``status`` / ``next_retry_at`` fields are mirrored into dedicated
columns for querying.

Startup migration: on first boot after this code is deployed, the existing
``publish-queue.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
Unit 5.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import SqliteStore, WebUIDatabase

_log = logging.getLogger(__name__)

_SENTINEL_NAME = ".webui-queue-migrated-v1"
_JSON_FILENAME = "publish-queue.json"


class QueueSqliteStore(SqliteStore):
    """Row-table store for background publishing tasks, backed by webui.db.

    Table::

        tasks (
          id            TEXT PRIMARY KEY,
          status        TEXT NOT NULL,
          next_retry_at TEXT,
          data_json     TEXT NOT NULL
        )
        CREATE INDEX tasks_status_retry ON tasks(status, next_retry_at)

    ``load()`` returns the full ``list[dict]`` in insertion order (``[]`` when
    empty). ``save(value)`` is a full delete-all + bulk-insert rewrite (matches
    the JsonStore whole-file rewrite semantics). ``update(fn)`` is inherited
    (load → fn → save under RLock).

    ``update_task`` / ``get_runnable`` preserve their JsonStore behaviour
    exactly; ``update_task`` is now a targeted SQL UPDATE rather than a
    full-list read-modify-write, and ``get_runnable`` filters by the indexed
    ``status`` column rather than scanning every task in Python.
    """

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "id TEXT PRIMARY KEY, "
                "status TEXT NOT NULL, "
                "next_retry_at TEXT, "
                "data_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS tasks_status_retry "
                "ON tasks(status, next_retry_at)"
            )

    def load(self) -> list[dict[str, Any]]:
        def _op() -> list[dict[str, Any]]:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT data_json FROM tasks ORDER BY rowid"
                ).fetchall()
            result: list[dict[str, Any]] = []
            for (data_json,) in rows:
                try:
                    task = json.loads(data_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(task, dict):
                    result.append(task)
            return result

        return _retry_sqlite(_op)

    def save(self, value: Any) -> None:
        tasks = value if isinstance(value, list) else []
        rows: list[tuple[Any, ...]] = []
        for task in tasks:
            task = task if isinstance(task, dict) else {}
            rows.append(
                (
                    task.get("id"),
                    task.get("status"),
                    task.get("next_retry_at"),
                    json.dumps(task, ensure_ascii=False),
                )
            )

        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute("DELETE FROM tasks")
                    if rows:
                        conn.executemany(
                            "INSERT INTO tasks (id, status, next_retry_at, "
                            "data_json) VALUES (?, ?, ?, ?)",
                            rows,
                        )

            _retry_sqlite(_op)

    # ── Task-level helpers (public API, preserved from JsonStore) ──────────

    def update_task(self, task_id: str, updates: dict[str, Any]) -> None:
        """Merge ``updates`` into the task with ``id == task_id``.

        Targeted single-row UPDATE. If no such task exists, this is a no-op
        (0 rows updated, no error) — identical observable behaviour to the old
        full-list-scan read-modify-write.
        """
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT data_json FROM tasks WHERE id = ?", (task_id,)
                    ).fetchone()
                    if row is None:
                        return
                    try:
                        task = json.loads(row[0])
                    except (json.JSONDecodeError, TypeError):
                        task = {}
                    if not isinstance(task, dict):
                        task = {}
                    task.update(updates)
                    conn.execute(
                        "UPDATE tasks SET status = ?, next_retry_at = ?, "
                        "data_json = ? WHERE id = ?",
                        (
                            task.get("status"),
                            task.get("next_retry_at"),
                            json.dumps(task, ensure_ascii=False),
                            task_id,
                        ),
                    )

            _retry_sqlite(_op)

    def get_runnable(self) -> list[dict[str, Any]]:
        """Return tasks that are pending or failed and past their retry time.

        Filters on the indexed ``status`` column, then compares ``next_retry_at``
        with ``datetime`` in Python — matching the old loop semantics exactly
        (status in pending/failed; next_retry_at null/empty or in the past).
        """
        now = datetime.now()

        def _op() -> list[tuple[str]]:
            with self._db.connect() as conn:
                return conn.execute(
                    "SELECT data_json FROM tasks "
                    "WHERE status IN ('pending', 'failed') ORDER BY rowid"
                ).fetchall()

        rows = _retry_sqlite(_op)
        runnable: list[dict[str, Any]] = []
        for (data_json,) in rows:
            try:
                task = json.loads(data_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(task, dict):
                continue
            next_retry_at = task.get("next_retry_at")
            if not next_retry_at or datetime.fromisoformat(next_retry_at) <= now:
                runnable.append(task)
        return runnable

    # ── Startup migration ─────────────────────────────────────────────────

    def migrate_from_json(self, config_dir: Path) -> None:
        """One-shot import from ``publish-queue.json`` if not yet migrated.

        Same load-bearing sequence as ``ScheduleSqliteStore.migrate_from_json``:
        commit to webui.db → rename ``.json`` → chmod 0o600 → write sentinel.
        Corrupt/absent JSON is silently skipped (sentinel NOT written so a
        later-appearing file can still be imported).
        """
        sentinel = config_dir / _SENTINEL_NAME
        json_path = config_dir / _JSON_FILENAME
        migrated_path = json_path.with_suffix(".json.migrated")

        if sentinel.exists():
            return

        # Crash-recovery: rename completed but sentinel not written
        if migrated_path.exists() and not sentinel.exists():
            sentinel.write_text("migrated", encoding="utf-8")
            return

        if not json_path.exists():
            return

        try:
            text = json_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError):
            _log.warning(
                "queue_store migration: skipping corrupt/unreadable %s", json_path
            )
            return

        self.save(data if isinstance(data, list) else [])

        try:
            json_path.rename(migrated_path)
        except OSError as exc:
            _log.warning("queue_store migration: rename failed: %s", exc)
            return

        try:
            os.chmod(migrated_path, 0o600)
        except OSError:
            pass

        sentinel.write_text("migrated", encoding="utf-8")
