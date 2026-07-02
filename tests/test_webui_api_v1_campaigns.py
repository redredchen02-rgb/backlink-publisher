"""Contract tests for ``/api/v1/campaigns*`` — Plan 2026-06-18-002 U7 (batch_campaign).

Hermetic: the module-level ``CampaignAPI`` instance is patched so we exercise the
HTTP binding + the error mapping (field validation → 422 with errors[]; success →
{campaign_id}) without touching campaign_store / the registry / the worker.

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.get/post("/api/v1/campaigns...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.campaigns as campaigns_mod

PROBLEM_CT = "application/problem+json"


def _patch(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(campaigns_mod._api, name, fn)


def test_webui_campaigns_form_returns_platforms_and_partition(client, monkeypatch):
    _patch(
        monkeypatch,
        form_bootstrap=lambda: {
            "platforms": ["blogger", "velog"],
            "publish_partition": {"main": [["blogger", {}, False]], "extension_count": 1},
        },
    )
    resp = client.get("/api/v1/campaigns/form")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["platforms"] == ["blogger", "velog"]
    assert body["publish_partition"]["extension_count"] == 1


def test_webui_campaigns_form_partition_null_falls_back(client, monkeypatch):
    _patch(monkeypatch, form_bootstrap=lambda: {"platforms": ["blogger"], "publish_partition": None})
    resp = client.get("/api/v1/campaigns/form")
    assert resp.status_code == 200
    assert resp.get_json()["publish_partition"] is None


def test_webui_campaigns_create_valid_returns_campaign_id(client, monkeypatch):
    _patch(monkeypatch, create=lambda data: {"ok": True, "campaign_id": "camp-123"})
    resp = client.post("/api/v1/campaigns", json={
        "seeds": '{"seed_text": "x"}', "platforms": ["blogger"], "mode": "draft",
    })
    assert resp.status_code == 200
    assert resp.get_json()["campaign_id"] == "camp-123"


def test_webui_campaigns_create_invalid_returns_422_with_field_errors(client, monkeypatch):
    _patch(
        monkeypatch,
        create=lambda data: {
            "ok": False,
            "errors": {"seeds": "至少输入一条 seed（每行一条 JSON）", "platforms": "至少选择一个平台"},
        },
    )
    resp = client.post("/api/v1/campaigns", json={"seeds": "", "platforms": []})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    fields = {e["field"] for e in resp.get_json()["errors"]}
    assert fields == {"seeds", "platforms"}


# --------------------------------------------------------------------------- #
# D2a signal round-trip: every test above patches the module-level ``_api``
# instance (per the module docstring), so none of them drive the real
# ``CampaignAPI().create()`` -> ``campaign_store.create()`` write path. This
# test does, against an isolated tmp_path-backed store (mirroring the
# isolation pattern in tests/test_webui_batch_campaign.py), and asserts the
# PERSISTED campaign_store row — not just the HTTP response body — carries the
# exact submitted platforms/mode/seed_text. A silent write-path regression
# (e.g. the wrong fields reaching campaign_store.create, or the write being
# skipped while still returning ``{"ok": True}``) would pass every other test
# in this file, since they never touch the real store.
# --------------------------------------------------------------------------- #
def test_webui_campaigns_create_persists_to_real_campaign_store(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store import _refresh_paths
    _refresh_paths()

    from webui_app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    real_client = app.test_client()

    resp = real_client.post("/api/v1/campaigns", json={
        "seeds": '{"seed_text": "round-trip seed"}\n',
        "platforms": ["blogger"],
        "mode": "draft",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    campaign_id = resp.get_json()["campaign_id"]

    from webui_store import campaign_store
    stored = campaign_store.get(campaign_id)
    assert stored is not None
    assert stored["platforms"] == ["blogger"]
    assert stored["mode"] == "draft"
    assert stored["status"] == "pending"
    assert stored["seeds"][0]["seed_text"] == "round-trip seed"
