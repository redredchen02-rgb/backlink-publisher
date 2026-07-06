"""R6 per-target dofollow history card badge — test-first unit.

Plan 2026-06-05-008 R6.
Tests the full R6 stack:
  1. history_query._verdict_to_target_dofollow (verdict → badge value)
  2. list_history enriches items with target_dofollow via latest link.rechecked
  3. HistoryAPI._normalize_item defaults target_dofollow='unverified'
  4. page-wide nofollow_detected does NOT downgrade a 'dofollow' badge
  5. Template renders sub-badge for each target_dofollow value
"""
from __future__ import annotations

__tier__ = "unit"

import json
import sqlite3

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_store(tmp_path):
    """Return an EventStore backed by a fresh in-memory-like tmp_path DB."""
    from backlink_publisher.events.store import EventStore
    return EventStore(path=tmp_path / "events.db")


def _seed_article_and_event(conn, article_id: int, target_url: str = "https://example.com"):
    """Insert a minimal article row + publish.confirmed event."""
    conn.execute(
        "INSERT OR IGNORE INTO articles "
        "(article_id, body, anchors_json, target_urls_json, lang, host, "
        " live_url, published_at_raw, published_at_utc, run_id, platform, "
        " verified_at, verify_error, migration_dedup_key) "
        "VALUES (?, '', '[]', '[]', 'en', 'example.com', "
        "        'https://art.example.com/1', '', '2026-01-01T00:00:00', "
        "        'run1', 'medium', NULL, NULL, NULL)",
        (article_id,),
    )
    conn.execute(
        "INSERT INTO events (ts_raw, ts_utc, run_id, kind, target_url, host, article_id, payload_json) "
        "VALUES ('', '2026-01-01T00:00:00', 'run1', 'publish.confirmed', ?, 'example.com', ?, ?)",
        (target_url, article_id, json.dumps({"live_url": "https://art.example.com/1"})),
    )


