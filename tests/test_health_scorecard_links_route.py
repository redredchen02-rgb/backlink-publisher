"""/ce:health/scorecard/<channel>/links — per-link drawer data route (Plan
2026-06-05-009 U2).

GET-only, read-only, fail-open with an explicit ``ok`` flag so the client can
distinguish a legitimately-empty channel ({ok:true, links:[]}) from a backend
error ({ok:false, links:[]}).
"""
from __future__ import annotations

__tier__ = "unit"

from datetime import datetime, timezone

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck import verdicts

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _seed(live_url, verdict, *, platform="telegraph", target="https://51acgs.com/c/1/"):
    EventStore().append(
        LINK_RECHECKED,
        {"verdict": verdict, "platform": platform, "live_url": live_url},
        target_url=target,
        ts_utc=NOW.isoformat(),
    )


def test_happy_path_returns_per_link_rows(client):
    _seed("https://telegra.ph/a", verdicts.ALIVE, platform="telegraph")
    _seed("https://telegra.ph/b", verdicts.LINK_STRIPPED, platform="telegraph")
    resp = client.get("/ce:health/scorecard/telegraph/links")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    urls = {r["live_url"] for r in body["links"]}
    assert urls == {"https://telegra.ph/a", "https://telegra.ph/b"}
    row = next(r for r in body["links"] if r["live_url"] == "https://telegra.ph/b")
    assert row["verdict"] == verdicts.LINK_STRIPPED
    assert set(row) == {
        "live_url", "target_url", "channel", "verdict",
        "last_recheck_ts", "dofollow_state", "anchor_drift",
    }


def test_unknown_channel_is_empty_not_error(client):
    resp = client.get("/ce:health/scorecard/nonexistent/links")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": True, "links": []}


def test_other_channel_not_leaked(client):
    _seed("https://telegra.ph/a", verdicts.ALIVE, platform="telegraph")
    body = client.get("/ce:health/scorecard/blogger/links").get_json()
    assert body == {"ok": True, "links": []}


def test_fails_open_with_ok_false_on_error(client, monkeypatch):
    import backlink_publisher.scorecard.links as links_mod

    def _boom(*a, **k):
        raise RuntimeError("read boom")

    monkeypatch.setattr(links_mod, "derive_links_by_channel", _boom)
    resp = client.get("/ce:health/scorecard/telegraph/links")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": False, "links": []}


def test_weird_channel_param_does_not_500(client):
    resp = client.get("/ce:health/scorecard/..%2f..%2fetc/links")
    assert resp.status_code in (200, 404)  # dict lookup is injection-safe; never 500
