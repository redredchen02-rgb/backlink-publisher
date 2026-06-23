"""Unified empty-state onboarding CTA — Plan 2026-06-18-001 U2 (R2).

settings.js tests removed in U8 (Plan 2026-06-18-002) — the legacy /settings
Jinja page and its JS bundle (settings.js) were retired; the SPA at /app/settings
replaces the settings UI.

Remaining tests cover index.js empty-state wiring.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import re
from pathlib import Path

import pytest

from webui_app import create_app

_JS_DIR = Path(__file__).resolve().parents[1] / "webui_app" / "static" / "js"
_INDEX_JS = (_JS_DIR / "index.js").read_text(encoding="utf-8")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ── imports + served assets ────────────────────────────────────────────────

def test_index_js_imports_states(client):
    """index.js is served and imports renderEmpty + renderError from ui/states.js."""
    resp = client.get("/static/js/index.js")
    assert resp.status_code == 200
    assert "javascript" in resp.content_type
    assert "import { renderEmpty, renderError } from './ui/states.js'" in _INDEX_JS


# ── cause #1: true zero-config -> renderEmpty WITH 去配置 CTA ────────────────

def test_index_zero_config_renders_cta(client):
    """index.js wires a 去配置 CTA (actionLabel + onAction) for the no-channel case."""
    assert "actionLabel: '去配置'" in _INDEX_JS
    assert "onAction: goToSettings" in _INDEX_JS
    # CTA navigates to settings (the onAction target).
    assert "function goToSettings()" in _INDEX_JS
    assert "/settings" in _INDEX_JS


def test_zero_config_cta_bound_via_addeventlistener_not_inline(client):
    """The CTA's onAction is bound via addEventListener inside states.js — never an
    inline on* handler. states.js is the single binder; the drivers pass a function."""
    states = (_JS_DIR / "ui" / "states.js").read_text(encoding="utf-8")
    assert "btn.addEventListener('click', onAction)" in states
    # The drivers must hand states.js a function, not an inline-handler string.
    assert "onAction: goToSettings" in _INDEX_JS


def test_index_bootstrap_exposes_has_channels(client):
    """The index page exposes has_channels so JS can tell zero-config from
    has-config-but-empty (cause #1 vs #2) without a backend call."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    m = re.search(r"window\.__indexBootstrap\s*=\s*(\{.*?\});", body, re.DOTALL)
    assert m, "window.__indexBootstrap not found"
    data = json.loads(m.group(1))
    assert "has_channels" in data
    assert isinstance(data["has_channels"], bool)
    # index.js reads it to gate the config CTA.
    assert "BOOT.has_channels === true" in _INDEX_JS


# ── cause #2: has config but empty -> renderEmpty WITHOUT config CTA ─────────

def test_index_filtered_empty_has_no_config_cta(client):
    """The filtered-empty path uses「当前条件无结果」and a clear-filter action — it
    must NOT offer the 去配置 CTA (config already exists)."""
    assert "当前条件无结果" in _INDEX_JS
    assert "actionLabel: '清除筛选'" in _INDEX_JS


def test_index_has_config_empty_branch_has_no_cta(client):
    """The has-config-but-empty branch of _initEmptyState (the `else`) renders a
    plain renderEmpty with NO actionLabel/onAction (去配置 only for zero-config)."""
    body = _INDEX_JS.split("function _initEmptyState()", 1)[1].split("function _boot()", 1)[0]
    # The 去配置 CTA lives only in the !HAS_CHANNELS (zero-config) branch.
    assert body.count("actionLabel") == 1, "has-config branch must not add a second CTA"
    assert "去配置" in body.split("} else {", 1)[0], "去配置 CTA must be in the zero-config branch"
    assert "去配置" not in body.split("} else {", 1)[1], "has-config branch must not show 去配置"


# ── cause #3: failure -> renderError (NOT empty) ────────────────────────────

def test_index_error_path_uses_render_error(client):
    """A failure to derive the state uses renderError with a retry, not renderEmpty."""
    assert "renderError(container" in _INDEX_JS
    assert "onRetry: () => window.location.reload()" in _INDEX_JS


# ── anti-rot ────────────────────────────────────────────────────────────────

def test_no_inline_on_handlers_in_index_js():
    """index.js must not introduce an inline on* handler string (data-action +
    delegated addEventListener only)."""
    assert not re.search(r"""['"]on(click|change|submit|input|keyup)['"]\s*:""", _INDEX_JS), (
        "an inline on* handler key crept into index.js"
    )


def test_cta_text_rides_action_label_not_innerhtml():
    """CTA text passes through actionLabel (states.js -> textContent), never
    innerHTML. The drivers must not assemble the CTA via innerHTML."""
    states = (_JS_DIR / "ui" / "states.js").read_text(encoding="utf-8")
    # states.js renders actionLabel as text, and binds the click listener.
    assert "text: actionLabel" in states
    # Driver must not hand-build the empty/CTA markup with innerHTML.
    assert "ui-empty__action" not in _INDEX_JS


def test_index_page_renders_empty_state_anchor(client):
    """On a fresh install (empty history) index renders the #indexEmptyState
    anchor that index.js fills with the unified empty state."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'id="indexEmptyState"' in body
    # The filtered-empty slot lives in the non-empty-history branch.
    src = (
        Path(__file__).resolve().parents[1]
        / "webui_app" / "templates" / "_tab_history.html"
    ).read_text(encoding="utf-8")
    assert 'id="historyEmptyFiltered"' in src
