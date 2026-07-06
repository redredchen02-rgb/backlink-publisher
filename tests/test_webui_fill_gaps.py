"""U4 — Fill Gaps endpoint (plan 2026-06-05-001).

POST /ce:equity-ledger/fill-gaps → missing platforms, deficiency, CLI command.
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch, disable_csrf):
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))
    import webui
    return webui.app.test_client()


def _seed(tmp_path):
    from backlink_publisher.events import EventStore
    from webui_store import history_store
    EventStore().add_article({
        "target_urls_json": json.dumps(["https://site.com/p"]),
        "live_url": "https://medium.com/post1",
        "platform": "medium",
    })
    history_store.save([{
        "id": "h1", "platform": "medium", "target_url": "https://site.com/p",
        "article_urls": ["https://medium.com/post1"], "status": "published",
    }])


def test_fill_gaps_missing_target_url_returns_400(client):
    resp = client.post("/ce:equity-ledger/fill-gaps",
                       json={}, content_type="application/json")
    assert resp.status_code == 400


def test_fill_gaps_unknown_target_returns_404(client):
    resp = client.post("/ce:equity-ledger/fill-gaps",
                       json={"target_url": "https://nope.example.com"},
                       content_type="application/json")
    assert resp.status_code == 404


def test_fill_gaps_returns_gap_data(client, tmp_path):
    _seed(tmp_path)
    resp = client.post("/ce:equity-ledger/fill-gaps",
                       json={"target_url": "https://site.com/p"},
                       content_type="application/json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "missing_platforms" in body
    assert "deficiency" in body
    assert "cli_command" in body
    assert isinstance(body["missing_platforms"], list)


def test_fill_gaps_csrf_required(tmp_path, monkeypatch):
    """Without disable_csrf, a POST without token → 403."""
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))
    import webui
    c = webui.app.test_client()
    resp = c.post("/ce:equity-ledger/fill-gaps",
                  json={"target_url": "https://site.com/p"},
                  content_type="application/json")
    assert resp.status_code == 403