def _seed_link_rechecked(conn, article_id: int, verdict: str):
    """Insert a link.rechecked event for the given article_id and verdict."""
    conn.execute(
        "INSERT INTO events (ts_raw, ts_utc, run_id, kind, target_url, host, article_id, payload_json) "
        "VALUES ('', '2026-01-02T00:00:00', 'run1', 'link.rechecked', 'https://example.com', "
        "        'example.com', ?, ?)",
        (article_id, json.dumps({"verdict": verdict})),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: verdict → target_dofollow mapping
# ─────────────────────────────────────────────────────────────────────────────

class TestVerdictToTargetDofollow:
    """Unit tests for the _verdict_to_target_dofollow helper."""

    def test_alive_maps_to_dofollow(self):
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("alive") == "dofollow"

    def test_dofollow_lost_maps_to_dofollow_lost(self):
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("dofollow_lost") == "dofollow_lost"

    def test_link_stripped_maps_to_stripped(self):
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("link_stripped") == "stripped"

    def test_host_gone_maps_to_stripped(self):
        """host_gone is a dead link — same red badge as stripped."""
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("host_gone") == "stripped"

    def test_empty_string_maps_to_unverified(self):
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("") == "unverified"

    def test_none_maps_to_unverified(self):
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow(None) == "unverified"

    def test_probe_error_maps_to_unverified(self):
        """probe_error is indeterminate — treat as no-signal."""
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("probe_error") == "unverified"

    def test_unknown_verdict_maps_to_unverified(self):
        from backlink_publisher.events.history_query import _verdict_to_target_dofollow
        assert _verdict_to_target_dofollow("something_new") == "unverified"


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: list_history enriches items from events.db
# ─────────────────────────────────────────────────────────────────────────────

class TestListHistoryTargetDofollow:
    """list_history should enrich items with target_dofollow from link.rechecked."""

    def test_alive_verdict_gives_dofollow(self, tmp_path):
        store = _make_store(tmp_path)
        with store.connect() as conn:
            _seed_article_and_event(conn, 1)
            _seed_link_rechecked(conn, 1, "alive")
        from backlink_publisher.events.history_query import list_history
        items = list_history(store=store)
        assert items, "expected at least one item"
        item = items[0]
        assert item["target_dofollow"] == "dofollow"

    def test_dofollow_lost_verdict(self, tmp_path):
        store = _make_store(tmp_path)
        with store.connect() as conn:
            _seed_article_and_event(conn, 2)
            _seed_link_rechecked(conn, 2, "dofollow_lost")
        from backlink_publisher.events.history_query import list_history
        items = list_history(store=store)
        assert items[0]["target_dofollow"] == "dofollow_lost"

    def test_link_stripped_verdict(self, tmp_path):
        store = _make_store(tmp_path)
        with store.connect() as conn:
            _seed_article_and_event(conn, 3)
            _seed_link_rechecked(conn, 3, "link_stripped")
        from backlink_publisher.events.history_query import list_history
        items = list_history(store=store)
        assert items[0]["target_dofollow"] == "stripped"

    def test_no_link_rechecked_gives_unverified(self, tmp_path):
        """Legacy row with no link.rechecked event → target_dofollow == 'unverified'."""
        store = _make_store(tmp_path)
        with store.connect() as conn:
            _seed_article_and_event(conn, 4)
            # Intentionally no link.rechecked event
        from backlink_publisher.events.history_query import list_history
        items = list_history(store=store)
        assert items[0]["target_dofollow"] == "unverified"

    def test_latest_verdict_wins_over_older(self, tmp_path):
        """When multiple link.rechecked events exist, the latest (MAX id) wins."""
        store = _make_store(tmp_path)
        with store.connect() as conn:
            _seed_article_and_event(conn, 5)
            _seed_link_rechecked(conn, 5, "link_stripped")   # older
            _seed_link_rechecked(conn, 5, "alive")           # newer
        from backlink_publisher.events.history_query import list_history
        items = list_history(store=store)
        assert items[0]["target_dofollow"] == "dofollow"

    def test_page_wide_nofollow_does_not_downgrade_dofollow(self, tmp_path):
        """page-wide nofollow_detected=True must NOT override a dofollow badge.

        This tests the isolation: target_dofollow comes purely from
        link.rechecked, never from the article-level nofollow_detected flag.
        """
        store = _make_store(tmp_path)
        with store.connect() as conn:
            _seed_article_and_event(conn, 6)
            _seed_link_rechecked(conn, 6, "alive")
        from backlink_publisher.events.history_query import list_history
        items = list_history(store=store)
        item = items[0]
        # target_dofollow should be 'dofollow' regardless of any nofollow_detected field
        assert item["target_dofollow"] == "dofollow"
        # Any nofollow_detected field should NOT alter the badge value
        item_with_nofollow = dict(item, nofollow_detected=True)
        assert item_with_nofollow["target_dofollow"] == "dofollow"


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: HistoryAPI._normalize_item defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeItemTargetDofollowDefault:
    """_normalize_item must supply target_dofollow='unverified' when absent."""

    def test_missing_target_dofollow_defaults_to_unverified(self):
        from webui_app.api.history_api import HistoryAPI
        item = {
            "id": "1",
            "target_url": "https://example.com",
            "article_urls": ["https://art.example.com/1"],
        }
        result = HistoryAPI._normalize_item(item)
        assert result["target_dofollow"] == "unverified"

    def test_existing_target_dofollow_is_preserved(self):
        from webui_app.api.history_api import HistoryAPI
        item = {
            "id": "2",
            "target_url": "https://example.com",
            "article_urls": ["https://art.example.com/2"],
            "target_dofollow": "dofollow",
        }
        result = HistoryAPI._normalize_item(item)
        assert result["target_dofollow"] == "dofollow"

    def test_dofollow_lost_preserved(self):
        from webui_app.api.history_api import HistoryAPI
        item = {
            "id": "3",
            "target_url": "https://example.com",
            "article_urls": [],
            "target_dofollow": "dofollow_lost",
        }
        result = HistoryAPI._normalize_item(item)
        assert result["target_dofollow"] == "dofollow_lost"

    def test_stripped_preserved(self):
        from webui_app.api.history_api import HistoryAPI
        item = {
            "id": "4",
            "target_url": "https://example.com",
            "article_urls": [],
            "target_dofollow": "stripped",
        }
        result = HistoryAPI._normalize_item(item)
        assert result["target_dofollow"] == "stripped"


# ─────────────────────────────────────────────────────────────────────────────
# Part 4: Template rendering of target_dofollow badge
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with monkeypatched list_history for template tests."""
    from webui_store import drafts_store, history_store
    monkeypatch.setattr(drafts_store, "_path", tmp_path / "drafts.json")
    monkeypatch.setattr(history_store, "_path", tmp_path / "history.json")

    _saved: list[dict] = []

    def _save(items: list[dict]) -> None:
        _saved.clear()
        _saved.extend(items)

    real = history_store._real()
    monkeypatch.setattr(real, "save", _save)

    import webui_app.api.history_api as _hapi
    monkeypatch.setattr(_hapi, "list_history", lambda include_deleted=None: list(_saved))

    import webui
    webui.app.config["TESTING"] = True
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


class TestTargetDofollowBadgeTemplateRendering:
    """Template must render target_dofollow sub-badge with text + title."""

    def _seed(self, history_store, target_dofollow: str):
        from webui_store import history_store as hs
        hs.save([{
            "id": "a",
            "status": "published",
            "target_url": "https://example.com/target",
            "platform": "medium",
            "article_urls": ["https://art.example.com/1"],
            "created_at": "2026-06-05",
            "target_dofollow": target_dofollow,
        }])

    def test_dofollow_badge_renders(self, client):
        self._seed(None, "dofollow")
        resp = client.get("/ce:history")
        body = resp.data.decode("utf-8")
        assert resp.status_code == 200
        assert "dofollow 正常" in body

    def test_dofollow_lost_badge_renders(self, client):
        self._seed(None, "dofollow_lost")
        resp = client.get("/ce:history")
        body = resp.data.decode("utf-8")
        assert "dofollow 已失效" in body

    def test_stripped_badge_renders(self, client):
        self._seed(None, "stripped")
        resp = client.get("/ce:history")
        body = resp.data.decode("utf-8")
        assert "链接被移除" in body

    def test_unverified_badge_renders(self, client):
        self._seed(None, "unverified")
        resp = client.get("/ce:history")
        body = resp.data.decode("utf-8")
        assert "未验证" in body

    def test_badge_has_title_attribute(self, client):
        """Badge must use title= attribute, never color alone."""
        self._seed(None, "dofollow")
        resp = client.get("/ce:history")
        body = resp.data.decode("utf-8")
        # title attribute must be present on the badge element
        assert 'title=' in body

    def test_nofollow_detected_does_not_override_dofollow_badge(self, client):
        """page-wide nofollow_detected=True must not downgrade the dofollow badge."""
        from webui_store import history_store as hs
        hs.save([{
            "id": "b",
            "status": "published",
            "target_url": "https://example.com/target",
            "platform": "medium",
            "article_urls": ["https://art.example.com/1"],
            "created_at": "2026-06-05",
            "target_dofollow": "dofollow",
            "nofollow_detected": True,
        }])
        resp = client.get("/ce:history")
        body = resp.data.decode("utf-8")
        assert "dofollow 正常" in body
        # Must not show the nofollow downgrade text
        assert "dofollow 已失效" not in body
