"""U1 + U2 + U3 — equity ledger Chinese UI, stats bar, gap data, preset chips (plan 2026-06-05-001)."""
from __future__ import annotations

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
        "platform": "medium",
    })
    from webui_store import history_store
    history_store.save([{
        "id": "h1", "platform": "medium", "target_url": "https://site.com/p",
        "article_urls": ["https://medium.com/post1"], "status": "published",
    }])


# ── U1: Chinese UI ────────────────────────────────────────────────────────────

def test_u1_page_title_is_chinese(client):
    """Page renders with Chinese title instead of English."""
    _seed()
    html = client.get("/ce:equity-ledger/jinja").get_data(as_text=True)
    assert "外链权益台账" in html
    # English title must NOT appear
    assert "Backlink Equity Ledger" not in html


def test_u1_stale_label_uses_chinese(client):
    """Stale label uses Chinese (超过 X 天)."""
    _seed()
    html = client.get("/ce:equity-ledger/jinja?stale_days=7").get_data(as_text=True)
    assert "天" in html
    # Old English form must not appear
    assert "stale &gt; 7d" not in html


def test_u1_stats_bar_element_present(client):
    """Stats bar element (#statsBar) is present in the DOM."""
    html = client.get("/ce:equity-ledger/jinja").get_data(as_text=True)
    assert "statsBar" in html


# ── U2: missing_dofollow_platforms in bootstrap data ─────────────────────────

def test_u2_bootstrap_includes_missing_dofollow_platforms(client):
    """Row bootstrap data includes missing_dofollow_platforms list."""
    _seed()
    html = client.get("/ce:equity-ledger/jinja").get_data(as_text=True)
    assert "missing_dofollow_platforms" in html


def test_u2_missing_is_list_of_strings(client):
    """missing_dofollow_platforms is a list of strings in the JSON."""
    _seed()
    html = client.get("/ce:equity-ledger/jinja").get_data(as_text=True)
    # Extract the bootstrap JSON
    marker = "window.__equityLedgerBootstrap = "
    idx = html.index(marker) + len(marker)
    end = html.index(";</script>", idx)
    boot = json.loads(html[idx:end])
    rows = boot.get("rows", [])
    assert rows, "Expected at least one row"
    for row in rows:
        assert "missing_dofollow_platforms" in row
        assert isinstance(row["missing_dofollow_platforms"], list)


# ── U3: preset filter chips in template ──────────────────────────────────────

def test_u3_preset_chips_rendered(client):
    """Template contains preset filter chips with data-preset attributes."""
    html = client.get("/ce:equity-ledger/jinja").get_data(as_text=True)
    assert 'data-preset="all"' in html
    assert 'data-preset="needs-attention"' in html
    assert 'data-preset="weak"' in html
    assert 'data-preset="healthy"' in html


def test_u3_preset_chip_labels_are_chinese(client):
    """Preset chip labels are Chinese."""
    html = client.get("/ce:equity-ledger/jinja").get_data(as_text=True)
    assert "全部" in html
    assert "需关注" in html or "需关注" in html
    assert "健康" in html
