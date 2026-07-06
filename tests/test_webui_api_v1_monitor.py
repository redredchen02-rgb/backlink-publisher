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


def test_webui_monitor_summary_degraded_true_when_single_subsystem_errors(client, monkeypatch):
    """Plan 2026-07-06-004 Unit 1 (R18): one subsystem's own caught error must
    flip ``degraded``, not just a total aggregator crash — and its card must
    still render (fail-open), not disappear because of degraded=true."""
    status_with_one_error = {
        "credentials": {"error": "boom"},
        "keepalive": {"n_targets": 0, "stripped": 0, "alive": 0, "unknown": 0},
    }
    monkeypatch.setattr(monitor_mod, "_collect_subsystem_status", lambda: status_with_one_error)
    monkeypatch.setattr(
        monitor_mod,
        "_build_anomaly_cards",
        lambda _status: [
            {"key": "credentials", "severity": "info", "title": "渠道凭证",
             "headline": "状态不可用", "detail": "boom",
             "deep_link": "/settings", "action": None},
            {"key": "keepalive", "severity": "ok", "title": "保活",
             "headline": "0 条链接存活", "detail": "",
             "deep_link": "/ce:keep-alive", "action": None},
        ],
    )
    resp = client.get("/api/v1/monitor/summary")
    assert resp.status_code == 200  # degraded=true never turns into a 500
    body = resp.get_json()
    assert body["degraded"] is True
    assert len(body["cards"]) == 2  # the failed subsystem's card still renders


def test_webui_monitor_summary_degraded_false_when_all_subsystems_healthy(client, monkeypatch):
    monkeypatch.setattr(
        monitor_mod, "_collect_subsystem_status",
        lambda: {"credentials": {"failed_count": 0, "n_bound": 3}},
    )
    monkeypatch.setattr(monitor_mod, "_build_anomaly_cards", lambda _status: [])
    body = client.get("/api/v1/monitor/summary").get_json()
    assert body["degraded"] is False


# ── Unit 2 (Plan 2026-07-06-004): 6 signal sources, hybrid cards ─────────────
#
# The two new sources (error_reports, schedule_queue) get their own dedicated
# test files (test_webui_monitor_error_reports_signal.py /
# test_webui_monitor_schedule_signal.py) for the collector/card-builder unit
# tests. These two tests cover the thing only the real endpoint proves: that
# the aggregate response really does carry all 6 sources at once, with the
# hybrid `items` field wired all the way through.

def test_webui_monitor_summary_includes_all_six_signal_sources(client):
    from datetime import datetime, timedelta, timezone
    from webui_store import drafts_store, queue_store

    drafts_store.save([{
        "id": "d1", "status": "scheduled",
        "scheduled_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "target_url": "https://a.example.com",
    }])
    queue_store.save([{
        "id": "t1", "status": "pending", "urls": ["https://b.example.com"],
        "config": {"platform": "blogger"},
    }])

    body = client.get("/api/v1/monitor/summary").get_json()
    keys = {c["key"] for c in body["cards"]}
    assert keys == {
        "credentials", "keepalive", "equity", "history",
        "error_reports", "schedule_queue",
    }

    sq_card = next(c for c in body["cards"] if c["key"] == "schedule_queue")
    assert "items" in sq_card  # hybrid card
    assert len(sq_card["items"]) == 2
    assert sq_card["severity"] == "warning"  # the draft is overdue

    er_card = next(c for c in body["cards"] if c["key"] == "error_reports")
    assert "items" in er_card  # present even at 0 open reports
    assert er_card["severity"] == "ok"

    # The 4 original cards keep their plain (non-hybrid) shape.
    for key in ("credentials", "keepalive", "equity", "history"):
        card = next(c for c in body["cards"] if c["key"] == key)
        assert "items" not in card


def test_webui_monitor_summary_severity_ordering_unaffected_by_new_sources(client):
    """danger/warning cards still sort ahead of the new sources' ok/info cards
    when nothing in error_reports/schedule_queue is seeded (both healthy)."""
    from webui_store import drafts_store, queue_store
    drafts_store.save([])
    queue_store.save([])

    body = client.get("/api/v1/monitor/summary").get_json()
    severities = [c["severity"] for c in body["cards"]]
    ranked = {"danger": 0, "warning": 1, "ok": 2, "info": 2}
    assert severities == sorted(severities, key=lambda s: ranked.get(s, 3))
