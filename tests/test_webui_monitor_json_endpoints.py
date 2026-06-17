"""U6 — read-only JSON endpoints for the monitor hub (equity + optimization).

Both must derive from the same source as their HTML pages (no drift), return an
``ok`` flag, fail open (never 500), and return empty lists (not null) when there
is no data. Plan 2026-06-17-001 U6.
"""
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


def _seed_equity():
    EventStore().add_article({
        "target_urls_json": json.dumps(["https://site.com/p"]),
        "live_url": "https://medium.com/post1",
    })
    from webui_store import history_store
    history_store.save([{
        "id": "h1", "platform": "medium", "target_url": "https://site.com/p",
        "article_urls": ["https://medium.com/post1"], "status": "published",
    }])


# ── equity JSON ────────────────────────────────────────────────────────────

def test_equity_json_empty_returns_ok_and_empty_list(client):
    resp = client.get("/api/equity-ledger")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["rows"] == []          # empty list, not null
    assert data["stale_count"] == 0


def test_equity_json_matches_html_engine(client):
    _seed_equity()
    from backlink_publisher.ledger import build_ledger
    engine_rows = build_ledger()
    data = client.get("/api/equity-ledger").get_json()
    assert data["ok"] is True
    assert len(data["rows"]) == len(engine_rows) == 1
    assert data["rows"][0]["target_url"] == engine_rows[0].target_url
    # carries the derived field the HTML page also computes
    assert "missing_dofollow_platforms" in data["rows"][0]


def test_equity_json_honors_stale_days(client):
    resp = client.get("/api/equity-ledger?stale_days=7")
    assert resp.get_json()["stale_days"] == 7


# ── optimization JSON ──────────────────────────────────────────────────────

def test_optimization_json_returns_ok_and_list(client):
    resp = client.get("/api/optimization-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["platforms"], list)      # list (possibly empty), never null
    assert isinstance(data["all_platforms"], list)


def test_optimization_json_shares_summary_source(client):
    # Parity: endpoint returns the same shape OptimizationState.to_summary() gives
    # (the source command_center + the HTML page also read).
    from backlink_publisher.optimization import OptimizationState
    expected = OptimizationState().to_summary().get("platforms", [])
    data = client.get("/api/optimization-status").get_json()
    assert data["platforms"] == expected
