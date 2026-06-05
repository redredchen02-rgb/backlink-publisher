"""Integration — equity-ledger batch recheck POST+GET (U5, Plan 2026-06-05-001).

Starts a background recheck thread and polls for completion. Background thread
uses recheck_many (monkeypatched in tests) to avoid real network calls.
"""
__tier__ = "integration"

import json
import time

import pytest

from backlink_publisher.events import EventStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))
    import webui
    webui.app.config["TESTING"] = True
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


def _seed_two_rows():
    EventStore().add_article({
        "target_urls_json": json.dumps(["https://site.com/p"]),
        "live_url": "https://medium.com/l1",
    })
    EventStore().add_article({
        "target_urls_json": json.dumps(["https://site.com/p"]),
        "live_url": "https://blog.ex/l2",
    })
    from webui_store import history_store
    history_store.save([
        {"id": "h1", "platform": "medium", "target_url": "https://site.com/p",
         "article_urls": ["https://medium.com/l1"], "status": "published_unverified",
         "title": "t"},
        {"id": "h2", "platform": "blogger", "target_url": "https://site.com/p",
         "article_urls": ["https://blog.ex/l2"], "status": "published_unverified",
         "title": "t"},
    ])


def test_batch_recheck_starts_and_completes(client, monkeypatch):
    _seed_two_rows()

    from types import SimpleNamespace
    mock_summary = SimpleNamespace(confirmed=1, downgraded_to_failed=0, skipped=0)

    monkeypatch.setattr(
        "webui_app.services.recheck.recheck_many",
        lambda items: ({"h1": {"status": "published", "verified_at": "now"}}, mock_summary),
    )

    resp = client.post(
        "/ce:equity-ledger/batch-recheck",
        data=json.dumps({"filter": "all"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "job_id" in body
    assert body["total"] >= 0

    job_id = body["job_id"]
    for _ in range(20):
        time.sleep(0.1)
        status_resp = client.get(f"/ce:equity-ledger/batch-recheck/{job_id}/status")
        if status_resp.status_code == 200:
            status = status_resp.get_json()
            if status.get("done"):
                break

    status_resp = client.get(f"/ce:equity-ledger/batch-recheck/{job_id}/status")
    assert status_resp.status_code == 200
    status = status_resp.get_json()
    assert status["done"] is True


def test_batch_recheck_with_explicit_urls(client, monkeypatch):
    _seed_two_rows()

    from types import SimpleNamespace
    mock_summary = SimpleNamespace(confirmed=0, downgraded_to_failed=0, skipped=1)

    monkeypatch.setattr(
        "webui_app.services.recheck.recheck_many",
        lambda items: ({}, mock_summary),
    )

    resp = client.post(
        "/ce:equity-ledger/batch-recheck",
        data=json.dumps({"target_urls": ["https://site.com/p"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "job_id" in body
    assert body["total"] == 1


def test_batch_recheck_invalid_filter_400(client):
    resp = client.post(
        "/ce:equity-ledger/batch-recheck",
        data=json.dumps({"filter": "nonexistent"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_batch_recheck_status_unknown_job_404(client):
    resp = client.get("/ce:equity-ledger/batch-recheck/does-not-exist/status")
    assert resp.status_code == 404
