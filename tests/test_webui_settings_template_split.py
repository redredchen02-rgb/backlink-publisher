"""settings.html template split — Plan B2 (CSS, JS, card partials)."""

from __future__ import annotations

import json
import re

import pytest

from webui_app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── Unit 1: CSS ──────────────────────────────────────────────────────────────

def test_settings_css_served(client):
    """GET /static/css/settings.css returns 200 text/css."""
    resp = client.get("/static/css/settings.css")
    assert resp.status_code == 200
    assert "text/css" in resp.content_type


def test_settings_page_links_to_css(client):
    """GET /settings includes <link> pointing to css/settings.css."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "css/settings.css" in resp.data.decode()


def test_settings_page_has_no_inline_style(client):
    """GET /settings response has no inline <style> element."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "<style>" not in resp.data.decode()


def test_settings_template_inline_styles_confined_to_loading_overlay():
    """settings.html proper must not carry static inline ``style=""`` attributes.

    The R10 follow-up (Plan 2026-06-03-003) extracted every static inline style
    into named settings.css classes. The only sanctioned exception is the
    ``#_loadingOverlay`` widget, whose ``display`` is toggled by settings.js (a
    data-driven exception R10 explicitly allows). Included sub-template partials
    (``_settings_channel_*`` etc.) are out of scope per the plan's scope boundary,
    so this asserts on the template source — not the rendered response.

    The original ``test_settings_page_has_no_inline_style`` only catches ``<style>``
    blocks, not ``style=""`` attributes — which is why the R10 residual slipped
    through. This closes that gap.
    """
    import pathlib

    import webui_app

    tpl = pathlib.Path(webui_app.__file__).parent / "templates" / "settings.html"
    lines = tpl.read_text(encoding="utf-8").splitlines()
    overlay_idx = next(
        (i for i, line in enumerate(lines) if "_loadingOverlay" in line), None
    )
    assert overlay_idx is not None, "expected the #_loadingOverlay widget in settings.html"
    stray = [
        (i + 1, line.strip())
        for i, line in enumerate(lines)
        if 'style="' in line and i < overlay_idx
    ]
    assert not stray, (
        'settings.html has inline style="" attributes outside the JS-toggled '
        f"#_loadingOverlay widget — extract them to settings.css classes: {stray}"
    )


# ── Unit 2: JS ───────────────────────────────────────────────────────────────

def test_settings_js_served(client):
    """GET /static/js/settings.js (ESM entry, replaced settings_main.js in U3)
    returns 200 application/javascript."""
    resp = client.get("/static/js/settings.js")
    assert resp.status_code == 200
    assert "javascript" in resp.content_type


def test_settings_bootstrap_var_present(client):
    """GET /settings includes window.__settingsBootstrap with plans_list and profiles."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "window.__settingsBootstrap" in body
    m = re.search(r'window\.__settingsBootstrap\s*=\s*(\{.*?\});', body, re.DOTALL)
    assert m, "window.__settingsBootstrap assignment not found"
    data = json.loads(m.group(1))
    assert "plans_list" in data
    assert "profiles" in data


def test_settings_no_jinja_interpolation_in_page(client):
    """GET /settings must not contain inline Jinja-rendered _plansData or _PROFILES."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "let _plansData = " not in body
    assert "const _PROFILES = [" not in body


# ── Unit 3: Card partials ────────────────────────────────────────────────────

def test_settings_renders_llm_integration_section(client):
    """GET /settings renders LLM integration card from partial."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "进阶 LLM 整合" in body


def test_settings_renders_diagnostics_section(client):
    """GET /settings renders diagnostics console card from partial."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "生成诊断控制台" in body


def test_settings_renders_banner_section(client):
    """GET /settings renders AI banner card from partial."""
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "AI Banner" in body


def test_settings_html_final_size():
    """settings.html must be ≤400 lines after all splits (R3)."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "webui_app" / "templates" / "settings.html"
    ).read_text(encoding="utf-8")
    lines = len(src.splitlines())
    assert lines <= 400, f"settings.html is {lines} lines, expected ≤400"


def test_settings_extends_base_layout():
    """Plan 007 U2: settings.html extends base; head is base-owned (one head, one
    csrf-meta), but the legacy settings_main.js stays wired (atomic boundary)."""
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[1]
        / "webui_app" / "templates" / "settings.html"
    ).read_text(encoding="utf-8")
    assert "{% extends 'base.html' %}" in src
    assert "<!DOCTYPE" not in src  # head comes from base now
    assert "js/settings.js" in src  # ESM entry (U3); settings_main.js removed
    assert "settings_main.js" not in src
    assert 'type="module"' in src  # settings.js loaded as a module


# ── Plan 007 U2: CSRF survives the extends migration (CSRF_ENABLED=True) ──────

def test_settings_binding_form_csrf_token_non_empty_when_enabled(tmp_path, monkeypatch):
    """With CSRF enabled, a channel binding form's hidden csrf_token must render
    non-empty after the base-layout migration (the include-with-context flow that
    supplies csrf_token must not be severed by `{% extends %}`)."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = True
    body = app.test_client().get("/settings").data.decode()
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m, "no hidden csrf_token input rendered on /settings"
    assert m.group(1).strip(), "csrf_token rendered EMPTY — context flow severed"


# ── Plan 007 U3: inline-handler elimination + CSRF 403 regression ─────────────

def test_settings_has_no_inline_event_handlers(client):
    """Core U3 success metric: the rendered settings page carries zero inline
    on* handlers (all migrated to data-action + module addEventListener) and no
    inline runVelogLogin <script>."""
    body = client.get("/settings").data.decode()
    assert not re.search(r'\son(click|change|submit|input|keyup|keydown|blur|focus)=', body), \
        "an inline on* handler survived the ESM migration"
    assert "function runVelogLogin" not in body, "velog inline script not removed"
    assert 'data-action="velog-login"' in body  # velog bind now uses data-action


def test_settings_post_rejected_without_csrf_token(tmp_path, monkeypatch):
    """CSRF 403 regression: a state-changing settings POST is rejected (403) when
    no token is supplied via EITHER transport — the guard is untouched by U3."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = True
    resp = app.test_client().post("/settings/test-llm-connection", data={})
    assert resp.status_code == 403
