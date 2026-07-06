"""Contract tests for ``/api/v1/health/*`` — Plan 2026-07-02-001 U6.

Contract-first (per the plan's Execution note): each panel helper is forced to
raise and the test asserts 200 + that panel's own ``degraded`` flag, with
sibling panels unaffected -- pinning the fail-open contract before/alongside
the SPA build.

Security tests that need the app-level Origin guard forced on (it auto-
disables under pytest) use ``guard_on_app``, mirroring
``tests/test_webui_lite_origin_guard_coverage.py``'s own fixture -- the CSRF
guard does NOT need force-enabling here since it is not gated off under
pytest by default (only ``ORIGIN_GUARD_ENABLED``/the rate limiter are). The
bind-origin decision tree itself (Origin/Referer allowlist matrix) is already
exhaustively covered by ``tests/test_webui_bind_security.py`` against the
shared ``_check_bind_origin_or_abort`` helper -- this file only confirms the
recheck-link view actually calls it, not the full matrix again.
"""

from __future__ import annotations

__tier__ = "integration"

import json as _json

import pytest

import webui_app.api.v1.health_dashboard as hd
from webui_app.helpers.security import _FLASK_PORT

PROBLEM_CT = "application/problem+json"

# (panel key in the response, module attribute to force-raise, expected empty fallback)
_PANELS = [
    ("canary", "_canary_rows", []),
    ("forward_path", "_forward_path_rows", []),
    ("reconciliation_gaps", "_reconciliation_gaps", {}),
    ("recheck_decay", "_decay_counts", {}),
    ("channel_scorecard", "_scorecard_rows", []),
    ("geo_panel", "_geo_panel", {}),
    ("pipeline_summary", "_pipeline_summary", {}),
    ("storage_health", "_storage_health", {}),
    ("platform_health", "_platform_health", {}),
    ("autopilot_alerts", "_autopilot_alerts", []),
    ("weights_snapshot", "_weights_snapshot", None),
    ("decay_alerts", "_decay_alerts", []),
    ("gsc_indexation", "_gsc_indexation_panel", []),
    ("gsc_ranking", "_gsc_ranking_panel", []),
    ("publish_index_latency", "_publish_index_latency", []),
    ("index_rate_by_channel", "_index_rate_by_channel", []),
    ("impression_analysis", "_impression_analysis", []),
    ("ranking_lift_analysis", "_ranking_lift_analysis", []),
    ("referral_conversion", "_referral_conversion", []),
    ("cost_metrics", "_cost_metrics", {}),
    ("decisions_by_platform", "_decisions_by_platform", []),
    ("publish_metrics", "_publish_metrics", {
        "success_rate": None, "coverage": None, "readiness": None,
        "policy_mode": None, "enforce_channels": [],
    }),
]


# ── GET /health/summary ──────────────────────────────────────────────────


def test_webui_health_summary_happy_path(client):
    resp = client.get("/api/v1/health/summary")
    assert resp.status_code == 200
    assert not resp.headers["Content-Type"].startswith(PROBLEM_CT)
    body = resp.get_json()
    assert set(body.keys()) == {"projection", "health", "agg_degraded", "panels"}
    assert body["agg_degraded"] is False
    assert set(body["panels"].keys()) == {name for name, _, _ in _PANELS}
    for name, panel in body["panels"].items():
        assert panel["degraded"] is False, name


