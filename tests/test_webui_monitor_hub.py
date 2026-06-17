"""U5 — monitor hub aggregation (extends command_center).

The hub view renders, the JSON feed is fail-open and severity-ranked, and the
card builder maps the plan's priority (credential-failure > stale links > equity
gaps) to ordering + visual severity. Plan 2026-06-17-001 U5.
"""
__tier__ = "unit"

import pytest

from webui_app.routes import command_center as cc


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


def test_hub_view_renders(client):
    resp = client.get("/monitor-hub")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "监控聚合" in body
    assert "js/monitor_hub.js" in body
    assert 'type="module"' in body


def test_hub_json_ok_and_shape(client):
    resp = client.get("/api/monitor-hub")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["cards"], list)
    assert isinstance(data["anomaly_count"], int)
    # each card carries the contract fields
    for c in data["cards"]:
        assert {"key", "title", "severity", "headline", "deep_link"} <= set(c)


def test_cards_sorted_danger_first():
    status = {
        "credentials": {"failed": ["medium"], "failed_count": 1, "n_bound": 3},  # danger
        "keepalive": {"stripped": 0, "alive": 5, "n_targets": 5, "unknown": 0},   # ok
        "equity": {"low_weight_count": 2, "total_rows": 10},                      # warning
        "history": {"recent_24h": 1, "recent_7d": 4},                            # info
    }
    cards = cc._build_anomaly_cards(status)
    severities = [c["severity"] for c in cards]
    # danger must come before warning before ok/info
    assert severities[0] == "danger"
    assert severities.index("danger") < severities.index("warning")
    assert "ok" in severities or "info" in severities


def test_credential_failure_is_danger_with_action():
    status = {"credentials": {"failed": ["medium", "devto"], "failed_count": 2, "n_bound": 5}}
    cards = cc._build_anomaly_cards(status)
    cred = next(c for c in cards if c["key"] == "credentials")
    assert cred["severity"] == "danger"
    assert "2 个渠道凭证失效" in cred["headline"]
    assert cred["action"]["href"] == "/settings"


def test_subsystem_error_degrades_to_info_card_not_vanish():
    status = {"keepalive": {"error": "boom"}}
    cards = cc._build_anomaly_cards(status)
    ka = next(c for c in cards if c["key"] == "keepalive")
    assert ka["severity"] == "info"
    assert "不可用" in ka["headline"]


def test_no_anomalies_yields_only_ok_info():
    status = {
        "credentials": {"failed": [], "failed_count": 0, "n_bound": 3},
        "keepalive": {"stripped": 0, "alive": 5, "n_targets": 5, "unknown": 0},
        "equity": {"low_weight_count": 0, "total_rows": 10},
    }
    cards = cc._build_anomaly_cards(status)
    assert all(c["severity"] in ("ok", "info") for c in cards)
