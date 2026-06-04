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
_CORE_ROUTES = ["/", "/ce:keep-alive", "/ce:health", "/settings"]
_TRIMMED_NAV_LABELS = ["排程", "权益", "PR队列"]


@pytest.fixture
def client():
    app = create_app()
    app.config["CSRF_ENABLED"] = False
    return app.test_client()


@pytest.fixture
def lite_on(monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_LITE", "1")


@pytest.fixture
def lite_off(monkeypatch):
    monkeypatch.delenv("BACKLINK_PUBLISHER_LITE", raising=False)


def test_full_nav_when_lite_off(client, lite_off):
    html = client.get("/ce:keep-alive").get_data(as_text=True)
    for label in _TRIMMED_NAV_LABELS:
        assert label in html


def test_nav_trimmed_to_core_when_lite_on(client, lite_on):
    html = client.get("/ce:keep-alive").get_data(as_text=True)
    assert "保活" in html and "设置" in html          # core kept
    for label in _TRIMMED_NAV_LABELS:
        assert label not in html                        # Pro/secondary gone


@pytest.mark.parametrize("path", _HIDDEN_ROUTES)
def test_pro_routes_404_when_lite_on(client, lite_on, path):
    # Gated server-side, not merely unlinked — URL guessing yields 404.
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", _HIDDEN_ROUTES)
def test_pro_routes_reachable_when_lite_off(client, lite_off, path):
    assert client.get(path).status_code != 404


@pytest.mark.parametrize("path", _CORE_ROUTES)
def test_core_routes_reachable_when_lite_on(client, lite_on, path):
    assert client.get(path).status_code == 200
