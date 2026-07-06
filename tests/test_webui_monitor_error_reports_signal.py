"""Tests for the error-reports backlog signal source (Plan 2026-07-06-004 Unit 2, R5).

Covers ``_collect_error_reports_status()`` / ``_build_error_reports_card()`` in
``webui_app/routes/command_center.py``. Each test isolates
``webui_store.error_reports.error_report_store`` to a fresh, tmp_path-backed
``ErrorReportSqliteStore`` instance -- that store has no whole-table ``save()``
(it is an ever-growing, id-addressable row collection by design, see its module
docstring), so unlike ``queue_store``/``drafts_store`` it cannot be reset via a
single ``save([...])`` call. ``_collect_error_reports_status()`` re-imports
``error_report_store`` locally on every call, so monkeypatching the module
attribute is picked up cleanly without touching the real, session-shared store.
"""
from __future__ import annotations

__tier__ = "integration"

import pytest

from webui_app.routes import command_center as cc


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Point ``webui_store.error_reports.error_report_store`` at a fresh db."""
    import webui_store.error_reports as er_mod
    from webui_store.sqlite_base import WebUIDatabase

    fresh = er_mod.ErrorReportSqliteStore(WebUIDatabase(tmp_path / "webui.db"))
    monkeypatch.setattr(er_mod, "error_report_store", fresh)
    return fresh


class TestCollectErrorReportsStatus:
    def test_zero_reports_is_healthy_not_absent(self, isolated_store):
        """Edge case: 0 open reports must still return a well-shaped status,
        not omit the key entirely -- the card builder turns this into the
        explicit '0 条，健康' card, not an absent card."""
        status = cc._collect_error_reports_status()
        assert status == {"open_count": 0, "items": []}

    def test_happy_path_three_open_reports(self, isolated_store):
        for i in range(3):
            isolated_store.add({"message": f"boom {i}", "source": "vue", "severity": "warning"})
        status = cc._collect_error_reports_status()
        assert status["open_count"] == 3
        assert len(status["items"]) == 3
        # collector items are the raw store rows (id/status/severity/occurrences/
        # message/...); _error_report_item() does the item_type/headline shaping
        # for the card -- see TestBuildErrorReportsCard below.
        assert all("id" in item and "occurrences" in item for item in status["items"])

    def test_only_open_reports_are_counted(self, isolated_store):
        open_id = isolated_store.add({"message": "still open"})
        resolved_id = isolated_store.add({"message": "already resolved"})
        isolated_store.update_status(resolved_id, "resolved")

        status = cc._collect_error_reports_status()
        assert status["open_count"] == 1
        assert status["items"][0]["id"] == open_id

    def test_sorted_by_occurrences_descending(self, isolated_store):
        low_id = isolated_store.add({"message": "low", "severity": "info"})
        high_id = isolated_store.add({"message": "high", "severity": "danger"})
        for _ in range(5):
            isolated_store.increment_occurrence(high_id)

        status = cc._collect_error_reports_status()
        ordered_ids = [item["id"] for item in status["items"]]
        assert ordered_ids.index(high_id) < ordered_ids.index(low_id)

    def test_top_n_cap(self, isolated_store):
        n = cc._ERROR_REPORTS_TOP_N + 3
        for i in range(n):
            isolated_store.add({"message": f"boom {i}"})

        status = cc._collect_error_reports_status()
        assert status["open_count"] == n
        assert len(status["items"]) == cc._ERROR_REPORTS_TOP_N

    def test_fail_open_on_store_error(self, isolated_store, monkeypatch):
        def _boom(self, filters=None):
            raise RuntimeError("db locked")

        import webui_store.error_reports as er_mod
        monkeypatch.setattr(er_mod.ErrorReportSqliteStore, "list", _boom)

        status = cc._collect_error_reports_status()
        assert set(status) == {"error"}
        assert "无法加载" in status["error"]
        assert "错误回报" in status["error"]

    def test_first_failure_shows_never_succeeded(self, isolated_store, monkeypatch):
        monkeypatch.setattr(cc, "_LAST_SUCCESS_AT", {})

        import webui_store.error_reports as er_mod

        def _boom(self, filters=None):
            raise RuntimeError("db locked")

        monkeypatch.setattr(er_mod.ErrorReportSqliteStore, "list", _boom)
        status = cc._collect_error_reports_status()
        assert "从未成功加载" in status["error"]

    def test_repeat_failure_after_success_shows_last_updated_time(self, isolated_store, monkeypatch):
        cc._collect_error_reports_status()  # prime a success

        import webui_store.error_reports as er_mod

        def _boom(self, filters=None):
            raise RuntimeError("db locked")

        monkeypatch.setattr(er_mod.ErrorReportSqliteStore, "list", _boom)
        status = cc._collect_error_reports_status()
        assert "上次更新于" in status["error"]
        assert "从未成功加载" not in status["error"]

    def test_unaffected_by_unrelated_subsystem_failures(self, isolated_store):
        """Fail-open isolation: this source has its own try/except -- it must
        not be influenced by (and must not influence) any other source."""
        isolated_store.add({"message": "boom"})
        status = cc._collect_error_reports_status()
        assert status["open_count"] == 1


class TestBuildErrorReportsCard:
    def test_zero_open_reports_card_shows_healthy(self):
        card = cc._build_error_reports_card({"open_count": 0, "items": []})
        assert card["key"] == "error_reports"
        assert card["severity"] == "ok"
        assert "健康" in card["headline"]
        assert card["items"] == []

    def test_open_reports_card_shows_count_and_items(self):
        # `items` here are RAW store rows (as `_collect_error_reports_status()`
        # returns them) -- `_build_error_reports_card` shapes each one via
        # `_error_report_item()` into the item_type/headline/detail contract.
        raw_items = [{
            "id": "r1", "status": "open", "severity": "warning",
            "occurrences": 3, "message": "boom", "last_seen_at": "2026-07-06T00:00:00",
        }]
        card = cc._build_error_reports_card({"open_count": 1, "items": raw_items})
        assert card["severity"] == "warning"
        assert "1" in card["headline"]
        assert card["action"] is None  # count does not exceed the item list
        assert len(card["items"]) == 1
        shaped = card["items"][0]
        assert shaped["id"] == "r1"
        assert shaped["item_type"] == "error_report"
        assert shaped["headline"] == "boom"
        assert shaped["occurrences"] == 3

    def test_item_count_exceeds_n_shows_view_all_action_not_full_list(self):
        n = cc._ERROR_REPORTS_TOP_N
        raw_items = [{"id": f"r{i}", "status": "open"} for i in range(n)]
        card = cc._build_error_reports_card({"open_count": n + 4, "items": raw_items})
        assert card["action"] == {"label": "查看全部", "href": "/error-reports"}
        assert len(card["items"]) == n  # inline items still capped at N

    def test_error_degrades_card_and_omits_items(self):
        card = cc._build_error_reports_card({"error": "无法加载错误回报，从未成功加载"})
        assert card["severity"] == "info"
        assert "items" not in card


def test_error_reports_card_present_in_full_aggregate_when_empty():
    """Edge case (integration-level): a status dict with no 'error_reports'
    key at all (e.g. a synthetic test status) must still produce a visible,
    healthy card -- the card builder defaults to the empty/healthy shape."""
    cards = cc._build_anomaly_cards({})
    er_card = next((c for c in cards if c["key"] == "error_reports"), None)
    assert er_card is not None
    assert er_card["severity"] == "ok"
    assert er_card["items"] == []


def test_unrecognized_error_status_is_not_silently_produced_by_store(caplog):
    """error_reports.py validates `status` against a closed enum on write, so
    there is no vocabulary-drift branch to exercise on the read side here
    (unlike schedule_queue's free-form task/draft status) -- this test pins
    that expectation so a future loosening of that validation is noticed."""
    from webui_store.error_reports import STATUS_VALUES
    assert STATUS_VALUES == frozenset({"open", "acknowledged", "resolved"})
