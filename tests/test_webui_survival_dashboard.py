"""R5: survival-rate dashboard route + view service.

Mirrors test_webui_keep_alive_status: exercises the injectable service view for
the data states and the real route for a never-500 render. The percentage is
derived from the link.rechecked time series with honest sample-size labelling.
"""

from __future__ import annotations

__tier__ = "integration"

from datetime import datetime, timedelta, timezone, UTC

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from backlink_publisher.recheck import verdicts
from webui_app.services.survival import build_survival_view

NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _confirm(store, aid, *, days_ago, host="medium.com"):
    ts = (NOW - timedelta(days=days_ago)).isoformat()
    store.append(PUBLISH_CONFIRMED, {"live_url": f"https://{host}/{aid}"},
                 host=host, article_id=aid, ts_utc=ts)


def _recheck(store, aid, verdict, *, days_ago=1):
    ts = (NOW - timedelta(days=days_ago)).isoformat()
    store.append(LINK_RECHECKED, {"verdict": verdict}, article_id=aid, ts_utc=ts)


def test_view_ok_rate_and_labels(store):
    for i in range(1, 9):
        _confirm(store, i, days_ago=40)
        _recheck(store, i, verdicts.ALIVE if i <= 6 else verdicts.LINK_STRIPPED)
    view = build_survival_view(store=store, now=NOW)
    assert view["state"] == "ok"
    assert view["has_rate"] is True
    assert view["display"] == "75.0%"     # 6/8
    assert view["sample_size"] == 8
    assert view["headline"] and view["sub"]


def test_view_insufficient_suppresses_number(store):
    _confirm(store, 1, days_ago=40)
    _recheck(store, 1, verdicts.ALIVE)
    view = build_survival_view(store=store, now=NOW)
    assert view["state"] == "insufficient"
    assert view["has_rate"] is False
    assert view["display"] == "—"
    assert view["sample_size"] == 1       # surfaced honestly


def test_view_empty_state(store):
    view = build_survival_view(store=store, now=NOW)
    assert view["state"] == "empty"
    assert view["has_rate"] is False


def test_view_stale_flags_partial(store):
    for i in range(1, 4):
        _confirm(store, i, days_ago=40)
        _recheck(store, i, verdicts.ALIVE)
    _confirm(store, 9, days_ago=50)       # mature, never rechecked
    view = build_survival_view(store=store, now=NOW)
    assert view["stale"] is True
    assert view["partial"] is True


def test_view_serializable_no_sets(store):
    import json

    view = build_survival_view(store=store, now=NOW)
    json.dumps(view)  # must not raise


def test_route_renders_200_and_csrf():
    from webui_app import create_app

    app = create_app()
    client = app.test_client()
    resp = client.get("/survival-dashboard")
    assert resp.status_code == 200          # never 500, even on empty store
    assert "存活率".encode() in resp.data
    # CSRF meta + asset versioning come from base.html.
    assert b"csrf-token" in resp.data or b"csrf_token" in resp.data


def test_route_never_500s_when_render_raises(monkeypatch, caplog):
    # The _render call must be inside the try: a template/render fault on the real
    # view degrades to the unavailable render, never a 500 (the docstring's promise).
    from webui_app import create_app
    import webui_app.routes.survival_dashboard as route

    calls = {"n": 0}
    real_render = route._render

    def _flaky_render(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("template boom")
        return real_render(*a, **kw)

    monkeypatch.setattr(route, "_render", _flaky_render)
    app = create_app()
    with caplog.at_level("WARNING"):
        resp = app.test_client().get("/survival-dashboard")
    assert resp.status_code == 200
    assert calls["n"] == 2  # first (real-view) render raised; fallback render ran
