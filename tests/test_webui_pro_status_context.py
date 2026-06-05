"""Plan 2026-06-05-003 U1 — pro_status single source of truth.

Covers the pure ``settings_service.pro_status_summary`` helper plus the
``inject_pro_status`` context processor, including the ``llm_configured``
back-compat alias that the shipped copilot panel still reads.
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest

from webui_app.services import settings_service


# ── pure summary ─────────────────────────────────────────────────────────────


def test_summary_happy_path_configured():
    out = settings_service.pro_status_summary({
        "endpoint": "https://api.example.com/v1",
        "api_key": "sk-secret",
        "model": "gpt-4",
        "use_article_gen": True,
        "use_image_gen": False,
    })
    assert out["configured"] is True
    assert out["article_gen"] is True
    assert out["image_gen"] is False
    assert out["endpoint_host"] == "api.example.com"
    assert out["model"] == "gpt-4"


def test_summary_endpoint_without_key_is_unconfigured():
    out = settings_service.pro_status_summary({
        "endpoint": "https://api.example.com/v1",
        "api_key": "",
    })
    assert out["configured"] is False


def test_summary_last_test_absent_is_none():
    out = settings_service.pro_status_summary({
        "endpoint": "https://api.example.com",
        "api_key": "k",
    })
    assert out["last_test"] is None


def test_summary_last_test_passed_through():
    lt = {"ok": True, "at": "2026-06-05T10:00:00", "message": "连接成功！"}
    out = settings_service.pro_status_summary({
        "endpoint": "https://api.example.com",
        "api_key": "k",
        "last_test": lt,
    })
    assert out["last_test"] == lt


def test_summary_malformed_last_test_coerced_to_none():
    out = settings_service.pro_status_summary({
        "endpoint": "https://api.example.com",
        "api_key": "k",
        "last_test": "not-a-dict",
    })
    assert out["last_test"] is None


def test_summary_never_contains_api_key():
    secret = "sk-super-secret-value"
    out = settings_service.pro_status_summary({
        "endpoint": "https://api.example.com",
        "api_key": secret,
        "model": "m",
    })
    assert "api_key" not in out
    assert secret not in json.dumps(out)


def test_summary_empty_settings_is_safe_default():
    out = settings_service.pro_status_summary({})
    assert out == {
        "configured": False, "endpoint_host": "", "model": "",
        "article_gen": False, "image_gen": False, "last_test": None,
    }


# ── context processor (alias back-compat) ────────────────────────────────────


@pytest.fixture
def cfg_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _gather_context(app):
    with app.app_context(), app.test_request_context("/"):
        ctx = {}
        for processor in app.template_context_processors[None]:
            ctx.update(processor())
    return ctx


def test_context_processor_exposes_pro_status_and_alias(cfg_dir):
    path = settings_service.llm_settings_file()
    path.write_text(json.dumps({
        "endpoint": "https://api.example.com/v1",
        "api_key": "sk-key",
        "model": "gpt-4",
        "use_article_gen": True,
    }), encoding="utf-8")
    path.chmod(0o600)

    from webui_app import create_app
    ctx = _gather_context(create_app())

    assert ctx["pro_status"]["configured"] is True
    assert ctx["pro_status"]["endpoint_host"] == "api.example.com"
    # back-compat: copilot panel reads this boolean
    assert ctx["llm_configured"] is True


def test_context_processor_safe_default_when_unconfigured(cfg_dir):
    from webui_app import create_app
    ctx = _gather_context(create_app())
    assert ctx["pro_status"]["configured"] is False
    assert ctx["llm_configured"] is False
