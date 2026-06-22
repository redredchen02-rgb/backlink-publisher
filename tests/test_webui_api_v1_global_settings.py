"""Contract for the ``/api/v1`` global settings saves (keywords + schedule).

Plan 2026-06-18-002 U7 (Settings, last backend piece). The keyword-pool and
schedule saves were ported HTML→JSON via the single-source ``GlobalSettingsAPI``
facade; the legacy ``/settings/{save-target-keywords,schedule}`` routes (302
flash-redirect) are covered by ``test_webui_settings_routes.py``. This suite guards
the JSON path: a save returns ``{ok, message}``, a >60-char keyword is a 422
problem+json, and a non-numeric schedule value is a 422 — all without writing
0600 credential files (these are global config writes, no inline guard).
"""

from __future__ import annotations

__tier__ = "integration"

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSRF = "test-csrf-token"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["csrf_token"] = CSRF
    return c


def _headers():
    return {"X-CSRFToken": CSRF}


# ── GET hydration (the SPA settings page reads these) ────────────────────────


def test_get_keywords_returns_targets_and_pools(client):
    """Round-trip: a saved pool surfaces under GET, and its domain is a target."""
    client.post(
        "/api/v1/settings/keywords",
        json={"pools": {"https://x.com/": ["alpha", "beta"]}},
        headers=_headers(),
    )
    resp = client.get("/api/v1/settings/keywords")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert "targets" in body and "pools" in body
    assert ["alpha", "beta"] in body["pools"].values()
    # the pooled domain is among the known targets
    assert any(d in body["targets"] for d in body["pools"])


def test_get_schedule_returns_current_settings(client):
    client.post(
        "/api/v1/settings/schedule",
        json={"min_interval_hours": 8, "jitter_minutes": 15},
        headers=_headers(),
    )
    resp = client.get("/api/v1/settings/schedule")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["min_interval_hours"] == 8
    assert body["jitter_minutes"] == 15


# ── keywords ─────────────────────────────────────────────────────────────────


def test_save_keywords_ok(client, tmp_path):
    resp = client.post(
        "/api/v1/settings/keywords",
        json={"pools": {"https://x.com/": ["seo anchor", "another anchor"]}},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    # persisted into config (save_config normalizes the domain key, e.g. strips a
    # trailing slash — assert on the value, not the exact normalized key).
    from backlink_publisher.config import load_config
    cfg = load_config()
    assert ["seo anchor", "another anchor"] in cfg.target_anchor_keywords.values()


def test_save_keywords_dedup_message(client):
    resp = client.post(
        "/api/v1/settings/keywords",
        json={"pools": {"https://x.com/": ["dup", "dup", "unique"]}},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert "去重" in resp.get_json()["message"]


def test_save_keywords_oversize_is_422(client):
    resp = client.post(
        "/api/v1/settings/keywords",
        json={"pools": {"https://x.com/": ["X" * 100]}},
        headers=_headers(),
    )
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")


def test_save_keywords_missing_pools_is_ok_noop(client):
    """No ``pools`` key → empty mapping → a valid (empty) save, not a 500."""
    resp = client.post("/api/v1/settings/keywords", json={}, headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


# ── schedule ─────────────────────────────────────────────────────────────────


def test_save_schedule_ok(client):
    resp = client.post(
        "/api/v1/settings/schedule",
        json={"min_interval_hours": 6, "jitter_minutes": 45},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_save_schedule_non_numeric_is_422(client):
    resp = client.post(
        "/api/v1/settings/schedule",
        json={"min_interval_hours": "not-a-number"},
        headers=_headers(),
    )
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith("application/problem+json")
