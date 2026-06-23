"""Contract tests for ``/api/v1/sites*`` — Plan 2026-06-18-002 U7 (sites page).

Hermetic: the module-level ``SitesAPI`` instance is patched so we exercise the
HTTP binding + the error mapping (validation → 422 with field errors;
out-of-range/missing autopilot input → 422; scheduler-sync failure → 502;
scrape fetch failure → 200 with status=error) without touching config I/O,
APScheduler, or the network.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.get/post("/api/v1/sites/...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.sites as sites_mod

PROBLEM_CT = "application/problem+json"

_SITE = {
    "label": "example.com",
    "main_url": "https://example.com/",
    "autopilot_enabled": False,
    "autopilot_interval": 86400,
    "alert_pending": False,
    "next_run_time_iso": None,
}


def _patch(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(sites_mod._api, name, fn)


# ── reads ────────────────────────────────────────────────────────────────────


def test_webui_sites_list_returns_items_envelope(client, monkeypatch):
    _patch(monkeypatch, list_sites=lambda: [_SITE])
    resp = client.get("/api/v1/sites")
    assert resp.status_code == 200
    assert resp.get_json()["items"] == [_SITE]


def test_webui_sites_widgets_returns_plan_gap_and_alert(client, monkeypatch):
    _patch(
        monkeypatch,
        widgets=lambda: {
            "plan_gap": {"status": "ok", "candidate_count": 3, "target_count": 2},
            "citation_alert": {"ts": "2026-06-18T00:00:00Z"},
        },
    )
    resp = client.get("/api/v1/sites/widgets")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["plan_gap"]["candidate_count"] == 3
    assert body["citation_alert"]["ts"].startswith("2026-06-18")


def test_webui_sites_form_returns_prefill(client, monkeypatch):
    form = {"main_url": "https://example.com/", "list_url": "https://example.com/list"}
    _patch(monkeypatch, get_form=lambda domain: form if domain else None)
    resp = client.get("/api/v1/sites/form?domain=https://example.com")
    assert resp.status_code == 200
    assert resp.get_json()["form"]["list_url"] == "https://example.com/list"


def test_webui_sites_form_unknown_domain_returns_null(client, monkeypatch):
    _patch(monkeypatch, get_form=lambda domain: None)
    resp = client.get("/api/v1/sites/form?domain=https://nope.com")
    assert resp.status_code == 200
    assert resp.get_json()["form"] is None


# ── save (validation + derivation) ───────────────────────────────────────────


def test_webui_sites_save_valid_returns_refreshed_list(client, monkeypatch):
    _patch(
        monkeypatch,
        save_three_url=lambda data: {
            "ok": True, "saved_domain": "https://example.com", "autofilled": ["branded_pool"],
        },
        list_sites=lambda: [_SITE],
    )
    resp = client.post("/api/v1/sites/save", json={"main_url": "https://example.com/"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["saved_domain"] == "https://example.com"
    assert body["autofilled"] == ["branded_pool"]
    assert body["items"] == [_SITE]


def test_webui_sites_save_invalid_returns_422_with_field_errors(client, monkeypatch):
    _patch(
        monkeypatch,
        save_three_url=lambda data: {
            "ok": False, "errors": {"main_url": "必须 https", "list_url": "必须 https"},
        },
    )
    resp = client.post("/api/v1/sites/save", json={"main_url": "http://insecure.com/"})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    body = resp.get_json()
    fields = {e["field"] for e in body["errors"]}
    assert fields == {"main_url", "list_url"}


# ── autopilot ────────────────────────────────────────────────────────────────


def test_webui_sites_autopilot_enable_returns_refreshed_list(client, monkeypatch):
    _patch(
        monkeypatch,
        set_autopilot=lambda url, enabled, interval: {
            "ok": True, "site_url": url, "enabled": enabled,
            "next_run_time": "2026-06-19T09:00:00+00:00", "last_run": None,
        },
        list_sites=lambda: [{**_SITE, "autopilot_enabled": True}],
    )
    resp = client.post(
        "/api/v1/sites/autopilot",
        json={"site_url": "https://example.com/", "enabled": True, "interval_seconds": 86400},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["enabled"] is True
    assert body["next_run_time"].startswith("2026-06-19")
    assert body["items"][0]["autopilot_enabled"] is True


def test_webui_sites_autopilot_bad_interval_returns_422(client, monkeypatch):
    _patch(
        monkeypatch,
        set_autopilot=lambda url, enabled, interval: {
            "ok": False, "error_code": "INVALID_INTERVAL", "detail": "out of range",
        },
    )
    resp = client.post(
        "/api/v1/sites/autopilot",
        json={"site_url": "https://example.com/", "enabled": True, "interval_seconds": 10},
    )
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "invalid_request"


def test_webui_sites_autopilot_missing_site_url_returns_422(client, monkeypatch):
    _patch(
        monkeypatch,
        set_autopilot=lambda url, enabled, interval: {
            "ok": False, "error_code": "MISSING_SITE_URL",
        },
    )
    resp = client.post("/api/v1/sites/autopilot", json={"enabled": True})
    assert resp.status_code == 422


def test_webui_sites_autopilot_scheduler_failure_returns_502(client, monkeypatch):
    # Store was rolled back — hard failure, nothing persisted.
    _patch(
        monkeypatch,
        set_autopilot=lambda url, enabled, interval: {
            "ok": False, "error_code": "SCHEDULER_SYNC_FAILED", "detail": "APScheduler error",
        },
    )
    resp = client.post(
        "/api/v1/sites/autopilot",
        json={"site_url": "https://example.com/", "enabled": True, "interval_seconds": 86400},
    )
    assert resp.status_code == 502
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["error_class"] == "scheduler_sync_failed"


# ── scrape preview ───────────────────────────────────────────────────────────


def test_webui_sites_scrape_preview_ok(client, monkeypatch):
    _patch(
        monkeypatch,
        scrape_preview=lambda url: {
            "status": "ok", "title": "T", "description": "D", "h1": "H",
        },
    )
    resp = client.get("/api/v1/sites/scrape-preview?url=https://example.com/work/1")
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "T"


def test_webui_sites_scrape_preview_fetch_error_is_200(client, monkeypatch):
    # A fetch/parse failure is an inline hint (200 + status=error), not a transport error.
    _patch(monkeypatch, scrape_preview=lambda url: {"status": "error", "reason": "timeout"})
    resp = client.get("/api/v1/sites/scrape-preview?url=https://example.com/work/1")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"


def test_webui_sites_scrape_preview_missing_url_returns_422(client):
    resp = client.get("/api/v1/sites/scrape-preview")
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
