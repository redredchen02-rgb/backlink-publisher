"""Contract tests for ``/api/v1/pipeline/*`` — Plan 2026-06-18-002 U5.

Hermetic: the module-level ``PipelineAPI`` instance and the history side-effects
are patched so we exercise the HTTP binding, the seed-building (characterized
against ``build_generate_seed``), and the problem+json status mapping — without
running the real plan/validate engines, shelling out to ``publish-backlinks``, or
touching the history store.

Named ``test_webui_*`` so the route-coverage meta-test
(``test_every_route_has_at_least_one_contract_test``) sees the literal
``client.post("/api/v1/pipeline/...")`` calls.
"""

from __future__ import annotations

__tier__ = "integration"

import json

import pytest

import webui_app.api.v1.pipeline as pipeline_mod
from webui_app.api.pipeline_api import PipeResult

PROBLEM_CT = "application/problem+json"


@pytest.fixture(autouse=True)
def _no_history_writes(monkeypatch):
    """Capture history side-effects instead of writing to the store."""
    calls = {"per_row": [], "single_failure": []}
    monkeypatch.setattr(
        pipeline_mod, "_push_history_per_row",
        lambda rows, **kw: calls["per_row"].append((rows, kw)),
    )
    monkeypatch.setattr(
        pipeline_mod, "_push_history_single_failure",
        lambda **kw: calls["single_failure"].append(kw),
    )
    return calls


def _patch_api(monkeypatch, **methods):
    for name, fn in methods.items():
        monkeypatch.setattr(pipeline_mod._api, name, fn)


# ── plan / generate ──────────────────────────────────────────────────────────


