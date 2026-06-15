"""/ce:health/publish-metrics — success-rate (B2) + coverage (B1) JSON route.

GET-only, read-only, fail-open with an explicit ``ok`` flag.
"""
from __future__ import annotations

__tier__ = "unit"

from datetime import datetime, timezone

import pytest

from backlink_publisher.events import EventStore, kinds

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _ok(kind, platform, live_url):
    EventStore().append(
        kind, {"platform": platform, "live_url": live_url}, ts_utc=NOW.isoformat()
    )


def _fail(platform):
    EventStore().append(
        kinds.PUBLISH_FAILED,
        {"platform": platform, "error_class": "ExternalServiceError",
         "error_message_clean": "boom"},
        ts_utc=NOW.isoformat(),
    )


def test_empty_store_ok_true(client):
    resp = client.get("/ce:health/publish-metrics")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["success_rate"]["overall_attempts"] == 0
    assert body["coverage"]["total_links"] == 0


def test_success_rate_and_coverage_surface(client):
    _ok(kinds.PUBLISH_CONFIRMED, "medium", "https://medium.com/x")
    _fail("medium")
    resp = client.get("/ce:health/publish-metrics")
    body = resp.get_json()
    assert body["ok"] is True
    sr = body["success_rate"]
    assert sr["overall_attempts"] == 2
    assert sr["overall_successes"] == 1
    # coverage present and shaped
    assert "coverage_pct" in body["coverage"]
    assert body["coverage"]["target_pct"] == 0.5


def test_payload_shape_is_json_serializable(client):
    _ok(kinds.PUBLISH_CONFIRMED, "velog", "https://velog.io/y")
    resp = client.get("/ce:health/publish-metrics")
    body = resp.get_json()
    # per_channel is a list of plain dicts (dataclass -> asdict)
    assert isinstance(body["success_rate"]["per_channel"], list)
    assert isinstance(body["coverage"]["per_channel"], list)
