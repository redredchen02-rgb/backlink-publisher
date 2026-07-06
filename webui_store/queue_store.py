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

import enum
from datetime import datetime
import json
from typing import Any

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import BaseSqliteStore, _SQL_IDENTIFIER_RE

_SENTINEL_NAME = ".webui-queue-migrated-v1"
_JSON_FILENAME = "publish-queue.json"

# Indexed columns that mirror fields inside ``data_json`` — see the table
# docstring below. ``update_task_if_status`` keeps both in sync in one
# statement whenever the caller's ``updates`` touch one of these keys.
_MIRRORED_COLUMNS = ("status", "next_retry_at")


class TaskUpdateOutcome(enum.Enum):
    """Result of :meth:`QueueSqliteStore.update_task_if_status`.

    ``UPDATED`` — exactly one row changed.
    ``NOT_FOUND`` — no task with the given id exists.
    ``REJECTED`` — the task exists but its live status equals the caller's
    ``forbidden_status`` at the moment the conditional UPDATE executed, so
    the WHERE guard held and zero rows were affected.
    """

    UPDATED = "updated"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


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

    def update_task_if_status(
        self,
        task_id: str,
        updates: dict[str, Any],
        *,
        forbidden_status: str = "processing",
    ) -> TaskUpdateOutcome:
        """Conditionally merge ``updates`` into the task ``id == task_id``.

        This is the safe alternative to :meth:`update_task` for callers that
        must not clobber a task the background scheduler
        (``webui_app/scheduler.py::_process_queue_job``) is currently
        working on. That scheduler runs on its own thread — outside any
        request-serialized lock — and flips a task's status to
        ``'processing'`` *before* doing the real (network-latency) publish
        work, then writes the terminal status only after that work returns.

        The whole read-guard-write happens inside **one** SQL statement::

            UPDATE tasks SET status = ?, data_json = json_set(...)
            WHERE id = ? AND status != ?

        executed as a single ``conn.execute()`` call and gated purely by
        SQLite's own write-lock — deliberately **not** wrapped in
        ``self._lock``. A Python-level read-then-write (even one guarded by
        ``self._lock``) would only be as safe as that lock's discipline
        happens to be; the atomic SQL statement's WHERE clause is instead
        evaluated by SQLite against the row's *live* value at the instant
        the UPDATE executes, so there is no gap in which a concurrent
        ``update_task(task_id, {'status': 'processing'})`` call from the
        scheduler thread could land between "we decided it was safe to
        write" and "we wrote" — the two cases collapse into the same
        atomic check-and-set. Reopening that gap (a separate SELECT to
        decide, followed by a separate UPDATE) is exactly the anti-pattern
        this method exists to avoid: it would let a task get silently
        reset to ``'pending'`` while the scheduler is mid-publish, risking
        a duplicate publish to an external platform.

        Returns:
            ``TaskUpdateOutcome.UPDATED`` — the row was found and its
                status did not equal ``forbidden_status``; ``updates`` was
                applied.
            ``TaskUpdateOutcome.NOT_FOUND`` — no task with this id exists.
            ``TaskUpdateOutcome.REJECTED`` — the task exists but its status
                equals ``forbidden_status``, so the guard held and nothing
                was written.

        The NOT_FOUND vs REJECTED distinction is resolved by a follow-up
        read-only ``SELECT`` that runs *only* when the atomic UPDATE
        affects zero rows. That lookup is diagnostic only (it shapes the
        caller's error message) and never mutates state, so it cannot
        reopen the race the atomic UPDATE closes — at worst its answer is
        a few milliseconds stale (e.g. the task has since finished
        processing), which only affects the wording of the rejection,
        never whether the write was allowed to happen.
        """
        if not updates:
            raise ValueError("update_task_if_status: updates must be non-empty")
        for key in updates:
            if not _SQL_IDENTIFIER_RE.match(key):
                raise ValueError(f"update_task_if_status: invalid field name {key!r}")

        set_clauses: list[str] = []
        params: list[Any] = []
        for column in _MIRRORED_COLUMNS:
            if column in updates:
                set_clauses.append(f"{column} = ?")
                params.append(updates[column])

        json_set_pairs = ", ".join(f"'$.{key}', ?" for key in updates)
        set_clauses.append(f"data_json = json_set(data_json, {json_set_pairs})")
        params.extend(updates.values())

        sql = (
            f"UPDATE tasks SET {', '.join(set_clauses)} "
            "WHERE id = ? AND status != ?"
        )
        params.extend([task_id, forbidden_status])
        bound_params = tuple(params)

        def _op() -> int:
            with self._db.connect() as conn:
                cur = conn.execute(sql, bound_params)
                return cur.rowcount

        rowcount = _retry_sqlite(_op)
        if rowcount >= 1:
            return TaskUpdateOutcome.UPDATED

        # Zero rows affected by the guarded UPDATE above — diagnostic-only
        # read to tell "no such id" apart from "guard rejected it". Does
        # not participate in the write decision (see docstring).
        def _lookup() -> Any:
            with self._db.connect() as conn:
                return conn.execute(
                    "SELECT status FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()

        row = _retry_sqlite(_lookup)
        return TaskUpdateOutcome.NOT_FOUND if row is None else TaskUpdateOutcome.REJECTED

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
