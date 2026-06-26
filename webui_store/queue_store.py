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

from datetime import datetime
import json
from typing import Any

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import BaseSqliteStore

_SENTINEL_NAME = ".webui-queue-migrated-v1"
_JSON_FILENAME = "publish-queue.json"


class QueueSqliteStore(BaseSqliteStore):
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
    (load → fn → save under RLock). ``__init__`` / ``_init_table`` /
    ``migrate_from_json`` are inherited from :class:`BaseSqliteStore`.

    ``update_task`` / ``get_runnable`` preserve their JsonStore behaviour
    exactly; ``update_task`` is now a targeted SQL UPDATE rather than a
    full-list read-modify-write, and ``get_runnable`` filters by the indexed
    ``status`` column rather than scanning every task in Python.
    """

    _value_type = list
    _json_filename = _JSON_FILENAME
    _sentinel_name = _SENTINEL_NAME

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS tasks ("
            "id TEXT PRIMARY KEY, "
            "status TEXT NOT NULL, "
            "next_retry_at TEXT, "
            "data_json TEXT NOT NULL)"
        )

    def _indices_sql(self) -> list[str]:
        return [
            "CREATE INDEX IF NOT EXISTS tasks_status_retry "
            "ON tasks(status, next_retry_at)"
        ]

    def load(self) -> list[dict[str, Any]]:
        return self._load_rows("SELECT data_json FROM tasks ORDER BY rowid")

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
        self._replace_all_rows(
            "tasks", ("id", "status", "next_retry_at", "data_json"), rows
        )

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
