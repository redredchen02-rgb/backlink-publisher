"""Contract tests for ``/api/v1/profiles*`` — Plan 2026-06-18-002 U7 (profiles CRUD).

Hermetic: the module-level ``profiles_store`` is patched with an in-memory fake
so we exercise the HTTP binding + the name-keyed upsert/delete + the refreshed
``{items}`` envelope without touching the real SQLite-backed store.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.get/post("/api/v1/profiles...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.profiles as profiles_mod

PROBLEM_CT = "application/problem+json"


class _FakeStore:
    """Minimal load()/update() stand-in for the profiles_store singleton."""

    def __init__(self, rows):
        self._rows = list(rows)

    def load(self):
        return [dict(r) for r in self._rows]

    def update(self, fn):
        self._rows = fn([dict(r) for r in self._rows])
        return self._rows


def _install(monkeypatch, rows):
    fake = _FakeStore(rows)
    monkeypatch.setattr(profiles_mod, "_store", fake)
    return fake


def test_webui_profiles_list_returns_items_envelope(client, monkeypatch):
    _install(monkeypatch, [{"name": "p1", "platform": "blogger"}])
    resp = client.get("/api/v1/profiles")
    assert resp.status_code == 200
    assert resp.get_json()["items"][0]["name"] == "p1"


def test_webui_profiles_save_inserts_new_profile(client, monkeypatch):
    _install(monkeypatch, [])
    resp = client.post("/api/v1/profiles/save", json={
        "name": "preset-a", "platform": "velog", "language": "ko-KR",
    })
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert items[0]["name"] == "preset-a"
    assert items[0]["platform"] == "velog"
    assert items[0]["language"] == "ko-KR"


def test_webui_profiles_save_upserts_existing_by_name(client, monkeypatch):
    _install(monkeypatch, [{"name": "preset-a", "platform": "blogger", "language": "zh-CN"}])
    resp = client.post("/api/v1/profiles/save", json={"name": "preset-a", "platform": "medium"})
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) == 1  # upsert, not append
    assert items[0]["platform"] == "medium"


def test_webui_profiles_save_missing_name_returns_422(client, monkeypatch):
    _install(monkeypatch, [])
    resp = client.post("/api/v1/profiles/save", json={"platform": "blogger"})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_webui_profiles_delete_removes_by_name(client, monkeypatch):
    _install(monkeypatch, [{"name": "p1"}, {"name": "p2"}])
    resp = client.post("/api/v1/profiles/delete", json={"name": "p1"})
    assert resp.status_code == 200
    names = {p["name"] for p in resp.get_json()["items"]}
    assert names == {"p2"}


def test_webui_profiles_delete_missing_name_returns_422(client, monkeypatch):
    _install(monkeypatch, [{"name": "p1"}])
    resp = client.post("/api/v1/profiles/delete", json={})
    assert resp.status_code == 422
