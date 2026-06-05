"""Unit — equity-ledger Fill Gaps POST (U4, Plan 2026-06-05-001)."""
__tier__ = "unit"

import json

import pytest

from backlink_publisher.events import EventStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))
    import webui
    webui.app.config["TESTING"] = True
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


def _seed():
    EventStore().add_article({
        "target_urls_json": json.dumps(["https://site.com/p"]),
        "live_url": "https://medium.com/post1",
    })
    from webui_store import history_store
    history_store.save([{
        "id": "h1", "platform": "medium", "target_url": "https://site.com/p",
        "article_urls": ["https://medium.com/post1"], "status": "published_unverified",
        "title": "t",
    }])


def test_fill_gaps_returns_gap_analysis(client):
    _seed()
    resp = client.post(
        "/ce:equity-ledger/fill-gaps",
        data=json.dumps({"target_url": "https://site.com/p"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["target_url"] == "https://site.com/p"
    assert isinstance(body["missing_platforms"], list)
    assert body["deficiency"] >= 0
    assert "cli_command" in body
    assert "plan-gap" in body["cli_command"]
    assert "site.com/p" in body["cli_command"]


def test_fill_gaps_missing_target_url_400(client):
    resp = client.post(
        "/ce:equity-ledger/fill-gaps",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_fill_gaps_unknown_target_404(client):
    _seed()
    resp = client.post(
        "/ce:equity-ledger/fill-gaps",
        data=json.dumps({"target_url": "https://nope.example/x"}),
        content_type="application/json",
    )
    assert resp.status_code == 404
