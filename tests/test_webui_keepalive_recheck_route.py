"""R1 / Unit 5 — keep-alive recheck routes (plan 2026-06-04-001).

POST /ce:keep-alive/recheck is an outbound action, so it enforces the
Origin/Referer guard on top of CSRF; GET recheck-status 404s on an unknown id
and never leaks the target inventory.
"""
__tier__ = "integration"

import pytest

import webui
from webui_app.services.keepalive_job import registry as keepalive_registry

_PORT = 8888
_GOOD_ORIGIN = {"Origin": f"http://127.0.0.1:{_PORT}"}


@pytest.fixture
def client(disable_csrf):
    keepalive_registry.reset_for_tests()
    return webui.app.test_client()


def test_start_recheck_rejects_missing_origin(client):
    assert client.post("/ce:keep-alive/recheck").status_code == 403


def test_start_recheck_rejects_external_origin(client):
    resp = client.post(
        "/ce:keep-alive/recheck", headers={"Origin": f"http://evil.example.com:{_PORT}"}
    )
    assert resp.status_code == 403


def test_start_recheck_with_loopback_origin_starts_job(client):
    resp = client.post("/ce:keep-alive/recheck", headers=_GOOD_ORIGIN)
    assert resp.status_code in (202, 409)          # started, or one already running
    if resp.status_code == 202:
        job_id = resp.get_json()["job_id"]
        status = client.get(f"/ce:keep-alive/recheck-status/{job_id}")
        assert status.status_code == 200
        body = status.get_json()
        assert body["job_id"] == job_id
        # poll surface exposes only progress/rollups, never credentials/targets
        assert set(body) == {
            "job_id", "kind", "status", "started_at",
            "total", "checked", "verdict_counts", "per_host", "error",
        }


def test_recheck_status_unknown_id_404s(client):
    assert client.get("/ce:keep-alive/recheck-status/deadbeefdeadbeef").status_code == 404