def test_webui_pipeline_plan_builds_seed_and_returns_rows(client, monkeypatch):
    captured: dict = {}

    def fake_plan(seed_json, **_kw):
        captured["seed"] = json.loads(seed_json)
        return PipeResult(stdout='{"id":"a","target_url":"https://example.com/"}', success=True)

    _patch_api(monkeypatch, plan=fake_plan)
    resp = client.post(
        "/api/v1/pipeline/plan",
        json={
            "urls": ["https://example.com/", "https://example.com/p2"],
            "platform": "medium",
            "target_language": "zh-TW",
            "custom_title": "T",
            "custom_tags": "x,y",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["plans"][0]["id"] == "a"
    # Characterization: the seed must mirror build_generate_seed (single source).
    seed = captured["seed"]
    assert seed["target_url"] == "https://example.com/"
    assert seed["platform"] == "medium"
    assert seed["target_language"] == "zh-CN"  # zh-TW normalized to a supported code
    assert seed["custom_title"] == "T"
    assert seed["extra_urls"] == ["https://example.com/p2"]


def test_webui_pipeline_plan_missing_urls_returns_422_problem(client):
    resp = client.post("/api/v1/pipeline/plan", json={})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert resp.get_json()["type"].endswith("invalid_request")


def test_webui_pipeline_plan_failure_maps_exit_to_problem(client, monkeypatch):
    _patch_api(
        monkeypatch,
        plan=lambda _s, **_k: PipeResult(
            success=False, error="boom", error_class="InputValidationError", exit_code=2
        ),
    )
    resp = client.post("/api/v1/pipeline/plan", json={"urls": ["https://x.com/"]})
    assert resp.status_code == 422  # exit 2 → 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    body = resp.get_json()
    assert body["error_class"] == "InputValidationError"
    assert body["status"] == 422


def test_webui_pipeline_plan_empty_output_returns_502(client, monkeypatch):
    _patch_api(monkeypatch, plan=lambda _s, **_k: PipeResult(stdout="", success=True))
    resp = client.post("/api/v1/pipeline/plan", json={"urls": ["https://x.com/"]})
    assert resp.status_code == 502
    assert resp.get_json()["error_class"] == "empty_output"


def test_webui_pipeline_preview_returns_first_row(client, monkeypatch):
    _patch_api(
        monkeypatch,
        plan=lambda _s, **_k: PipeResult(stdout='{"id":"p1"}\n{"id":"p2"}', success=True),
    )
    resp = client.post("/api/v1/pipeline/preview", json={"urls": ["https://x.com/"]})
    assert resp.status_code == 200
    assert resp.get_json()["plan"]["id"] == "p1"


# ── validate ───────────────────────────────────────────────────────────────


def test_webui_pipeline_validate_returns_rows(client, monkeypatch):
    captured: dict = {}

    def fake_validate(jsonl, **kw):
        captured["jsonl"] = jsonl
        captured["kw"] = kw
        return PipeResult(stdout='{"id":"v1"}', success=True)

    _patch_api(monkeypatch, validate=fake_validate)
    resp = client.post("/api/v1/pipeline/validate", json={"plans": [{"id": "x"}]})
    assert resp.status_code == 200
    assert resp.get_json()["validated"][0]["id"] == "v1"
    assert captured["kw"]["no_check_urls"] is True
    assert '"id": "x"' in captured["jsonl"]  # array → JSONL string


def test_webui_pipeline_validate_missing_plans_returns_422(client):
    resp = client.post("/api/v1/pipeline/validate", json={})
    assert resp.status_code == 422
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


# ── publish ──────────────────────────────────────────────────────────────────


def test_webui_pipeline_publish_full_success(client, monkeypatch, _no_history_writes):
    _patch_api(
        monkeypatch,
        publish=lambda *_a, **_k: PipeResult(
            stdout='{"published_url":"https://blog/x"}', success=True, exit_code=0
        ),
    )
    resp = client.post(
        "/api/v1/pipeline/publish", json={"plans": '{"id":"x"}', "platform": "blogger"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["state"] == "all_success"
    assert body["n_ok"] == 1 and body["n_total"] == 1
    assert len(_no_history_writes["per_row"]) == 1


def test_webui_pipeline_publish_partial_success(client, monkeypatch, _no_history_writes):
    stdout = '{"published_url":"https://blog/ok"}\n{"error":"nope"}'
    _patch_api(
        monkeypatch,
        publish=lambda *_a, **_k: PipeResult(stdout=stdout, success=True, exit_code=4),
    )
    resp = client.post(
        "/api/v1/pipeline/publish", json={"plans": "x", "platform": "blogger"}
    )
    assert resp.status_code == 200  # partial success is still 200; SPA branches on state
    body = resp.get_json()
    assert body["state"] == "partial_success"
    assert body["n_ok"] == 1 and body["n_total"] == 2
    assert body["failure_detail"]


def test_webui_pipeline_publish_total_failure_returns_problem(
    client, monkeypatch, _no_history_writes
):
    _patch_api(
        monkeypatch,
        publish=lambda *_a, **_k: PipeResult(
            success=False, error="auth gone", error_class="AuthExpiredError", exit_code=3
        ),
    )
    resp = client.post(
        "/api/v1/pipeline/publish", json={"plans": "x", "platform": "blogger"}
    )
    assert resp.status_code == 401  # exit 3 → 401
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert len(_no_history_writes["single_failure"]) == 1  # failure still recorded


def test_webui_pipeline_publish_missing_platform_returns_422(client):
    resp = client.post("/api/v1/pipeline/publish", json={"plans": "x"})
    assert resp.status_code == 422


def test_webui_pipeline_publish_velog_invalid_credentials_returns_400(client, monkeypatch):
    monkeypatch.setattr(
        pipeline_mod, "_get_velog_status", lambda: {"state": "expired", "guide": "rebind"}
    )
    resp = client.post(
        "/api/v1/pipeline/publish", json={"plans": "x", "platform": "velog"}
    )
    assert resp.status_code == 400
    assert resp.get_json()["error_class"] == "velog_credentials_invalid"


# ── regen-body ─────────────────────────────────────────────────────────────


def test_webui_pipeline_regen_body_missing_fields_returns_422(client):
    resp = client.post("/api/v1/pipeline/regen-body", json={"anchors": ["a"]})
    assert resp.status_code == 422


def test_webui_pipeline_regen_body_llm_not_configured_returns_400(client, monkeypatch):
    import backlink_publisher.config as cfgmod

    class _Cfg:
        llm_anchor_provider = None

    monkeypatch.setattr(cfgmod, "load_config", lambda: _Cfg())
    resp = client.post(
        "/api/v1/pipeline/regen-body", json={"main_domain": "x.com", "anchors": ["a"]}
    )
    assert resp.status_code == 400
    assert resp.get_json()["error_class"] == "llm_not_configured"
