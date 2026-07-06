"""plan 2026-06-04-002 Unit 1 — POST /ce:keep-alive/recheck route."""
__tier__ = "integration"

import pytest

import webui
from webui_app.services.keepalive_job import registry as keepalive_registry

_PORT = 8888
_GOOD_ORIGIN = {"Origin": f"http://127.0.0.1:{_PORT}"}


@pytest.fixture
def client(disable_csrf):
    keepalive_registry.reset_for_tests()
    return webui.app.test_client()


# ── POST async start ─────────────────────────────────────────────────────────

def test_post_with_good_origin_starts_job(client):
    resp = client.post("/ce:keep-alive/recheck", headers=_GOOD_ORIGIN)
    assert resp.status_code in (202, 409)
    body = resp.get_json()
    assert "job_id" in body


def test_post_without_origin_returns_403(client):
    assert client.post("/ce:keep-alive/recheck").status_code == 403


# ── GET with flash params ────────────────────────────────────────────────────

def test_get_renders_flash_alert(client):
    resp = client.get("/ce:keep-alive/jinja?flash_type=success&flash_msg=已核实+3+条")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "alert-success" in body
    assert "已核实" in body


def test_get_no_flash_shows_no_alert(client):
    resp = client.get("/ce:keep-alive/jinja")
    assert resp.status_code == 200
    body = resp.data.decode()
    # The flash block has a btn-close dismiss button; staleBanner is always in HTML
    # but hidden (d-none) and has no btn-close — so btn-close absence = no flash block.
    assert 'data-bs-dismiss="alert"' not in body


# ── button not disabled ──────────────────────────────────────────────────────

def test_recheck_button_is_enabled(client):
    resp = client.get("/ce:keep-alive/jinja")
    assert resp.status_code == 200
    body = resp.data.decode()
    # Button must not carry the disabled attribute.
    assert 'id="recheckBtn"' in body
    assert 'disabled' not in body.split('id="recheckBtn"')[1].split('>')[0]
