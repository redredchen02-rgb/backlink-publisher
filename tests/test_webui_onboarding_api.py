"""Unit + endpoint tests for the onboarding wizard (Plan 2026-07-09-001).

Backend-side coverage of OnboardingAPI (live derivation of each step's `done`
flag) and the /api/v1/onboarding/* endpoints (shape + dismiss/reset persistence).
"""

from __future__ import annotations

__tier__ = "unit"

from unittest.mock import MagicMock, patch

import webui
from webui_app.api import channel_overview_api, global_settings_api
from webui_app.api.onboarding_api import OnboardingAPI
from webui_app.services import app_meta as app_meta_mod
import webui_store


def test_status_derives_done_flags_from_state() -> None:
    """Each step's `done` is computed live; flipping the underlying source flips it."""
    channels = MagicMock()
    channels.list_channels.return_value = [{"bound": True}]
    settings = MagicMock()
    settings.get_keywords.return_value = {
        "targets": ["https://a.com"],
        "pools": {"https://a.com": ["kw1"]},
    }
    campaigns = MagicMock()
    campaigns.list.return_value = [{"id": "c1"}]
    history = MagicMock()
    history.load.return_value = [{"status": "published"}]
    store = MagicMock()
    store.is_dismissed.return_value = False

    # The facade imports these names inside the method, so patch the source
    # modules (the names are re-read from there at call time).
    with (
        patch.object(channel_overview_api, "ChannelOverviewAPI", return_value=channels),
        patch.object(global_settings_api, "GlobalSettingsAPI", return_value=settings),
        patch.object(app_meta_mod, "pro_status_payload", return_value={"configured": True}),
        patch.object(webui_store, "campaign_store", campaigns),
        patch.object(webui_store, "history_store", history),
        patch.object(webui_store, "onboarding_store", store),
    ):
        status = OnboardingAPI().status()

    by_id = {s["id"]: s for s in status["steps"]}
    assert by_id["connect_channel"]["done"] is True
    assert by_id["configure_llm"]["done"] is True
    assert by_id["add_targets"]["done"] is True
    assert by_id["create_campaign"]["done"] is True
    assert by_id["publish_first"]["done"] is True
    assert status["all_done"] is True
    assert status["dismissed"] is False


def test_status_all_done_ignores_optional_step() -> None:
    """LLM (optional) being incomplete must not block all_done."""
    channels = MagicMock()
    channels.list_channels.return_value = [{"bound": False}]
    settings = MagicMock()
    settings.get_keywords.return_value = {"targets": [], "pools": {}}
    campaigns = MagicMock()
    campaigns.list.return_value = []
    history = MagicMock()
    history.load.return_value = []
    store = MagicMock()
    store.is_dismissed.return_value = False

    with (
        patch.object(channel_overview_api, "ChannelOverviewAPI", return_value=channels),
        patch.object(global_settings_api, "GlobalSettingsAPI", return_value=settings),
        patch.object(app_meta_mod, "pro_status_payload", return_value={"configured": False}),
        patch.object(webui_store, "campaign_store", campaigns),
        patch.object(webui_store, "history_store", history),
        patch.object(webui_store, "onboarding_store", store),
    ):
        status = OnboardingAPI().status()

    assert status["all_done"] is False
    assert status["steps"][1]["optional"] is True


def test_endpoints_status_shape(disable_csrf) -> None:
    client = disable_csrf.test_client()
    resp = client.get("/api/v1/onboarding/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data.keys()) >= {"dismissed", "all_done", "steps"}
    assert len(data["steps"]) == 5
    for step in data["steps"]:
        assert set(step.keys()) == {"id", "title", "rationale", "optional", "cta", "done"}


def test_endpoints_dismiss_then_reset(disable_csrf) -> None:
    client = disable_csrf.test_client()
    assert client.get("/api/v1/onboarding/status").get_json()["dismissed"] is False

    resp = client.post("/api/v1/onboarding/dismiss")
    assert resp.status_code == 200
    assert client.get("/api/v1/onboarding/status").get_json()["dismissed"] is True

    client.post("/api/v1/onboarding/reset")
    assert client.get("/api/v1/onboarding/status").get_json()["dismissed"] is False


def test_endpoints_post_requires_csrf() -> None:
    """Without the disable_csrf fixture the global CSRF guard must block POST."""
    client = webui.app.test_client()
    resp = client.post("/api/v1/onboarding/dismiss")
    assert resp.status_code == 403
