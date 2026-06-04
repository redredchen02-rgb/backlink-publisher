"""plan 2026-06-04-002 Unit 1 — POST /ce:keep-alive/recheck route."""
__tier__ = "integration"

import json

import pytest

from backlink_publisher.events import EventStore

T = "https://51acgs.com/comic/test"


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


def _seed(tmp_path=None):
    store = EventStore()
    store.add_article({"target_urls_json": json.dumps([T]),
                       "live_url": "https://medium.com/ka1"})
    from webui_store import history_store
    history_store.save([
        {"id": "ka1", "platform": "medium", "target_url": T,
         "article_urls": ["https://medium.com/ka1"],
         "status": "published_unverified", "title": "t"},
    ])


def _alive_probe(*a, **k):
    return {
        "page_readable": True, "target_anchor_found": True,
        "target_is_nofollow": False, "target_rel": None,
        "target_anchor_text": None, "reason": None, "marker_present": None,
    }


# ── happy path ─────────────────────────────────────────────────────────────

def test_post_redirects_to_keep_alive_with_success_flash(client, monkeypatch):
    _seed()
    monkeypatch.setattr(
        "backlink_publisher.publishing.adapters.link_attr_verifier.inspect_target_anchor",
        _alive_probe,
    )
    resp = client.post("/ce:keep-alive/recheck")
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert "/ce:keep-alive" in loc
    assert "flash_type=success" in loc
    assert "flash_msg=" in loc


# ── empty store ─────────────────────────────────────────────────────────────

def test_empty_store_redirects_with_info_flash(client):
    # No history seeded — route should redirect without calling recheck.
    resp = client.post("/ce:keep-alive/recheck")
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert "flash_type=info" in loc


# ── GET with flash params ────────────────────────────────────────────────────

def test_get_renders_flash_alert(client):
    resp = client.get("/ce:keep-alive?flash_type=success&flash_msg=已核实+3+条")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "alert-success" in body
    assert "已核实" in body


def test_get_no_flash_shows_no_alert(client):
    resp = client.get("/ce:keep-alive")
    assert resp.status_code == 200
    body = resp.data.decode()
    # The flash block has a btn-close dismiss button; staleBanner is always in HTML
    # but hidden (d-none) and has no btn-close — so btn-close absence = no flash block.
    assert 'data-bs-dismiss="alert"' not in body


# ── button not disabled ──────────────────────────────────────────────────────

def test_recheck_button_is_enabled(client):
    resp = client.get("/ce:keep-alive")
    assert resp.status_code == 200
    body = resp.data.decode()
    # Button must not carry the disabled attribute.
    assert 'id="recheckBtn"' in body
    assert 'disabled' not in body.split('id="recheckBtn"')[1].split('>')[0]
