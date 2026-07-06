"""Tests for batch campaign flow — Plan 2026-06-02-001 U3-U6.

Covers CampaignStore, CampaignWorker, batch_campaign routes, campaign_progress
route, and campaign_id filtering on the main page.

IMPORTANT: All tests use the module-level ``webui_store.campaign_store``
singleton (not a local instance) so that route handlers and CampaignWorker
see the same data. The singleton resolves via BACKLINK_PUBLISHER_CONFIG_DIR
which is set to ``tmp_path`` by the ``app`` fixture.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import re
import threading

import pytest

pytest.importorskip("flask")

from webui_app import create_app
from webui_store import campaign_store

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    # Bypass _LazyStore cache so each test gets a fresh store against tmp_path.
    from webui_store import _refresh_paths
    _refresh_paths()
    app = create_app()
    app.config["TESTING"] = True
    app.config.update(CSRF_ENABLED=False)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_campaign(*, mode="draft", seed="test seed", platforms=None):
    from webui_store import campaign_store
    return campaign_store.create(
        mode=mode,
        platforms=platforms or ["blogger"],
        seeds=[{"seed_text": seed}],
    )


# ── CampaignStore — create / get / update / list ───────────────────────────────


def test_campaign_store_create_and_get():
    cid = _make_campaign(seed="test seed")
    campaign = campaign_store.get(cid)
    assert campaign is not None
    assert campaign["campaign_id"] == cid
    assert campaign["mode"] == "draft"
    assert campaign["platforms"] == ["blogger"]
    assert campaign["status"] == "pending"
    assert len(campaign["seeds"]) == 1
    assert campaign["seeds"][0]["seed_text"] == "test seed"
    assert campaign["seeds"][0]["status"] == "idle"


def test_campaign_store_update_status():
    cid = _make_campaign()
    ok = campaign_store.update_status(cid, status="running")
    assert ok is True
    campaign = campaign_store.get(cid)
    assert campaign["status"] == "running"

    ok = campaign_store.update_status(cid, status="completed", progress_pct=100.0)
    assert ok is True
    campaign = campaign_store.get(cid)
    assert campaign["status"] == "completed"
    assert campaign["progress_pct"] == 100.0


def test_campaign_store_update_seed_status():
    cid = _make_campaign()
    ok = campaign_store.update_seed_status(cid, 0, status="success", draft_count=1)
    assert ok is True
    campaign = campaign_store.get(cid)
    assert campaign["seeds"][0]["status"] == "success"
    assert campaign["seeds"][0]["draft_count"] == 1
    assert campaign["progress_pct"] == 100.0


def test_campaign_store_list():
    c1 = _make_campaign(seed="a")
    c2 = _make_campaign(seed="b", mode="publish", platforms=["medium"])
    all_campaigns = campaign_store.list()
    assert len(all_campaigns) >= 2
    # newest first
    assert all_campaigns[0]["campaign_id"] in (c1, c2)


def test_campaign_store_get_nonexistent():
    assert campaign_store.get("nonexistent-id") is None
    assert campaign_store.update_status("nonexistent-id", status="running") is False


# ── CampaignWorker — start / status / cancel / AlreadyRunning ──────────────────


def test_campaign_worker_get_status_before_start():
    from webui_app.campaign_worker import CampaignWorker

    cid = _make_campaign()
    worker = CampaignWorker(max_workers=1)
    try:
        status = worker.get_status(cid)
        assert status is not None, "Campaign exists in store, worker should find it"
        assert status["campaign_id"] == cid
        assert status["_running"] is False
        assert status["_done"] is True
    finally:
        worker.shutdown(wait=False)


def test_campaign_worker_already_running():
    from webui_app.campaign_worker import AlreadyRunningError, CampaignWorker

    cid1 = _make_campaign(seed="s")
    cid2 = _make_campaign(seed="t")

    worker = CampaignWorker(max_workers=1)
    try:
        worker.start_campaign(cid1, {"platforms": ["blogger"], "mode": "draft"})
        with pytest.raises(AlreadyRunningError):
            worker.start_campaign(cid2, {"platforms": ["blogger"], "mode": "draft"})
    finally:
        worker.shutdown(wait=False)


def test_campaign_worker_cancel():
    from webui_app.campaign_worker import CampaignWorker

    worker = CampaignWorker(max_workers=1)
    assert worker.is_running() is False
    cancelled = worker.cancel_campaign("nonexistent")
    assert cancelled is False
    worker.shutdown(wait=False)


def test_campaign_worker_is_running():
    from webui_app.campaign_worker import CampaignWorker

    worker = CampaignWorker(max_workers=1)
    assert worker.is_running() is False
    worker.shutdown(wait=False)


def test_campaign_worker_get_status_nonexistent():
    from webui_app.campaign_worker import CampaignWorker

    worker = CampaignWorker(max_workers=1)
    try:
        status = worker.get_status("nonexistent")
        assert status is None
    finally:
        worker.shutdown(wait=False)


# ── batch_campaign route — GET ─────────────────────────────────────────────────


def test_batch_campaign_get_renders(client):
    resp = client.get("/batch-campaign")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "批量创建" in html or "batch" in html.lower()


# ── batch_campaign — connection-state partition (Plan 2026-06-05-007 U5) ──────


def test_batch_campaign_get_shows_extension_area(client):
    """The picker renders a folded 拓展区 for never-connected platforms."""
    html = client.get("/batch-campaign").data.decode("utf-8")
    assert "拓展區" in html
    assert 'id="campaign-ext-area"' in html


def test_batch_campaign_anon_platform_is_selectable(client):
    """R1: an anon platform (telegraph) renders as an enabled, name=platforms
    checkbox in the main area.
    """
    html = client.get("/batch-campaign").data.decode("utf-8")
    assert re.search(
        r'name="platforms"\s+value="telegraph"', html
    ), "anon telegraph must be a selectable platform checkbox"


def test_batch_campaign_unbound_platform_folded_and_disabled(client, monkeypatch):
    """R3: a never-connected non-anon platform folds into the extension area as
    a disabled checkbox with a path to the settings binding page.
    """
    from webui_app import binding_status

    real = binding_status.get_channel_status

    def _patched(name, config):
        st = real(name, config)
        if name == "notion":
            return {**st, "bound": False}
        return st

    monkeypatch.setattr(binding_status, "get_channel_status", _patched)
    html = client.get("/batch-campaign").data.decode("utf-8")
    ext = html[html.index('id="campaign-ext-area"'):]
    assert 'id="extplat-notion"' in ext, "unbound notion must fold into 拓展区"
    assert "/settings#section-channels" in ext, "extension must link to binding page"
    # An unbound non-anon platform must not be a selectable publish checkbox.
    assert not re.search(r'name="platforms"\s+value="notion"', html)


def test_batch_campaign_expired_platform_in_main_with_reconnect(client, monkeypatch):
    """R2: an expired browser channel stays in the main picker area, disabled,
    with a 需重連 marker — not folded away and not selectable.
    """
    from webui_app import binding_status
    from webui_store import channel_status

    real = binding_status.get_channel_status

    def _patched(name, config):
        st = real(name, config)
        if name == "medium":
            return {**st, "bound": False}
        return st

    monkeypatch.setattr(binding_status, "get_channel_status", _patched)
    monkeypatch.setattr(
        channel_status, "list_all", lambda: {"medium": {"status": "expired"}}
    )
    html = client.get("/batch-campaign").data.decode("utf-8")
    main = html[:html.index('id="campaign-ext-area"')]
    assert "需重連" in main
    assert 'id="plat-medium"' in main, "expired medium must render in main area"
    assert not re.search(r'name="platforms"\s+value="medium"', html), (
        "expired medium must not be a selectable publish checkbox"
    )


def test_batch_campaign_expired_api_platform_not_selectable(client):
    """Plan 008: an API platform with a persisted token_expired verdict shows in
    the main picker area as 需重連 and is NOT a selectable publish checkbox.
    """
    from webui_store import verify_health

    verify_health.record("devto", "token_expired")
    html = client.get("/batch-campaign").data.decode("utf-8")
    main = html[:html.index('id="campaign-ext-area"')]
    assert "需重連" in main
    assert 'id="plat-devto"' in main, "expired devto must render in the main picker area"
    assert not re.search(r'name="platforms"\s+value="devto"', html), (
        "expired devto must not be a selectable publish checkbox"
    )


def test_batch_campaign_post_error_preserves_partition(client):
    """The POST validation-error re-render still shows the partitioned picker."""
    resp = client.post("/batch-campaign", data={
        "seeds": "",  # triggers a validation error
        "platforms": ["telegraph"],
        "mode": "draft",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "拓展區" in html
    assert 'id="campaign-ext-area"' in html


# ── batch_campaign route — POST ────────────────────────────────────────────────


def test_batch_campaign_post_valid(client):
    """POST with valid seeds and platforms redirects to campaign progress."""
    from webui_store import campaign_store as cs
    resp = client.post("/batch-campaign", data={
        "seeds": json.dumps({"seed_text": "test article"}) + "\n",
        "platforms": ["blogger"],
        "mode": "draft",
    })
    assert resp.status_code in (302, 303)
    assert "/campaign/" in resp.location


def test_batch_campaign_post_empty_seeds(client):
    resp = client.post("/batch-campaign", data={
        "seeds": "",
        "platforms": ["blogger"],
        "mode": "draft",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "至少输入" in html


def test_batch_campaign_post_no_platform(client):
    resp = client.post("/batch-campaign", data={
        "seeds": json.dumps({"seed_text": "test"}) + "\n",
        "platforms": [],
        "mode": "draft",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "至少选择一个平台" in html


def test_batch_campaign_post_invalid_json(client):
    resp = client.post("/batch-campaign", data={
        "seeds": "not valid json\n",
        "platforms": ["blogger"],
        "mode": "draft",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "解析失败" in html


def test_batch_campaign_post_too_many_seeds(client):
    lines = "\n".join(
        json.dumps({"seed_text": f"seed {i}"})
        for i in range(12)
    )
    resp = client.post("/batch-campaign", data={
        "seeds": lines,
        "platforms": ["blogger"],
        "mode": "draft",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "最多 10" in html


def test_batch_campaign_post_invalid_mode(client):
    resp = client.post("/batch-campaign", data={
        "seeds": json.dumps({"seed_text": "test"}) + "\n",
        "platforms": ["blogger"],
        "mode": "invalid_mode",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "模式必须选择" in html


def test_batch_campaign_post_with_cap_and_delay(client):
    resp = client.post("/batch-campaign", data={
        "seeds": json.dumps({"seed_text": "test"}) + "\n",
        "platforms": ["blogger"],
        "mode": "publish",
        "cap": "5",
        "seed_delay": "30",
    })
    assert resp.status_code in (302, 303)
    assert "/campaign/" in resp.location


# ── campaign_progress route ────────────────────────────────────────────────────


def test_campaign_progress_page_valid(client):
    """Visit campaign progress for an existing campaign.

    /campaign/<id> now 302s to the SPA (P13 B3); the Jinja page lives at
    /campaign/<id>/jinja.
    """
    cid = _make_campaign()
    resp = client.get(f"/campaign/{cid}")
    assert resp.status_code == 302
    assert f"/app/campaign/{cid}" in resp.location
    resp = client.get(f"/campaign/{cid}/jinja")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert cid[:8] in html or "批量" in html


def test_campaign_progress_page_invalid(client):
    resp = client.get("/campaign/nonexistent-id/jinja")
    assert resp.status_code == 404


# ── Campaign API status endpoint ───────────────────────────────────────────────


def test_campaign_api_status(client):
    cid = _make_campaign()
    resp = client.get(f"/api/campaign/{cid}/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    assert data["running"] is False
    assert data["done"] is True


def test_campaign_api_status_nonexistent(client):
    resp = client.get("/api/campaign/nonexistent/status")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data is not None
    assert "error" in data


# ── Main page — campaign_id filter ─────────────────────────────────────────────


def test_main_page_with_campaign_id(client):
    """Main page accepts campaign_id param and renders without error."""
    resp = client.get("/?campaign_id=test-id-123")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Backlink" in html or "Publisher" in html


def test_main_page_without_campaign_id(client):
    """Main page renders normally without campaign_id filter."""
    resp = client.get("/")
    assert resp.status_code == 200


# ── batch_campaign route — POST with cap validation ────────────────────────────


def test_batch_campaign_post_invalid_cap(client):
    resp = client.post("/batch-campaign", data={
        "seeds": json.dumps({"seed_text": "test"}) + "\n",
        "platforms": ["blogger"],
        "mode": "draft",
        "cap": "abc",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "上限" in html


def test_batch_campaign_post_negative_cap(client):
    resp = client.post("/batch-campaign", data={
        "seeds": json.dumps({"seed_text": "test"}) + "\n",
        "platforms": ["blogger"],
        "mode": "draft",
        "cap": "0",
    })
    assert resp.status_code == 422
    html = resp.data.decode("utf-8")
    assert "上限" in html


# ── CampaignWorker with store data ─────────────────────────────────────────────


def test_worker_start_and_store_consistency():
    from webui_app.campaign_worker import CampaignWorker

    cid = _make_campaign(seed="worker test")
    worker = CampaignWorker(max_workers=1)
    try:
        worker.start_campaign(cid, {"platforms": ["blogger"], "mode": "draft"})
        status = worker.get_status(cid)
        assert status is not None
        assert status["campaign_id"] == cid
    finally:
        worker.shutdown(wait=False)
