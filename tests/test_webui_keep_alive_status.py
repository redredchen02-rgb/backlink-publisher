"""R3 — keep-alive status view (plan 2026-06-04-001 Unit 4).

The scorecard reads the link.rechecked time series as the liveness authority
(not the stale ledger column), per-target, bleeding pages first, with example.com
test data excluded and a staleness signal when newer publishes are unverified.
"""
__tier__ = "integration"

import json
from datetime import datetime, timedelta

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from webui_app.services.keep_alive import build_keepalive_view

NOW = datetime(2026, 6, 4, 12, 0, 0)
RECENT = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
OLD = (NOW - timedelta(days=5)).isoformat(timespec="seconds")
T_ATTN = "https://51acgs.com/comic/117"
T_OK = "https://51acgs.com/"
T_EX = "https://example.com/article"


def _article(store, live_url, target):
    return store.add_article(
        {"target_urls_json": json.dumps([target]), "live_url": live_url}
    )


def _recheck(store, *, target, article_id, verdict, ts):
    store.append(
        LINK_RECHECKED,
        {"verdict": verdict, "live_url": "x", "platform": "telegraph"},
        target_url=target,
        article_id=article_id,
        ts_utc=ts,
    )


@pytest.fixture
def populated(tmp_path):
    s = EventStore(path=tmp_path / "events.db")
    a1 = _article(s, "https://telegra.ph/a1", T_ATTN)
    a2 = _article(s, "https://taiwanmanga2026.blogspot.com/a2", T_ATTN)
    a3 = _article(s, "https://redredchen01.github.io/a3", T_OK)
    a4 = _article(s, "https://telegra.ph/ex", T_EX)
    # T_ATTN: one alive, one stripped (latest wins over an older alive).
    _recheck(s, target=T_ATTN, article_id=a1, verdict="alive", ts=RECENT)
    _recheck(s, target=T_ATTN, article_id=a2, verdict="alive", ts=OLD)
    _recheck(s, target=T_ATTN, article_id=a2, verdict="link_stripped", ts=RECENT)
    # T_OK: healthy.
    _recheck(s, target=T_OK, article_id=a3, verdict="alive", ts=RECENT)
    # example.com test data — must be excluded.
    _recheck(s, target=T_EX, article_id=a4, verdict="alive", ts=RECENT)
    history = [
        {"id": "h1", "platform": "telegraph", "target_url": T_ATTN,
         "article_urls": ["https://telegra.ph/a1"], "verified_at": RECENT},
        {"id": "h2", "platform": "blogger", "target_url": T_ATTN,
         "article_urls": ["https://taiwanmanga2026.blogspot.com/a2"], "verified_at": RECENT},
        {"id": "h3", "platform": "ghpages", "target_url": T_OK,
         "article_urls": ["https://redredchen01.github.io/a3"], "verified_at": RECENT},
        {"id": "h4", "platform": "telegraph", "target_url": T_EX,
         "article_urls": ["https://telegra.ph/ex"], "verified_at": RECENT},
    ]
    return s, history


def test_per_target_stripped_count_and_strip_rate(populated):
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    attn = next(t for t in view["targets"] if t["target_url"] == T_ATTN)
    assert attn["stripped"] == 1          # latest verdict wins (link_stripped)
    assert attn["rechecked"] == 2
    assert attn["strip_rate"] == 0.5
    assert attn["needs_attention"] is True


def test_recheck_overrides_stale_ledger_liveness(populated):
    # h2's history says verified_at=RECENT (ledger would call it live), but the
    # latest recheck verdict is link_stripped → the view must show it stripped.
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    attn = next(t for t in view["targets"] if t["target_url"] == T_ATTN)
    assert attn["stripped"] >= 1


def test_example_com_excluded(populated):
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    assert all("example.com" not in t["target_url"] for t in view["targets"])


def test_bleeding_targets_sort_first(populated):
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    assert view["targets"][0]["target_url"] == T_ATTN   # needs-attention first
    assert view["targets"][0]["needs_attention"] is True


def test_empty_when_no_recheck_events(tmp_path):
    s = EventStore(path=tmp_path / "e.db")
    view = build_keepalive_view(store=s, history=[], now=NOW)
    assert view["is_empty"] is True
    assert view["targets"] == []


def test_stale_when_publish_newer_than_recheck(populated):
    store, history = populated
    newer = (NOW - timedelta(hours=1)).isoformat(timespec="seconds")
    store.append(PUBLISH_CONFIRMED, {"live_url": "https://telegra.ph/new"},
                 target_url=T_OK, ts_utc=newer)
    view = build_keepalive_view(store=store, history=history, now=NOW)
    assert view["stale"] is True


def test_route_renders():
    # Real path against the sandboxed (empty) store → S0-empty render, HTTP 200.
    from webui_app import create_app

    app = create_app()
    client = app.test_client()
    resp = client.get("/ce:keep-alive")
    assert resp.status_code == 200
    assert "保活".encode() in resp.data
