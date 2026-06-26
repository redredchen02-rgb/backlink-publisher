"""U5 — Batch Recheck endpoint (plan 2026-06-05-001).

POST /ce:equity-ledger/batch-recheck → start job, returns job_id.
GET  /ce:equity-ledger/batch-recheck/<job_id>/status → poll progress.
"""
from __future__ import annotations

__tier__ = "unit"

import time

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch, disable_csrf):
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))
    import webui
    return webui.app.test_client()


def test_batch_recheck_start_empty_store(client):
    """Empty store → immediate done=True response."""
    resp = client.post("/ce:equity-ledger/batch-recheck",
                       json={"filter": "all"},
                       content_type="application/json")
    assert resp.status_code in (200, 202)
    body = resp.get_json()
    # Either immediate done (no targets) or a job_id was returned
    assert "job_id" in body or body.get("done") is True


def test_batch_recheck_invalid_filter_returns_400(client):
    resp = client.post("/ce:equity-ledger/batch-recheck",
                       json={"filter": "totally-invalid"},
                       content_type="application/json")
    assert resp.status_code == 400


def test_batch_recheck_status_unknown_job_returns_404(client):
    resp = client.get("/ce:equity-ledger/batch-recheck/nonexistent-job-id/status")
    assert resp.status_code == 404


def test_batch_recheck_returns_job_id_and_status_pollable(client):
    """Start a real batch job and poll status — it must not crash."""
    resp = client.post("/ce:equity-ledger/batch-recheck",
                       json={"filter": "weak"},
                       content_type="application/json")
    assert resp.status_code in (200, 202)
    body = resp.get_json()
    if "job_id" not in body:
        return  # immediate done — no targets, acceptable
    job_id = body["job_id"]

    # Poll up to 3 seconds for completion
    deadline = time.monotonic() + 3.0
    done = False
    while time.monotonic() < deadline:
        status_resp = client.get(f"/ce:equity-ledger/batch-recheck/{job_id}/status")
        assert status_resp.status_code == 200
        data = status_resp.get_json()
        assert "checked" in data
        if data.get("done"):
            done = True
            break
        time.sleep(0.1)
    assert done, "Batch recheck job did not complete within 3 seconds (empty store should be instant)"
