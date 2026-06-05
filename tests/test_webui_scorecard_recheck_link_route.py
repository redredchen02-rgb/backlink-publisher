"""POST /ce:health/scorecard/recheck-link — single-link recheck (Plan
2026-06-05-009 U4).

Outbound-probe route: enforces the Origin guard on top of the app-level CSRF
guard, and — R8, anti-SSRF — only re-probes a live_url that already has a
publish event in events.db (a client-supplied unpublished URL is rejected with
NO probe fired). Writes a link.rechecked event via the keepalive emit path, and
returns an honest structured result that distinguishes a call failure from a
PROBE_ERROR verdict.
"""
from __future__ import annotations

__tier__ = "integration"

import pytest

from backlink_publisher.events import EventStore, kinds
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck import verdicts

_GOOD_ORIGIN = {"Origin": "http://127.0.0.1:8888"}
LIVE = "https://telegra.ph/published-a"
TARGET = "https://51acgs.com/c/1/"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    return app.test_client()


def _seed_published(live_url=LIVE, platform="telegraph", kind=kinds.PUBLISH_CONFIRMED):
    EventStore().append(
        kind,
        {"live_url": live_url, "platform": platform},
        target_url=TARGET,
        host="telegra.ph",
        article_id=1,
    )


def _link_rechecked_count():
    rows = EventStore().query(
        "SELECT COUNT(*) AS n FROM events WHERE kind = ?", (LINK_RECHECKED,)
    )
    return rows[0]["n"]


def _patch_probe(monkeypatch, verdict=verdicts.ALIVE, raises=False):
    import backlink_publisher.recheck.probe as probe_mod

    calls = []

    def _fake(record, *, probe, **kw):
        calls.append(record)
        if raises:
            raise RuntimeError("probe boom")
        return {**record, "verdict": verdict, "reason": None}

    monkeypatch.setattr(probe_mod, "recheck_link", _fake)
    return calls


def test_recheck_published_link_writes_event_and_returns_verdict(client, monkeypatch):
    _seed_published()
    _patch_probe(monkeypatch, verdict=verdicts.ALIVE)
    before = _link_rechecked_count()
    resp = client.post(
        "/ce:health/scorecard/recheck-link", json={"live_url": LIVE}, headers=_GOOD_ORIGIN
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["verdict"] == verdicts.ALIVE
    assert _link_rechecked_count() == before + 1  # emit_recheck path, not recheck_one


def test_unpublished_link_is_rejected_without_probing(client, monkeypatch):
    # R8: a live_url with no publish event must 404 and fire NO outbound probe.
    calls = _patch_probe(monkeypatch, verdict=verdicts.ALIVE)
    resp = client.post(
        "/ce:health/scorecard/recheck-link",
        json={"live_url": "https://evil.example/attacker"},
        headers=_GOOD_ORIGIN,
    )
    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False
    assert calls == []  # probe never called


def test_missing_origin_is_403(client):
    assert client.post(
        "/ce:health/scorecard/recheck-link", json={"live_url": LIVE}
    ).status_code == 403


def test_external_origin_is_403(client):
    resp = client.post(
        "/ce:health/scorecard/recheck-link",
        json={"live_url": LIVE},
        headers={"Origin": "http://evil.example.com:8888"},
    )
    assert resp.status_code == 403


def test_probe_error_verdict_is_ok_true_not_call_failure(client, monkeypatch):
    _seed_published()
    _patch_probe(monkeypatch, verdict=verdicts.PROBE_ERROR)
    resp = client.post(
        "/ce:health/scorecard/recheck-link", json={"live_url": LIVE}, headers=_GOOD_ORIGIN
    )
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True               # the call succeeded...
    assert body["verdict"] == verdicts.PROBE_ERROR  # ...the verdict is probe_error


def test_emit_failure_returns_ok_false_no_500(client, monkeypatch):
    _seed_published()
    _patch_probe(monkeypatch, verdict=verdicts.ALIVE)
    import backlink_publisher.recheck.events_io as io_mod

    def _boom(*a, **k):
        raise RuntimeError("db boom")

    monkeypatch.setattr(io_mod, "emit_recheck", _boom)
    resp = client.post(
        "/ce:health/scorecard/recheck-link", json={"live_url": LIVE}, headers=_GOOD_ORIGIN
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error_code"] == "probe_failed"


def test_published_via_unverified_is_also_probeable(client, monkeypatch):
    # Membership accepts publish.unverified, not only publish.confirmed.
    _seed_published(kind=kinds.PUBLISH_UNVERIFIED)
    _patch_probe(monkeypatch, verdict=verdicts.ALIVE)
    before = _link_rechecked_count()
    resp = client.post(
        "/ce:health/scorecard/recheck-link", json={"live_url": LIVE}, headers=_GOOD_ORIGIN
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert _link_rechecked_count() == before + 1


def test_client_url_matches_published_via_canonicalization(client, monkeypatch):
    # The client live_url is a lookup KEY matched canonically — a trailing-slash /
    # utm variant still resolves to the published record, and the probed URL is the
    # STORED one (anti-SSRF: client string never reaches the probe verbatim).
    _seed_published(live_url=LIVE)
    calls = _patch_probe(monkeypatch, verdict=verdicts.ALIVE)
    resp = client.post(
        "/ce:health/scorecard/recheck-link",
        json={"live_url": LIVE + "?utm_source=x"},
        headers=_GOOD_ORIGIN,
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert calls and calls[0]["live_url"] == LIVE  # probed the stored URL, not client's


def test_missing_live_url_is_400(client):
    resp = client.post(
        "/ce:health/scorecard/recheck-link", json={}, headers=_GOOD_ORIGIN
    )
    assert resp.status_code == 400


def test_csrf_enforced_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app

    app = create_app()
    app.config["CSRF_ENABLED"] = True
    c = app.test_client()
    # No CSRF token + good origin → app-level guard rejects before the handler.
    resp = c.post(
        "/ce:health/scorecard/recheck-link", json={"live_url": LIVE}, headers=_GOOD_ORIGIN
    )
    assert resp.status_code == 403
