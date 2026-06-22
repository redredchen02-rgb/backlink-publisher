"""Contract tests for ``/api/v1/schedule`` — Plan 2026-06-18-002 U7 (schedule page).

Hermetic: the module-level ``list_scheduled`` query is patched so we exercise the
HTTP binding + the fail-soft envelope (a query failure degrades to an empty list)
without touching drafts_store.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.get("/api/v1/schedule")`` call.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.schedule as schedule_mod

_ITEM = {
    "id": "ab12",
    "title": "Hello",
    "target_url": "https://a.com/",
    "platform": "velog",
    "scheduled_at": "2026-06-20T09:00",
    "created_at": "2026-06-18 10:00",
    "status": "scheduled",
}


def test_webui_schedule_returns_items_envelope(client, monkeypatch):
    monkeypatch.setattr(schedule_mod, "list_scheduled", lambda: {"ok": True, "items": [_ITEM]})
    resp = client.get("/api/v1/schedule")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == [_ITEM]


def test_webui_schedule_empty_is_empty_list(client, monkeypatch):
    monkeypatch.setattr(schedule_mod, "list_scheduled", lambda: {"ok": True, "items": []})
    resp = client.get("/api/v1/schedule")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == []


def test_webui_schedule_query_failure_degrades_to_empty(client, monkeypatch):
    # Fail-soft: a read failure is a 200 with an empty list, not a transport error.
    monkeypatch.setattr(
        schedule_mod, "list_scheduled",
        lambda: {"ok": False, "error": "boom", "items": []},
    )
    resp = client.get("/api/v1/schedule")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == []
