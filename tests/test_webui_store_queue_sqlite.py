"""Tests for QueueSqliteStore (Unit 5) — queue_store → webui.db ``tasks`` table.

Verifies targeted update_task, get_runnable filtering semantics, load/save/update
roundtrip, startup migration from JSON (order + completeness), sentinel
idempotency, crash-recovery, and Store protocol compliance.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
"""

from __future__ import annotations

__tier__ = "integration"
import contextlib
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading

from webui_store.base import Store
from webui_store.queue_store import (
    _JSON_FILENAME,
    _SENTINEL_NAME,
    QueueSqliteStore,
    TaskUpdateOutcome,
)
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> QueueSqliteStore:
    return QueueSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


def _past() -> str:
    return (datetime.now() - timedelta(hours=1)).isoformat()


def _future() -> str:
    return (datetime.now() + timedelta(hours=1)).isoformat()


# ── Core Store protocol ───────────────────────────────────────────────────────

class TestQueueSqliteStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_load_returns_empty_list_when_absent(self, tmp_path):
        assert _store(tmp_path).load() == []

    def test_load_returns_list_not_none(self, tmp_path):
        assert isinstance(_store(tmp_path).load(), list)

    def test_save_and_load_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        tasks = [
            {"id": "t1", "status": "pending", "next_retry_at": None, "url": "a"},
            {"id": "t2", "status": "done", "next_retry_at": None, "url": "b"},
        ]
        store.save(tasks)
        assert store.load() == tasks

    def test_save_preserves_insertion_order(self, tmp_path):
        store = _store(tmp_path)
        tasks = [{"id": f"t{i}", "status": "pending"} for i in range(10)]
        store.save(tasks)
        assert [t["id"] for t in store.load()] == [f"t{i}" for i in range(10)]

    def test_save_overwrites_previous(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "pending"}])
        store.save([{"id": "b", "status": "done"}])
        assert store.load() == [{"id": "b", "status": "done"}]

    def test_save_empty_list(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "a", "status": "pending"}])
        store.save([])
        assert store.load() == []

    def test_update_roundtrip(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending"}])
        result = store.update(lambda ts: ts + [{"id": "t2", "status": "pending"}])
        assert [t["id"] for t in result] == ["t1", "t2"]
        assert [t["id"] for t in store.load()] == ["t1", "t2"]


# ── update_task (targeted) ────────────────────────────────────────────────────

class TestUpdateTask:
    def test_mutates_only_target_task(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "t1", "status": "pending", "x": 1},
            {"id": "t2", "status": "pending", "x": 2},
        ])
        store.update_task("t1", {"status": "done"})
        loaded = {t["id"]: t for t in store.load()}
        assert loaded["t1"]["status"] == "done"
        assert loaded["t1"]["x"] == 1  # other fields preserved
        assert loaded["t2"] == {"id": "t2", "status": "pending", "x": 2}

    def test_merges_new_keys(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending"}])
        store.update_task("t1", {"error": "boom", "attempts": 3})
        task = store.load()[0]
        assert task["error"] == "boom"
        assert task["attempts"] == 3
        assert task["status"] == "pending"

    def test_updates_next_retry_at_column(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed", "next_retry_at": None}])
        future = _future()
        store.update_task("t1", {"next_retry_at": future})
        # get_runnable must reflect the column change → excluded (future)
        assert store.get_runnable() == []
        assert store.load()[0]["next_retry_at"] == future

    def test_absent_id_is_no_op(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending"}])
        store.update_task("nonexistent", {"status": "done"})  # no error
        assert store.load() == [{"id": "t1", "status": "pending"}]

    def test_absent_id_on_empty_store_is_no_op(self, tmp_path):
        store = _store(tmp_path)
        store.update_task("x", {"status": "done"})
        assert store.load() == []

    def test_preserves_order_after_update(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": f"t{i}", "status": "pending"} for i in range(5)])
        store.update_task("t2", {"status": "done"})
        assert [t["id"] for t in store.load()] == [f"t{i}" for i in range(5)]


# ── update_task_if_status (atomic conditional UPDATE, Unit 1) ─────────────────

class TestUpdateTaskIfStatus:
    """Plan 2026-07-06-004 Unit 1: retry_task() bug fixes.

    ``update_task_if_status`` must be a single atomic conditional SQL
    UPDATE (checked via affected-row-count), not a separate read-then-write
    — see the method's docstring for the TOCTOU race this closes against
    ``webui_app/scheduler.py::_process_queue_job``.
    """

    def test_happy_path_updates_and_returns_updated(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed", "error": "boom"}])
        outcome = store.update_task_if_status(
            "t1", {"status": "pending", "error": None}, forbidden_status="processing",
        )
        assert outcome is TaskUpdateOutcome.UPDATED
        task = store.load()[0]
        assert task["status"] == "pending"
        assert task["error"] is None

    def test_mirrors_status_column(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed"}])
        store.update_task_if_status(
            "t1", {"status": "pending", "error": None}, forbidden_status="processing",
        )
        # get_runnable() filters on the indexed status column, not data_json.
        assert [t["id"] for t in store.get_runnable()] == ["t1"]

    def test_preserves_other_fields(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed", "x": 1, "urls": ["a"]}])
        store.update_task_if_status(
            "t1", {"status": "pending", "error": None}, forbidden_status="processing",
        )
        task = store.load()[0]
        assert task["x"] == 1
        assert task["urls"] == ["a"]

    def test_unknown_id_returns_not_found(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed"}])
        outcome = store.update_task_if_status(
            "nonexistent", {"status": "pending", "error": None},
            forbidden_status="processing",
        )
        assert outcome is TaskUpdateOutcome.NOT_FOUND
        # untouched — no phantom row created, existing row unaffected
        assert store.load() == [{"id": "t1", "status": "failed"}]

    def test_unknown_id_on_empty_store_returns_not_found(self, tmp_path):
        store = _store(tmp_path)
        outcome = store.update_task_if_status(
            "ghost", {"status": "pending", "error": None}, forbidden_status="processing",
        )
        assert outcome is TaskUpdateOutcome.NOT_FOUND

    def test_processing_status_is_rejected_not_clobbered(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "processing"}])
        outcome = store.update_task_if_status(
            "t1", {"status": "pending", "error": None}, forbidden_status="processing",
        )
        assert outcome is TaskUpdateOutcome.REJECTED
        # must NOT have been silently flipped back to pending
        assert store.load()[0]["status"] == "processing"

    def test_non_processing_status_is_updated(self, tmp_path):
        # Sanity: only the forbidden status is guarded; any other current
        # status (pending/failed/success/done/...) is retryable.
        store = _store(tmp_path)
        for status in ("pending", "failed", "success", "done"):
            store.save([{"id": "t1", "status": status}])
            outcome = store.update_task_if_status(
                "t1", {"status": "pending", "error": None}, forbidden_status="processing",
            )
            assert outcome is TaskUpdateOutcome.UPDATED, status

    def test_empty_updates_raises(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending"}])
        try:
            store.update_task_if_status("t1", {}, forbidden_status="processing")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_rejects_unsafe_field_name(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending"}])
        try:
            store.update_task_if_status(
                "t1", {"status'; DROP TABLE tasks; --": "x"},
                forbidden_status="processing",
            )
            assert False, "expected ValueError"
        except ValueError:
            pass

    # ── Genuine interleaving: the atomic UPDATE must see LIVE status,
    #    not a value captured earlier in Python. ─────────────────────────

    def test_atomic_update_sees_live_status_not_stale_snapshot(self, tmp_path, monkeypatch):
        """Simulates the scheduler grabbing the task for processing in the
        exact window between our conditional UPDATE being prepared and it
        actually executing against the database.

        A single atomic SQL statement has no such window at the Python
        level: the WHERE guard is evaluated by SQLite against the row's
        live value at the instant the UPDATE runs. This test proves that —
        it gates our own conditional UPDATE's ``conn.execute`` call right
        before it fires, lets a *separate* connection (simulating the
        scheduler thread) commit a ``'processing'`` transition while we're
        paused, then releases us. The guard must see that fresh value and
        reject — proving the decision is made at execution time, not from
        an earlier Python-level read. A read-then-write implementation
        gated the same way would instead have already decided "not
        processing" before the pause and would incorrectly clobber the
        scheduler's claim — exactly the race this method exists to close.
        """
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending", "error": "boom"}])

        real_connect = store._db.connect
        reached_gate = threading.Event()
        proceed = threading.Event()

        class _GatedConn:
            """Proxies a real sqlite3.Connection; pauses right before the
            conditional retry UPDATE executes (identified by its WHERE
            clause), so a concurrent writer can land in between."""

            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, params=()):
                if "status != ?" in sql:
                    reached_gate.set()
                    assert proceed.wait(timeout=5), "test deadlocked: proceed never set"
                return self._conn.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        @contextlib.contextmanager
        def gated_connect():
            with real_connect() as conn:
                yield _GatedConn(conn)

        monkeypatch.setattr(store._db, "connect", gated_connect)

        result: dict[str, TaskUpdateOutcome] = {}

        def _retry():
            result["outcome"] = store.update_task_if_status(
                "t1", {"status": "pending", "error": None},
                forbidden_status="processing",
            )

        retry_thread = threading.Thread(target=_retry)
        retry_thread.start()
        assert reached_gate.wait(timeout=5), "retry call never reached its UPDATE"

        # "Scheduler" thread wins the race: claims the task via a plain,
        # ungated update_task() call while our retry is paused mid-flight.
        store.update_task("t1", {"status": "processing"})
        proceed.set()
        retry_thread.join(timeout=5)

        assert result["outcome"] is TaskUpdateOutcome.REJECTED
        # Never clobbered back to 'pending' despite our stale-looking read.
        assert store.load()[0]["status"] == "processing"

    def test_atomic_update_wins_when_it_runs_before_scheduler_claims_task(
        self, tmp_path, monkeypatch,
    ):
        """Mirror case: if our conditional UPDATE reaches SQLite strictly
        before the scheduler's claim, the retry legitimately succeeds and
        the scheduler's subsequent claim attempt (via plain update_task,
        which is unconditional) would be the one that "wins" afterwards —
        this just pins that a live 'pending' row is retryable at all under
        the same gated harness used above."""
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed", "error": "boom"}])

        real_connect = store._db.connect
        reached_gate = threading.Event()
        proceed = threading.Event()

        class _GatedConn:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, params=()):
                if "status != ?" in sql:
                    reached_gate.set()
                    assert proceed.wait(timeout=5), "test deadlocked: proceed never set"
                return self._conn.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        @contextlib.contextmanager
        def gated_connect():
            with real_connect() as conn:
                yield _GatedConn(conn)

        monkeypatch.setattr(store._db, "connect", gated_connect)

        result: dict[str, TaskUpdateOutcome] = {}

        def _retry():
            result["outcome"] = store.update_task_if_status(
                "t1", {"status": "pending", "error": None},
                forbidden_status="processing",
            )

        retry_thread = threading.Thread(target=_retry)
        retry_thread.start()
        assert reached_gate.wait(timeout=5)
        # No concurrent claim this time — release immediately.
        proceed.set()
        retry_thread.join(timeout=5)

        assert result["outcome"] is TaskUpdateOutcome.UPDATED
        assert store.load()[0]["status"] == "pending"


# ── get_runnable filtering ────────────────────────────────────────────────────

class TestGetRunnable:
    def test_returns_eligible_status_with_no_retry(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "t1", "status": "pending", "next_retry_at": None},
            {"id": "t2", "status": "failed", "next_retry_at": None},
        ])
        ids = {t["id"] for t in store.get_runnable()}
        assert ids == {"t1", "t2"}

    def test_returns_past_next_retry_at(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed", "next_retry_at": _past()}])
        assert [t["id"] for t in store.get_runnable()] == ["t1"]

    def test_excludes_future_next_retry_at(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "failed", "next_retry_at": _future()}])
        assert store.get_runnable() == []

    def test_excludes_ineligible_status(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "t1", "status": "done", "next_retry_at": None},
            {"id": "t2", "status": "processing", "next_retry_at": None},
        ])
        assert store.get_runnable() == []

    def test_mixed_set(self, tmp_path):
        store = _store(tmp_path)
        store.save([
            {"id": "ready1", "status": "pending", "next_retry_at": None},
            {"id": "ready2", "status": "failed", "next_retry_at": _past()},
            {"id": "later", "status": "failed", "next_retry_at": _future()},
            {"id": "done", "status": "done", "next_retry_at": None},
            {"id": "ready3", "status": "pending"},  # missing next_retry_at
        ])
        ids = {t["id"] for t in store.get_runnable()}
        assert ids == {"ready1", "ready2", "ready3"}

    def test_empty_string_next_retry_at_is_runnable(self, tmp_path):
        store = _store(tmp_path)
        store.save([{"id": "t1", "status": "pending", "next_retry_at": ""}])
        assert [t["id"] for t in store.get_runnable()] == ["t1"]

    def test_empty_store(self, tmp_path):
        assert _store(tmp_path).get_runnable() == []


# ── Startup migration ─────────────────────────────────────────────────────────

class TestStartupMigration:
    def test_migrates_from_json_preserves_order_and_tasks(self, tmp_path):
        tasks = [
            {"id": "t1", "status": "pending", "url": "a"},
            {"id": "t2", "status": "failed", "url": "b"},
            {"id": "t3", "status": "done", "url": "c"},
        ]
        (tmp_path / _JSON_FILENAME).write_text(json.dumps(tasks), encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        assert store.load() == tasks
        assert (tmp_path / (_JSON_FILENAME + ".migrated")).exists()
        assert (tmp_path / _SENTINEL_NAME).exists()
        assert not (tmp_path / _JSON_FILENAME).exists()

    def test_migrated_file_chmod_600(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("[]", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        migrated = tmp_path / (_JSON_FILENAME + ".migrated")
        assert migrated.exists()
        assert (migrated.stat().st_mode & 0o777) == 0o600

    def test_idempotent_when_sentinel_exists(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text(
            json.dumps([{"id": "t1", "status": "pending"}]), encoding="utf-8"
        )
        (tmp_path / _SENTINEL_NAME).write_text("migrated", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        assert (tmp_path / _JSON_FILENAME).exists()
        assert store.load() == []  # nothing imported

    def test_no_op_when_json_absent(self, tmp_path):
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert store.load() == []

    def test_corrupt_json_skipped_no_sentinel(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text("not valid [", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert not (tmp_path / _SENTINEL_NAME).exists()
        assert (tmp_path / _JSON_FILENAME).exists()

    def test_crash_recovery_migrated_exists_no_sentinel(self, tmp_path):
        (tmp_path / (_JSON_FILENAME + ".migrated")).write_text("[]", encoding="utf-8")
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)
        assert (tmp_path / _SENTINEL_NAME).exists()

    def test_second_migration_call_is_no_op(self, tmp_path):
        (tmp_path / _JSON_FILENAME).write_text(
            json.dumps([{"id": "t1", "status": "pending"}]), encoding="utf-8"
        )
        store = _store(tmp_path)
        store.migrate_from_json(tmp_path)

        store.save([{"id": "z", "status": "done"}])
        store.migrate_from_json(tmp_path)
        assert store.load() == [{"id": "z", "status": "done"}]


# ── Integration: import from webui_store ─────────────────────────────────────

class TestWebuiStoreIntegration:
    def test_queue_store_import_satisfies_protocol(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, queue_store
        _refresh_paths()

        assert isinstance(queue_store._real(), QueueSqliteStore)
        queue_store.save([{"id": "t1", "status": "pending"}])
        assert queue_store.load() == [{"id": "t1", "status": "pending"}]

    def test_queue_store_path_is_webui_db(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, queue_store
        _refresh_paths()

        assert queue_store.path == tmp_path / "webui.db"

    def test_queue_store_update_task_and_get_runnable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store import _refresh_paths, queue_store
        _refresh_paths()

        queue_store.save([{"id": "t1", "status": "pending", "next_retry_at": None}])
        queue_store.update_task("t1", {"status": "processing"})
        assert queue_store.get_runnable() == []
