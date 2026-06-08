"""Plan 2026-05-19-006 Unit 1 — history truth propagation.

Lock the contract: ``_push_history_per_row`` writes one history entry per
CLI publish-result row, transparently carrying the per-row ``status``
(including ``*_unverified`` suffixes) and synthesising ``failed`` when an
adapter returns no URL.

Updated for plan 2026-05-28-007 U2: events.db is now the sole write target.
Assertions use list_history() (events.db query) instead of history_store.load().
"""
from __future__ import annotations


__tier__ = "unit"
import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect EventStore to a per-test temp directory."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    yield


# ── _push_history_per_row happy paths ────────────────────────────────────────


class TestPushHistoryPerRow:
    def test_writes_one_entry_per_row(self):
        from webui_app.helpers.history import _push_history_per_row
        rows = [
            {
                "status": "published",
                "target_url": "https://a.example/",
                "platform": "medium",
                "title": "T1",
                "published_url": "https://medium.com/p/abc",
                "draft_url": "",
                "error": None,
            },
            {
                "status": "drafted_unverified",
                "target_url": "https://b.example/",
                "platform": "medium",
                "title": "T2",
                "published_url": "",
                "draft_url": "https://medium.com/p/def-draft",
                "error": None,
            },
        ]
        result = _push_history_per_row(rows, target_url_fallback="x", platform_fallback="y", language_fallback="zh-CN")
        assert len(result) == 2
        by_title = {r.get("title"): r for r in result}
        assert by_title["T1"]["status"] == "published"
        assert by_title["T1"]["article_urls"] == ["https://medium.com/p/abc"]
        assert by_title["T2"]["status"] == "drafted_unverified"
        assert by_title["T2"]["article_urls"] == ["https://medium.com/p/def-draft"]

    def test_preserves_unverified_suffix(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_per_row
        rows = [{
            "status": "published_unverified",
            "target_url": "https://x.example/",
            "title": "T",
            "published_url": "https://medium.com/p/zzz",
            "draft_url": "",
            "error": None,
        }]
        _push_history_per_row(rows)
        items = list_history()
        assert items, "no items in events.db after write"
        assert items[0]["status"] == "published_unverified"

    def test_empty_urls_with_no_error_coerces_to_failed(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_per_row
        rows = [{
            "status": "drafted",
            "target_url": "https://x.example/",
            "title": "T",
            "published_url": "",
            "draft_url": "",
            "error": None,
        }]
        _push_history_per_row(rows)
        items = list_history()
        assert items, "no items in events.db after write"
        item = items[0]
        assert item["status"] == "failed"
        assert item["error"] == "no URL returned by adapter"
        assert item["article_urls"] == []

    def test_unverified_with_empty_urls_stays_unverified(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_per_row
        rows = [{
            "status": "published_unverified",
            "target_url": "https://x.example/",
            "title": "T",
            "published_url": "",
            "draft_url": "",
            "error": None,
        }]
        _push_history_per_row(rows)
        items = list_history()
        assert items, "no items in events.db after write"
        assert items[0]["status"] == "published_unverified"

    def test_falls_back_to_provided_target_url(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_per_row
        rows = [{
            "status": "published",
            # no target_url in the row
            "title": "T",
            "published_url": "https://medium.com/p/x",
            "error": None,
        }]
        _push_history_per_row(rows, target_url_fallback="https://fallback.example/")
        items = list_history()
        assert items, "no items in events.db after write"
        assert items[0]["target_url"] == "https://fallback.example/"

    def test_empty_rows_is_noop(self):
        from webui_app.helpers.history import _push_history_per_row
        result = _push_history_per_row([])
        assert result == []

    def test_carries_adapter_field(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_per_row
        rows = [{
            "status": "published",
            "title": "T",
            "adapter": "medium-api",
            "published_url": "https://medium.com/p/x",
            "error": None,
        }]
        _push_history_per_row(rows)
        items = list_history()
        assert items, "no items in events.db after write"
        assert items[0].get("adapter") == "medium-api"

    def test_error_row_preserved(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_per_row
        rows = [{
            "status": "failed",
            "title": "T",
            "published_url": "",
            "error": "service error: 503 from medium",
        }]
        _push_history_per_row(rows)
        items = list_history()
        assert items, "no items in events.db after write"
        item = items[0]
        assert item["status"] == "failed"
        assert item["error"] == "service error: 503 from medium"

    def test_truncates_to_max_items(self):
        from webui_app.helpers.history import _push_history_per_row, _HISTORY_MAX_ITEMS
        new_rows = [{
            "status": "published",
            "title": "T",
            "published_url": f"https://x/{n}",
            "error": None,
        } for n in range(3)]
        result = _push_history_per_row(new_rows)
        assert len(result) == 3


class TestPushHistorySingleFailure:
    def test_writes_one_failed_entry(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_single_failure
        _push_history_single_failure(
            target_url="https://x.example/",
            platform="medium",
            language="zh-CN",
            error="boom",
        )
        items = list_history()
        assert len(items) == 1
        assert items[0]["status"] == "failed"
        assert items[0]["error"] == "boom"
        assert items[0]["article_urls"] == []

    def test_uses_default_error_when_blank(self):
        from backlink_publisher.events.history_query import list_history
        from webui_app.helpers.history import _push_history_single_failure
        _push_history_single_failure(
            target_url="https://x.example/", platform="", language="", error="",
        )
        items = list_history()
        assert items, "no items in events.db after write"
        assert items[0]["error"] == "publish failed"
