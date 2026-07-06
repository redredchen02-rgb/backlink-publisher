"""R7 + R8 — LITE operator surface reduction (plan 2026-06-04-001 Unit 10).

In the LITE edition the operator nav is trimmed to the keep-alive core
(保活 / 发布 / 健康 / 设置) and the Pro / not-yet-implemented blueprints are hidden
*server-side* (404), not merely unlinked. With the flag off (default) the full
surface is intact, so the existing Pro test suite is unaffected.
"""
__tier__ = "integration"

import pytest

from webui_app import create_app

# Pro / unimplemented blueprints gated in LITE — one representative GET each.
# Baseline (flag off) statuses: copilot/advice 200, metrics 200, seo 400,
# pr-queue 200 — all non-404, so the gate's 404 is observable.
_HIDDEN_ROUTES = ["/copilot/advice", "/metrics", "/api/seo/anchors", "/pr-queue"]
# '/jinja' not bare '/' — Plan 2026-07-06-004 Unit 4 made bare '/' an
# unconditional redirect to the SPA ('/app/'), so it no longer returns 200
# directly; '/jinja' is the legacy Jinja fallback that still does (same
# content this list originally meant to exercise).
_CORE_ROUTES = ["/jinja", "/ce:keep-alive/jinja", "/ce:health"]
_TRIMMED_NAV_LABELS = ["排程", "权益", "PR队列"]


@pytest.fixture
def client():
    # All assertions here are GET-only, so the CSRF guard never engages — no
    # need to disable it (raw-mutating CSRF_ENABLED would also trip the
    # security-toggle mutation gate; use the conftest disable_csrf fixture if a
    # POST is ever added here).
    return create_app().test_client()


@pytest.fixture
def lite_on(monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_LITE", "1")


@pytest.fixture
def lite_off(monkeypatch):
    monkeypatch.delenv("BACKLINK_PUBLISHER_LITE", raising=False)


def test_full_nav_when_lite_off(client, lite_off):
    html = client.get("/ce:keep-alive/jinja").get_data(as_text=True)
    for label in _TRIMMED_NAV_LABELS:
        assert label in html


def test_nav_trimmed_to_core_when_lite_on(client, lite_on):
    html = client.get("/ce:keep-alive/jinja").get_data(as_text=True)
    # Assert the core nav *link* survives — not the bare '保活' label, which also
    # renders in the page title + navbar-brand and would pass even if the nav
    # anchor were deleted. '设置' is nav-unique, so its bare label is sound.
    assert 'href="/ce:keep-alive" class="app-sidebar__item' in html   # 保活 sidebar link
    assert "设置" in html
    for label in _TRIMMED_NAV_LABELS:
        assert label not in html                        # Pro/secondary gone


@pytest.mark.parametrize("path", _HIDDEN_ROUTES)
def test_pro_routes_404_when_lite_on(client, lite_on, path):
    # Gated server-side, not merely unlinked: a GET to a hidden blueprint 404s.
    # (A no-token POST to these GET-only paths 403s on the CSRF guard first —
    # uniform with any unmatched path, so it discloses no hidden-route existence.)
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", _HIDDEN_ROUTES)
def test_pro_routes_reachable_when_lite_off(client, lite_off, path):
    assert client.get(path).status_code != 404


@pytest.mark.parametrize("path", _CORE_ROUTES)
def test_core_routes_reachable_when_lite_on(client, lite_on, path):
    assert client.get(path).status_code == 200
