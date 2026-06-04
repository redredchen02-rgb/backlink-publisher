"""R5 — fail-safe WebUI runtime defaults (plan 2026-06-04-001 Unit 2).

The Werkzeug debug page is an interactive RCE console; this WebUI is no-auth +
loopback + holds live publishing credentials, so debug must default OFF and a
fresh app must not leak any debug-class config. SECRET_KEY, when supplied, must
be honored so sessions/CSRF survive restart.
"""
from __future__ import annotations

import pytest


def test_debug_mode_defaults_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from webui import _resolve_debug_mode

    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    assert _resolve_debug_mode() is False


def test_debug_mode_opt_in_with_explicit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    from webui import _resolve_debug_mode

    monkeypatch.setenv("FLASK_DEBUG", "1")
    assert _resolve_debug_mode() is True


@pytest.mark.parametrize("value", ["0", "true", "True", "yes", ""])
def test_debug_mode_only_exact_1_enables(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from webui import _resolve_debug_mode

    monkeypatch.setenv("FLASK_DEBUG", value)
    assert _resolve_debug_mode() is False


def test_secret_key_env_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    from webui_app import create_app

    monkeypatch.setenv("SECRET_KEY", "pinned-test-key-12345")
    app = create_app()
    assert app.secret_key == "pinned-test-key-12345"


def test_created_app_has_no_debug_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression fence: a future config edit must not silently re-open the
    Werkzeug debugger / exception propagation."""
    from webui_app import create_app

    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    app = create_app()
    assert app.debug is False
    assert app.config.get("PROPAGATE_EXCEPTIONS") is not True
    assert app.config.get("TEMPLATES_AUTO_RELOAD") is not True
