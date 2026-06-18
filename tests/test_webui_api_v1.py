"""Contract tests for the /api/v1 surface — Plan 2026-06-18-002 U1.

Covers: the /health liveness endpoint (happy path), the RFC 9457 problem+json
error envelope (error path), path-scoped 404 handling (the non-/api/v1 surface
must keep its default HTML 404 — proving the scoping doesn't leak), the
OpenAPI 3.1 spec shape, and that the committed spec is not stale.
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── happy path ───────────────────────────────────────────────────────────────


def test_health_returns_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["api_version"] == "v1"
    assert body["version"]  # package version string, non-empty


# ── error path: RFC 9457 problem+json, path-scoped ──────────────────────────


def test_unknown_api_path_returns_problem_json(client):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.content_type.startswith("application/problem+json")
    body = resp.get_json()
    assert body["status"] == 404
    assert body["type"]  # stable problem-type URI
    assert body["title"] == "Not Found"
    assert body["error_class"] == "not_found"


def test_non_api_404_keeps_default_behavior(client):
    """Path-scoping must NOT leak: non-/api/v1 404s stay default (not problem+json)."""
    resp = client.get("/totally-unknown-page-xyz")
    assert resp.status_code == 404
    assert "application/problem+json" not in (resp.content_type or "")


def test_api_405_returns_problem_json(client):
    # /api/v1/health is GET-only; POST should yield a problem+json 405.
    resp = client.post("/api/v1/health")
    assert resp.status_code == 405
    assert resp.content_type.startswith("application/problem+json")
    assert resp.get_json()["error_class"] == "method_not_allowed"


# ── error envelope builders (unit) ──────────────────────────────────────────


def test_problem_dict_shape():
    from webui_app.api.v1.errors import problem_dict

    d = problem_dict(
        422,
        "Validation failed",
        detail="bad url",
        error_class="validation_error",
        errors=[{"field": "url", "message": "required"}],
    )
    assert d["status"] == 422
    assert d["type"].endswith("validation_error")
    assert d["error_class"] == "validation_error"
    assert d["errors"][0]["field"] == "url"


def test_from_pipe_result_reuses_error_class():
    from webui_app.api.v1.errors import from_pipe_result

    class _FakeResult:
        error = "plan-backlinks exploded"
        error_class = "content_gate_drop"

    prob = from_pipe_result(_FakeResult())
    assert prob.error_class == "content_gate_drop"
    assert prob.detail == "plan-backlinks exploded"
    assert prob.status == 502


# ── OpenAPI 3.1 contract ────────────────────────────────────────────────────


def test_openapi_spec_is_31_and_documents_health():
    from webui_app.api.v1.spec import spec_dict

    spec = spec_dict()
    assert spec["openapi"].startswith("3.1")
    assert "/api/v1/health" in spec["paths"]
    assert "ProblemDetails" in spec["components"]["schemas"]


def test_committed_openapi_spec_is_not_stale():
    """The committed spec must match the generator (CI runs the same check)."""
    from webui_app.api.v1.spec import spec_yaml

    committed = (REPO_ROOT / "openapi" / "backlink-api.yaml").read_text()
    assert committed.strip() == spec_yaml().strip(), (
        "openapi/backlink-api.yaml is stale — run `python scripts/gen_openapi.py`."
    )
