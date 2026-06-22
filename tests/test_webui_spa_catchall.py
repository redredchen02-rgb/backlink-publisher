"""SPA catch-all contract tests — Plan 2026-06-18-002 U3.

Hermetic: the SPA dir + the enable flag are monkeypatched, so these pass whether
or not the real bundle has been built (CI's Python job has no Node build step).
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def fake_spa(tmp_path, monkeypatch):
    """Point the SPA route at a tmp bundle (index.html + one asset)."""
    (tmp_path / "index.html").write_text(
        '<!doctype html><div id="app"></div><!--SPA_INDEX_MARKER-->'
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('built-asset')")
    monkeypatch.setattr("webui_app.routes.spa._SPA_DIR", tmp_path)
    return tmp_path


def test_app_404_when_flag_explicitly_off(client, monkeypatch, fake_spa):
    # U8: the SPA is default-ON; BACKLINK_PUBLISHER_SPA=0 is the opt-out. With a
    # built bundle present, only the explicit "0" should fall back to legacy (404).
    monkeypatch.setenv("BACKLINK_PUBLISHER_SPA", "0")
    assert client.get("/app").status_code == 404
    assert client.get("/app/").status_code == 404


def test_app_serves_by_default_without_the_flag(client, monkeypatch, fake_spa):
    # U8: with the flag UNSET, the SPA serves (default-ON) — this is the flip.
    monkeypatch.delenv("BACKLINK_PUBLISHER_SPA", raising=False)
    resp = client.get("/app")
    assert resp.status_code == 200
    assert b"SPA_INDEX_MARKER" in resp.data


def test_app_serves_index_when_enabled(client, monkeypatch, fake_spa):
    monkeypatch.setenv("BACKLINK_PUBLISHER_SPA", "1")
    resp = client.get("/app")
    assert resp.status_code == 200
    assert b"SPA_INDEX_MARKER" in resp.data


def test_app_deep_route_serves_index_fallback(client, monkeypatch, fake_spa):
    """A client-side route (no matching file) returns index.html on hard refresh."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_SPA", "1")
    resp = client.get("/app/dashboard")
    assert resp.status_code == 200
    assert b"SPA_INDEX_MARKER" in resp.data


def test_app_serves_real_asset_not_index(client, monkeypatch, fake_spa):
    monkeypatch.setenv("BACKLINK_PUBLISHER_SPA", "1")
    resp = client.get("/app/assets/app.js")
    assert resp.status_code == 200
    assert b"built-asset" in resp.data
    assert b"SPA_INDEX_MARKER" not in resp.data


def test_app_404_when_enabled_but_not_built(client, monkeypatch, tmp_path):
    monkeypatch.setenv("BACKLINK_PUBLISHER_SPA", "1")
    monkeypatch.setattr("webui_app.routes.spa._SPA_DIR", tmp_path)  # empty -> no index
    assert client.get("/app").status_code == 404


def test_spa_does_not_shadow_api(client, monkeypatch, fake_spa):
    """Registering /app/* must not change the /api/v1 surface."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_SPA", "1")
    assert client.get("/api/v1/health").status_code == 200