@pytest.mark.parametrize("panel_key,attr,fallback", _PANELS)
def test_webui_health_summary_panel_fail_open(client, monkeypatch, panel_key, attr, fallback):
    """Forcing one panel to raise -> 200, that panel degraded, siblings unaffected."""
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(hd, attr, _boom)
    resp = client.get("/api/v1/health/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    panel = body["panels"][panel_key]
    assert panel["degraded"] is True
    assert panel["data"] == fallback
    for other_key, other_panel in body["panels"].items():
        if other_key != panel_key:
            assert other_panel["degraded"] is False, other_key


def test_webui_health_summary_agg_panel_self_reports_via_projection(client, monkeypatch):
    """_health_agg never raises (matches the legacy closure) -- its own
    degradation surfaces via projection.degraded, not agg_degraded."""
    import webui_app.health_metrics as hm

    def _boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(hm, "build_health", _boom)
    resp = client.get("/api/v1/health/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["agg_degraded"] is False
    assert body["projection"]["degraded"] is True


def test_webui_health_summary_never_leaks_str_exc(client, monkeypatch):
    """A sentinel embedded in an exception message must never reach the JSON body."""
    sentinel = "sqlite-secret-path-C:/Users/user/.config/sekrit"

    def _boom():
        raise RuntimeError(sentinel)

    monkeypatch.setattr(hd, "_canary_rows", _boom)
    resp = client.get("/api/v1/health/summary")
    assert sentinel not in resp.get_data(as_text=True)


def test_webui_health_summary_degraded_reason_never_leaks_str_exc(client, monkeypatch):
    import webui_app.health_metrics as hm

    sentinel = "sqlite-secret-path-C:/Users/user/.config/sekrit"

    def _boom():
        raise RuntimeError(sentinel)

    monkeypatch.setattr(hm, "build_health", _boom)
    resp = client.get("/api/v1/health/summary")
    assert sentinel not in resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["projection"]["degraded_reason"] == "RuntimeError"


# ── GET /health/scorecard/<channel>/links ────────────────────────────────


def test_webui_health_scorecard_links_happy_path(client, monkeypatch):
    class _Row:
        def to_dict(self):
            return {"url": "https://a.com/x"}

    monkeypatch.setattr(
        "backlink_publisher.scorecard.links.derive_links_by_channel",
        lambda: {"blogger": [_Row()]},
    )
    resp = client.get("/api/v1/health/scorecard/blogger/links")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": True, "links": [{"url": "https://a.com/x"}]}


def test_webui_health_scorecard_links_fail_open(client, monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "backlink_publisher.scorecard.links.derive_links_by_channel", _boom,
    )
    resp = client.get("/api/v1/health/scorecard/blogger/links")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": False, "links": []}


# ── POST /health/scorecard/recheck-link ──────────────────────────────────


def _origin_headers():
    return {"Origin": f"http://127.0.0.1:{_FLASK_PORT}"}


def test_webui_health_recheck_link_missing_origin_and_referer_403(client):
    """Smoke-confirms the view calls _check_bind_origin_or_abort -- the full
    Origin/Referer allowlist matrix is covered by test_webui_bind_security.py."""
    resp = client.post(
        "/api/v1/health/scorecard/recheck-link",
        data=_json.dumps({"live_url": "https://a.com/x"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_webui_health_recheck_link_missing_live_url_400(client):
    resp = client.post(
        "/api/v1/health/scorecard/recheck-link",
        data=_json.dumps({}),
        content_type="application/json",
        headers=_origin_headers(),
    )
    assert resp.status_code == 400


def test_webui_health_recheck_link_unpublished_url_404_no_probe(client, monkeypatch):
    """Anti-SSRF: an unpublished URL is rejected with NO probe fired."""
    probe_called = []
    monkeypatch.setattr(hd, "_published_candidate", lambda store, url: None)
    monkeypatch.setattr(
        "backlink_publisher.recheck.probe.recheck_link",
        lambda *a, **k: probe_called.append(True),
    )
    resp = client.post(
        "/api/v1/health/scorecard/recheck-link",
        data=_json.dumps({"live_url": "https://not-published.example/x"}),
        content_type="application/json",
        headers=_origin_headers(),
    )
    assert resp.status_code == 404
    assert probe_called == []


def test_webui_health_recheck_link_probes_stored_url_not_client_string(client, monkeypatch):
    """The probe target is the STORED live_url, never the client-supplied string."""
    stored_record = {
        "live_url": "https://stored.example/canonical",
        "target_url": "https://target.example",
        "host": "stored.example",
        "article_id": "a1",
        "platform": "blogger",
    }
    probed_records = []

    def _fake_recheck_link(record, **kwargs):
        probed_records.append(record)
        return {"verdict": "alive"}

    monkeypatch.setattr(hd, "_published_candidate", lambda store, url: stored_record)
    monkeypatch.setattr("backlink_publisher.recheck.probe.recheck_link", _fake_recheck_link)
    monkeypatch.setattr("backlink_publisher.recheck.events_io.emit_recheck", lambda store, results: None)

    resp = client.post(
        "/api/v1/health/scorecard/recheck-link",
        # Client sends a DIFFERENT (but canonicalization-equivalent) string.
        data=_json.dumps({"live_url": "https://STORED.example/canonical/"}),
        content_type="application/json",
        headers=_origin_headers(),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["live_url"] == stored_record["live_url"]
    assert len(probed_records) == 1
    assert probed_records[0]["live_url"] == stored_record["live_url"]


def test_webui_health_recheck_link_probe_failure_is_fail_soft_200(client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("probe network error")

    monkeypatch.setattr(hd, "_published_candidate", lambda store, url: {
        "live_url": "https://a.com/x", "target_url": "https://a.com",
        "host": "a.com", "article_id": "a1", "platform": "blogger",
    })
    monkeypatch.setattr("backlink_publisher.recheck.probe.recheck_link", _boom)
    resp = client.post(
        "/api/v1/health/scorecard/recheck-link",
        data=_json.dumps({"live_url": "https://a.com/x"}),
        content_type="application/json",
        headers=_origin_headers(),
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": False, "error_code": "probe_failed"}


# ── POST /health/actions/* ────────────────────────────────────────────────


def _known_platform_true(monkeypatch):
    monkeypatch.setattr(hd, "_known_platform", lambda platform: True)


def test_webui_health_action_pause_happy_path(client, monkeypatch):
    _known_platform_true(monkeypatch)
    monkeypatch.setattr(
        "backlink_publisher.health.persistence.locked_store.set_paused",
        lambda platform, paused, cfg: paused,
    )
    resp = client.post(
        "/api/v1/health/actions/pause",
        json={"platform": "blogger", "paused": True},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "platform": "blogger", "paused": True}


def test_webui_health_action_pause_resume_round_trip(client, monkeypatch):
    """pause then resume -- labels stay consistent (paused True then False)."""
    _known_platform_true(monkeypatch)
    monkeypatch.setattr(
        "backlink_publisher.health.persistence.locked_store.set_paused",
        lambda platform, paused, cfg: paused,
    )
    r1 = client.post("/api/v1/health/actions/pause", json={"platform": "blogger", "paused": True})
    r2 = client.post("/api/v1/health/actions/pause", json={"platform": "blogger", "paused": False})
    assert r1.get_json()["paused"] is True
    assert r2.get_json()["paused"] is False


def test_webui_health_action_pause_unknown_platform_400_no_side_effect(client, monkeypatch):
    called = []
    monkeypatch.setattr(hd, "_known_platform", lambda platform: False)
    monkeypatch.setattr(
        "backlink_publisher.health.persistence.locked_store.set_paused",
        lambda *a, **k: called.append(True),
    )
    resp = client.post(
        "/api/v1/health/actions/pause", json={"platform": "nonexistent", "paused": True},
    )
    assert resp.status_code == 400
    assert called == []


def test_webui_health_action_pause_write_failure_fail_soft_200(client, monkeypatch):
    _known_platform_true(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("backlink_publisher.health.persistence.locked_store.set_paused", _boom)
    resp = client.post("/api/v1/health/actions/pause", json={"platform": "blogger", "paused": True})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is False


def test_webui_health_action_reverify_happy_path(client, monkeypatch):
    _known_platform_true(monkeypatch)
    monkeypatch.setattr(
        "backlink_publisher.publishing.adapters.verify_adapter_setup",
        lambda platform, cfg: None,
    )
    resp = client.post("/api/v1/health/actions/reverify", json={"platform": "blogger"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "platform": "blogger", "ready": True, "reason": ""}


def test_webui_health_action_reverify_dependency_error_is_curated_ok_true(client, monkeypatch):
    from backlink_publisher._util.errors import DependencyError

    _known_platform_true(monkeypatch)

    def _raise_dep(*a, **k):
        raise DependencyError("missing credentials.json")

    monkeypatch.setattr("backlink_publisher.publishing.adapters.verify_adapter_setup", _raise_dep)
    resp = client.post("/api/v1/health/actions/reverify", json={"platform": "blogger"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "ok": True, "platform": "blogger", "ready": False,
        "reason": "missing credentials.json",
    }


def test_webui_health_action_reverify_generic_error_never_leaks_str_exc(client, monkeypatch):
    _known_platform_true(monkeypatch)
    sentinel = "sqlite-secret-path"

    def _boom(*a, **k):
        raise RuntimeError(sentinel)

    monkeypatch.setattr("backlink_publisher.publishing.adapters.verify_adapter_setup", _boom)
    resp = client.post("/api/v1/health/actions/reverify", json={"platform": "blogger"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["reason"] == "RuntimeError"
    assert sentinel not in resp.get_data(as_text=True)


def test_webui_health_action_circuit_reset_happy_path(client, monkeypatch):
    _known_platform_true(monkeypatch)
    monkeypatch.setattr(
        "backlink_publisher.publishing.reliability.circuit.reset_circuit",
        lambda platform, cfg: None,
    )
    resp = client.post("/api/v1/health/actions/circuit-reset", json={"platform": "blogger"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "platform": "blogger"}


def test_webui_health_action_circuit_reset_unknown_platform_400(client, monkeypatch):
    monkeypatch.setattr(hd, "_known_platform", lambda platform: False)
    resp = client.post("/api/v1/health/actions/circuit-reset", json={"platform": "nonexistent"})
    assert resp.status_code == 400


@pytest.mark.parametrize("path", [
    "/api/v1/health/actions/pause",
    "/api/v1/health/actions/reverify",
    "/api/v1/health/actions/circuit-reset",
])
def test_webui_health_actions_non_loopback_403(client, path):
    """The inline loopback gate isn't blueprint-scoped (unlike health_actions.py's
    original) -- must be enforced per-view since api_v1 is one shared blueprint."""
    resp = client.post(
        path, json={"platform": "blogger"},
        environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("path", [
    "/api/v1/health/actions/pause",
    "/api/v1/health/actions/reverify",
    "/api/v1/health/actions/circuit-reset",
])
def test_webui_health_actions_x_forwarded_for_spoof_still_403(client, path):
    """X-Forwarded-For claiming loopback must not bypass the gate -- it checks
    the real TCP peer (request.remote_addr), not a client-controlled header."""
    resp = client.post(
        path, json={"platform": "blogger"},
        environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
        headers={"X-Forwarded-For": "127.0.0.1"},
    )
    assert resp.status_code == 403
