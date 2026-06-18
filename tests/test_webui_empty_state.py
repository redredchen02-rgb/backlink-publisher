"""Unified empty-state onboarding CTA — Plan 2026-06-18-001 U2 (R2).

Zero-build ESM has no JS test runner, so (like test_webui_index_js_bootstrap.py)
these assert on the served JS source + the rendered template anchors:

  - index.js / settings.js import renderEmpty + renderError from ui/states.js
  - the THREE empty causes are wired distinctly:
      1. true zero-config (no bound channel) -> renderEmpty WITH a 去配置 CTA
         (actionLabel + onAction, bound via addEventListener inside states.js)
      2. has config but the current view/filter is empty -> renderEmpty WITHOUT
         the config CTA, message「当前条件无结果」
      3. request/state failure -> renderError (NOT an empty state)
  - anti-rot: no inline on* handlers survive; CTA text rides actionLabel (which
    states.js renders via textContent, never innerHTML).
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
_SETTINGS_JS = (_JS_DIR / "settings.js").read_text(encoding="utf-8")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    # GET-only tests (served static JS + rendered pages); CSRF guards mutating
    # methods only, so no CSRF toggle is needed (and raw mutation is gated).
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


def test_settings_js_imports_states(client):
    """settings.js is served and imports renderEmpty + renderError from ui/states.js."""
    resp = client.get("/static/js/settings.js")
    assert resp.status_code == 200
    assert "javascript" in resp.content_type
    assert "import { renderEmpty, renderError } from './ui/states.js'" in _SETTINGS_JS


# ── cause #1: true zero-config -> renderEmpty WITH 去配置 CTA ────────────────

def test_index_zero_config_renders_cta(client):
    """index.js wires a 去配置 CTA (actionLabel + onAction) for the no-channel case."""
    assert "actionLabel: '去配置'" in _INDEX_JS
    assert "onAction: goToSettings" in _INDEX_JS
    # CTA navigates to settings (the onAction target).
    assert "function goToSettings()" in _INDEX_JS
    assert "/settings" in _INDEX_JS


def test_settings_zero_config_renders_cta(client):
    """settings.js wires a 去配置 CTA opening the channels pane for zero-config."""
    assert "actionLabel: '去配置'" in _SETTINGS_JS
    # onAction switches to the channels pane (not an inline handler).
    assert "showPane('channels')" in _SETTINGS_JS


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


def test_settings_filter_no_results_has_no_config_cta(client):
    """settings.js renders「当前条件无结果」for the extension filter-no-results,
    without a 去配置 CTA."""
    assert "当前条件无结果" in _SETTINGS_JS
    # The ext-no-match branch passes no actionLabel/onAction (no CTA).
    nomatch = _SETTINGS_JS.split("renderEmpty(noMatch", 1)[1].split(")", 1)[0]
    assert "actionLabel" not in nomatch
    assert "onAction" not in nomatch


# ── cause #3: failure -> renderError (NOT empty) ────────────────────────────

def test_index_error_path_uses_render_error(client):
    """A failure to derive the state uses renderError with a retry, not renderEmpty."""
    assert "renderError(container" in _INDEX_JS
    assert "onRetry: () => window.location.reload()" in _INDEX_JS


def test_settings_error_path_uses_render_error(client):
    """settings.js falls back to renderError (with retry) on a failure deriving the
    channel list, instead of a blank/empty state."""
    assert "renderError(container" in _SETTINGS_JS


# ── anti-rot ────────────────────────────────────────────────────────────────

def test_no_inline_on_handlers_in_drivers():
    """Neither driver introduces an inline on* handler string (data-action +
    delegated addEventListener only)."""
    for src in (_INDEX_JS, _SETTINGS_JS):
        assert not re.search(r"""['"]on(click|change|submit|input|keyup)['"]\s*:""", src), (
            "an inline on* handler key crept into a driver"
        )


def test_cta_text_rides_action_label_not_innerhtml():
    """CTA text passes through actionLabel (states.js -> textContent), never
    innerHTML. The drivers must not assemble the CTA via innerHTML."""
    states = (_JS_DIR / "ui" / "states.js").read_text(encoding="utf-8")
    # states.js renders actionLabel as text, and binds the click listener.
    assert "text: actionLabel" in states
    # Neither driver hand-builds the empty/CTA markup with innerHTML.
    assert "ui-empty__action" not in _INDEX_JS
    assert "ui-empty__action" not in _SETTINGS_JS


def test_settings_sidebar_has_zero_config_anchor():
    """The sidebar template carries the JS-fillable #sidebarChannelsEmpty slot
    (with a no-JS fallback). It renders only in the genuine zero-platform branch;
    the 免綁定 (anon) channels mean a fresh install is rarely truly zero — so we
    assert the slot exists in source, not that a fresh render hits that branch."""
    src = (
        Path(__file__).resolve().parents[1]
        / "webui_app" / "templates" / "_settings_sidebar.html"
    ).read_text(encoding="utf-8")
    assert 'id="sidebarChannelsEmpty"' in src
    # No-JS fallback preserved.
    assert "（暂无渠道）" in src


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


def test_settings_page_renders_with_empty_wiring(client):
    """/settings renders 200 with the empty-state wiring in place (regression:
    the sidebar/overview edits must not break the page)."""
    resp = client.get("/settings")
    assert resp.status_code == 200
