"""Contract tests for ``/api/v1/monitor/summary`` — Plan 2026-06-18-002 U6.

The aggregate REUSES command_center's ``_collect_subsystem_status`` +
``_build_anomaly_cards`` (no recompute). These tests pin the versioned envelope,
the anomaly_count rule, and the fail-open contract (the monitor view must never
500 / never be dragged down by one bad subsystem).

Named ``test_webui_*`` so the route-coverage meta-test sees the literal
``client.get("/api/v1/monitor/summary")`` call.
"""

from __future__ import annotations

__tier__ = "integration"

import webui_app.api.v1.monitor as monitor_mod

PROBLEM_CT = "application/problem+json"


def test_webui_monitor_summary_returns_versioned_envelope(client):
    """Real aggregator call → 200 with the documented object envelope."""
    resp = client.get("/api/v1/monitor/summary")
    assert resp.status_code == 200
    assert not resp.headers["Content-Type"].startswith(PROBLEM_CT)
    body = resp.get_json()
    assert isinstance(body["cards"], list)  # never a bare top-level array
    assert isinstance(body["anomaly_count"], int)
    assert body["degraded"] in (True, False)


def test_webui_monitor_summary_anomaly_count_is_danger_plus_warning(client, monkeypatch):
    """anomaly_count counts only danger+warning cards (ok/info are not anomalies)."""
    monkeypatch.setattr(monitor_mod, "_collect_subsystem_status", lambda: {})
    monkeypatch.setattr(
        monitor_mod,
        "_build_anomaly_cards",
        lambda _status: [
            {"key": "credentials", "severity": "danger", "title": "", "headline": "",
             "detail": "", "deep_link": "/settings", "action": None},
            {"key": "equity", "severity": "warning", "title": "", "headline": "",
             "detail": "", "deep_link": "/ce:equity-ledger", "action": None},
            {"key": "keepalive", "severity": "ok", "title": "", "headline": "",
             "detail": "", "deep_link": "/ce:keep-alive", "action": None},
            {"key": "history", "severity": "info", "title": "", "headline": "",
             "detail": "", "deep_link": "/ce:history", "action": None},
        ],
    )
    body = client.get("/api/v1/monitor/summary").get_json()
    assert len(body["cards"]) == 4
    assert body["anomaly_count"] == 2  # danger + warning only
    assert body["degraded"] is False


def test_webui_monitor_summary_is_fail_open_on_aggregator_error(client, monkeypatch):
    """A catastrophic aggregator failure degrades to an empty 200 (never 500)."""
    def _boom():
        raise RuntimeError("subsystem exploded")

    monkeypatch.setattr(monitor_mod, "_collect_subsystem_status", _boom)
    resp = client.get("/api/v1/monitor/summary")
    assert resp.status_code == 200  # fail-open: dashboard still renders
    body = resp.get_json()
    assert body["cards"] == []
    assert body["anomaly_count"] == 0
    assert body["degraded"] is True
