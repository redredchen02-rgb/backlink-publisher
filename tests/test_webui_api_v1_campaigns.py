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
