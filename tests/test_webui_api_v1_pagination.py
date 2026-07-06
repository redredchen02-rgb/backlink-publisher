"""Contract tests for incremental `limit`/`offset` pagination on the
``/api/v1/history`` and ``/api/v1/drafts`` list endpoints (Plan
2026-07-02-001 U5).

Hermetic: module-level ``_api`` facade instances are patched, mirroring
test_webui_api_v1_history.py's convention.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.get("/api/v1/...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.drafts as drafts_mod
import webui_app.api.v1.history as history_mod

PROBLEM_CT = "application/problem+json"

_ITEMS = [{"id": str(i)} for i in range(120)]


def _patch_history(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(history_mod._api, name, fn)


def _patch_drafts(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(drafts_mod._api, name, fn)


# ── history ────────────────────────────────────────────────────────────────


def test_webui_history_list_no_params_returns_flat_envelope(client, monkeypatch):
    """Old clients don't break: no `limit` -> unchanged flat {items} shape."""
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == _ITEMS
    assert "total" not in body
    assert "limit" not in body
    assert "offset" not in body


def test_webui_history_list_second_page_envelope(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=50&offset=50")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == _ITEMS[50:100]
    assert body["total"] == 120
    assert body["limit"] == 50
    assert body["offset"] == 50


def test_webui_history_list_offset_beyond_total_is_empty_page(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=50&offset=500")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == []
    assert body["total"] == 120


def test_webui_history_list_limit_zero_is_a_valid_empty_page(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=0")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == []
    assert body["total"] == 120
    assert body["limit"] == 0


def test_webui_history_list_negative_limit_returns_400(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=-1")
    assert resp.status_code == 400
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_webui_history_list_negative_offset_returns_400(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=10&offset=-1")
    assert resp.status_code == 400


def test_webui_history_list_non_numeric_limit_returns_400(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=abc")
    assert resp.status_code == 400


def test_webui_history_list_oversized_limit_returns_400(client, monkeypatch):
    _patch_history(monkeypatch, list=lambda: _ITEMS)
    resp = client.get("/api/v1/history?limit=100000")
    assert resp.status_code == 400


# ── drafts ─────────────────────────────────────────────────────────────────


def test_webui_drafts_list_no_params_returns_flat_envelope(client, monkeypatch):
    _patch_drafts(monkeypatch, list_all=lambda: _ITEMS)
    resp = client.get("/api/v1/drafts")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == _ITEMS
    assert "total" not in body


def test_webui_drafts_list_second_page_envelope(client, monkeypatch):
    _patch_drafts(monkeypatch, list_all=lambda: _ITEMS)
    resp = client.get("/api/v1/drafts?limit=50&offset=50")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"] == _ITEMS[50:100]
    assert body["total"] == 120
    assert body["limit"] == 50
    assert body["offset"] == 50


def test_webui_drafts_list_negative_limit_returns_400(client, monkeypatch):
    _patch_drafts(monkeypatch, list_all=lambda: _ITEMS)
    resp = client.get("/api/v1/drafts?limit=-5")
    assert resp.status_code == 400
