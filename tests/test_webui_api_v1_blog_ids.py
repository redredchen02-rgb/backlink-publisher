"""Contract for the ``/api/v1`` Blogger blog-ID mapping routes.

Plan 2026-06-18-002 U7 (Settings section 3 slice 6). The cleaning rule (strip /
drop-empty / dedup-by-domain) + the config write moved to the single-source
``BloggerSettingsAPI`` facade; the legacy ``/settings/save-blog-ids`` route (form
parallel-lists → 302 redirect) is covered by ``test_webui_settings_routes.py``.
This guards the JSON path: the read shape, the save round-trip, and that the
cleaning rule holds.
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys

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


def test_get_blog_ids_starts_empty(client):
    resp = client.get("/api/v1/settings/blogger/blog-ids")
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json() == {"blog_ids": {}}


def test_save_then_get_round_trips(client):
    resp = client.post(
        "/api/v1/settings/blogger/blog-ids",
        json={"blog_ids": {"https://a.com": "111", "https://b.com": "222"}},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["ok"] is True
    got = client.get("/api/v1/settings/blogger/blog-ids").get_json()["blog_ids"]
    assert got == {"https://a.com": "111", "https://b.com": "222"}


def test_save_strips_and_drops_blank_pairs(client):
    client.post(
        "/api/v1/settings/blogger/blog-ids",
        json={"blog_ids": {"  https://a.com  ": "  111  ", "": "999", "https://c.com": ""}},
        headers=_headers(),
    )
    got = client.get("/api/v1/settings/blogger/blog-ids").get_json()["blog_ids"]
    assert got == {"https://a.com": "111"}  # stripped; blank domain + blank id dropped


def test_save_replaces_prior_mapping(client):
    client.post("/api/v1/settings/blogger/blog-ids",
                json={"blog_ids": {"https://old.com": "1"}}, headers=_headers())
    client.post("/api/v1/settings/blogger/blog-ids",
                json={"blog_ids": {"https://new.com": "2"}}, headers=_headers())
    got = client.get("/api/v1/settings/blogger/blog-ids").get_json()["blog_ids"]
    assert got == {"https://new.com": "2"}


def test_save_empty_clears_mapping(client):
    client.post("/api/v1/settings/blogger/blog-ids",
                json={"blog_ids": {"https://a.com": "1"}}, headers=_headers())
    resp = client.post("/api/v1/settings/blogger/blog-ids",
                       json={"blog_ids": {}}, headers=_headers())
    assert resp.status_code == 200
    assert client.get("/api/v1/settings/blogger/blog-ids").get_json()["blog_ids"] == {}


def test_save_missing_body_is_a_no_op_save(client):
    resp = client.post("/api/v1/settings/blogger/blog-ids", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
