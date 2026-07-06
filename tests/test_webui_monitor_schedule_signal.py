"""Tests for the schedule/queue backlog signal source (Plan 2026-07-06-004 Unit 2, R6).

Covers ``_collect_schedule_queue_status()`` / ``_build_schedule_queue_card()`` /
the ``_classify_scheduled_draft`` / ``_classify_queue_task`` bucketing helpers
in ``webui_app/routes/command_center.py``.

Unlike ``error_report_store`` (Unit 2's other new signal source),
``queue_store``/``drafts_store`` both support a whole-table ``save(value)``
(delete-all + bulk-insert), so each test just calls ``.save([...])`` with an
exact, fully-specified list -- this replaces whatever the session-shared
sqlite db held before, giving a deterministic starting state without needing
a per-test tmp-db fixture (mirrors the existing ``_seed_equity()`` pattern in
``tests/test_webui_monitor_json_endpoints.py``).
"""
from __future__ import annotations

__tier__ = "integration"

import logging
from datetime import datetime, timedelta, timezone

from webui_app.routes import command_center as cc


def _past_iso(hours: float = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _future_iso(hours: float = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _seed_drafts(items):
    from webui_store import drafts_store
    drafts_store.save(items)


def _seed_queue_tasks(items):
    from webui_store import queue_store
    queue_store.save(items)


class TestCollectScheduleQueueStatus:
    def test_zero_items_is_healthy_not_absent(self):
        """Edge case: nothing waiting on a clock must still return a
        well-shaped status (not omit the key) -- the card builder turns this
        into the explicit '0 项，健康' card."""
        _seed_drafts([])
        _seed_queue_tasks([])
        status = cc._collect_schedule_queue_status()
        assert status == {
            "n_overdue": 0, "n_upcoming": 0, "n_unscheduled": 0,
            "n_pending": 0, "n_failed": 0, "n_other": 0,
            "total": 0, "items": [],
        }

    def test_happy_path_two_stuck_drafts_plus_one_pending_task(self):
        _seed_drafts([
            {"id": "d1", "status": "scheduled", "scheduled_at": _past_iso(1),
             "target_url": "https://a.com"},
            {"id": "d2", "status": "scheduled", "scheduled_at": _past_iso(2),
             "target_url": "https://b.com"},
        ])
        _seed_queue_tasks([
            {"id": "t1", "status": "pending", "urls": ["https://c.com"],
             "config": {"platform": "blogger"}},
        ])

        status = cc._collect_schedule_queue_status()
        assert status["n_overdue"] == 2
        assert status["n_pending"] == 1
        assert status["total"] == 3
        assert len(status["items"]) == 3
        item_types = {item["item_type"] for item in status["items"]}
        assert item_types == {"scheduled_draft", "queue_task"}

    def test_upcoming_draft_is_not_counted_as_overdue(self):
        _seed_drafts([{
            "id": "d1", "status": "scheduled", "scheduled_at": _future_iso(),
            "target_url": "https://a.com",
        }])
        _seed_queue_tasks([])

        status = cc._collect_schedule_queue_status()
        assert status["n_upcoming"] == 1
        assert status["n_overdue"] == 0
        assert status["total"] == 1

    def test_failed_queue_task_bucketed_separately_from_pending(self):
        _seed_drafts([])
        _seed_queue_tasks([
            {"id": "t1", "status": "pending", "urls": ["https://a.com"], "config": {}},
            {"id": "t2", "status": "failed", "urls": ["https://b.com"], "config": {},
             "error": "429 rate limited"},
        ])

        status = cc._collect_schedule_queue_status()
        assert status["n_pending"] == 1
        assert status["n_failed"] == 1
        assert status["total"] == 2

    def test_unparseable_scheduled_at_is_logged_and_counted_not_dropped(self, caplog):
        """Status-vocabulary-drift discipline (docs/solutions/logic-errors/
        projector-silent-drop-status-vocabulary-drift-2026-05-26.md): an item
        that can't be classified must still be counted in the total, not
        silently excluded."""
        caplog.set_level(logging.WARNING, logger="webui_app.routes.command_center")
        _seed_drafts([{
            "id": "d1", "status": "scheduled", "scheduled_at": "not-a-real-timestamp",
            "target_url": "https://a.com",
        }])
        _seed_queue_tasks([])

        status = cc._collect_schedule_queue_status()
        assert status["n_unscheduled"] == 1
        assert status["total"] == 1  # counted, not dropped
        assert "unparseable" in caplog.text

    def test_top_n_cap_with_view_all_action(self):
        _seed_drafts([])
        n = cc._SCHEDULE_QUEUE_TOP_N + 3
        _seed_queue_tasks([
            {"id": f"t{i}", "status": "pending", "urls": [f"https://x.com/{i}"], "config": {}}
            for i in range(n)
        ])

        status = cc._collect_schedule_queue_status()
        assert status["total"] == n
        assert len(status["items"]) == cc._SCHEDULE_QUEUE_TOP_N
        card = cc._build_schedule_queue_card(status)
        assert card["action"] == {"label": "查看全部", "href": "/schedule"}
        assert len(card["items"]) == cc._SCHEDULE_QUEUE_TOP_N  # inline items still capped

    def test_fail_open_when_get_runnable_raises(self, monkeypatch):
        # NOTE: `import webui_store.queue_store as queue_mod` would NOT give
        # the submodule here -- `webui_store/__init__.py` rebinds the
        # `queue_store` package attribute to the `_LazyStore` singleton
        # *after* importing the submodule, which shadows it for `import a.b
        # as x` (attribute-chain resolution). `from webui_store.queue_store
        # import QueueSqliteStore` resolves via `sys.modules` instead and is
        # unaffected by that shadowing.
        from webui_store.queue_store import QueueSqliteStore

        def _boom(self):
            raise RuntimeError("db locked")

        monkeypatch.setattr(QueueSqliteStore, "get_runnable", _boom)
        status = cc._collect_schedule_queue_status()
        assert set(status) == {"error"}
        assert "无法加载" in status["error"]
        assert "排程/队列" in status["error"]

    def test_fail_open_when_list_scheduled_reports_failure(self, monkeypatch):
        import webui_app.api.scheduled_api as sched_mod
        monkeypatch.setattr(sched_mod, "list_scheduled", lambda: {"ok": False, "error": "boom"})

        status = cc._collect_schedule_queue_status()
        assert "error" in status

    def test_first_ever_failure_shows_never_succeeded(self, monkeypatch):
        monkeypatch.setattr(cc, "_LAST_SUCCESS_AT", {})
        import webui_app.api.scheduled_api as sched_mod
        monkeypatch.setattr(sched_mod, "list_scheduled", lambda: {"ok": False, "error": "boom"})

        status = cc._collect_schedule_queue_status()
        assert "从未成功加载" in status["error"]

    def test_repeat_failure_after_success_shows_last_updated_time(self, monkeypatch):
        _seed_drafts([])
        _seed_queue_tasks([])
        cc._collect_schedule_queue_status()  # prime a success

        import webui_app.api.scheduled_api as sched_mod
        monkeypatch.setattr(sched_mod, "list_scheduled", lambda: {"ok": False, "error": "boom"})
        status = cc._collect_schedule_queue_status()
        assert "上次更新于" in status["error"]
        assert "从未成功加载" not in status["error"]

    def test_partial_failure_degrades_whole_merged_card_not_half(self, monkeypatch):
        """A merged single card can't show a half-correct total -- if either
        underlying read fails, the whole schedule_queue source degrades."""
        _seed_drafts([{
            "id": "d1", "status": "scheduled", "scheduled_at": _past_iso(),
            "target_url": "https://a.com",
        }])
        from webui_store.queue_store import QueueSqliteStore

        def _boom(self):
            raise RuntimeError("db locked")

        monkeypatch.setattr(QueueSqliteStore, "get_runnable", _boom)
        status = cc._collect_schedule_queue_status()
        assert "error" in status
        assert "total" not in status  # no partial/misleading count


class TestClassifyQueueTask:
    def test_pending_and_failed_are_recognized(self):
        assert cc._classify_queue_task({"status": "pending"}) == "pending"
        assert cc._classify_queue_task({"status": "failed"}) == "failed"

    def test_unrecognized_status_logged_and_bucketed_other(self, caplog):
        caplog.set_level(logging.WARNING, logger="webui_app.routes.command_center")
        result = cc._classify_queue_task({"id": "t9", "status": "processing"})
        assert result == "other"
        assert "unrecognized" in caplog.text
        assert "t9" in caplog.text


class TestBuildScheduleQueueCard:
    def test_zero_total_shows_healthy(self):
        card = cc._build_schedule_queue_card({"total": 0, "items": []})
        assert card["key"] == "schedule_queue"
        assert card["severity"] == "ok"
        assert "健康" in card["headline"]
        assert card["items"] == []

    def test_overdue_or_failed_escalates_to_warning(self):
        status = {
            "n_overdue": 1, "n_upcoming": 0, "n_unscheduled": 0,
            "n_pending": 0, "n_failed": 0, "n_other": 0, "total": 1, "items": [],
        }
        card = cc._build_schedule_queue_card(status)
        assert card["severity"] == "warning"

    def test_only_upcoming_or_pending_is_info_not_warning(self):
        status = {
            "n_overdue": 0, "n_upcoming": 1, "n_unscheduled": 0,
            "n_pending": 1, "n_failed": 0, "n_other": 0, "total": 2, "items": [],
        }
        card = cc._build_schedule_queue_card(status)
        assert card["severity"] == "info"

    def test_error_degrades_card_and_omits_items(self):
        card = cc._build_schedule_queue_card({"error": "无法加载排程/队列，从未成功加载"})
        assert card["severity"] == "info"
        assert "items" not in card


def test_schedule_queue_card_present_in_full_aggregate_when_empty():
    cards = cc._build_anomaly_cards({})
    sq_card = next((c for c in cards if c["key"] == "schedule_queue"), None)
    assert sq_card is not None
    assert sq_card["severity"] == "ok"
    assert sq_card["items"] == []
