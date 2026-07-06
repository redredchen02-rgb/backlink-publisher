"""Contract for the ``/api/v1`` LLM diagnostics routes.

Plan 2026-06-18-002 U7 (Settings). The connection/generation diagnostics were
ported HTML→JSON via the single-source ``LlmDiagnosticsAPI`` facade; the legacy
``/settings/test-llm-{connection,generation}`` routes + the SSRF-guard internals
are covered by ``test_webui_unit3_security.py`` / ``test_webui_llm_test_persist.py``
/ ``test_webui_core_routes.py``. This suite guards the JSON path: the diagnostic
envelope (``status`` ∈ ok|failed|error) is returned as-is (NOT problem+json), the
SSRF rejection still 400s, and a successful probe persists last-known health.

Mock note: the SSRF helpers + ``_load_llm_settings`` are patched on the facade
module (``webui_app.api.llm_diagnostics_api.*``) — the logic moved there.
"""

from __future__ import annotations

__tier__ = "integration"

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSRF = "test-csrf-token"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["csrf_token"] = CSRF
    return c


def _headers():
    return {"X-CSRFToken": CSRF}


_FACADE = "webui_app.api.llm_diagnostics_api"


# ── test-connection ──────────────────────────────────────────────────────────


def test_connection_ok_and_persists(client, tmp_path):
    with patch(f"{_FACADE}._guard_llm_endpoint", return_value=(None, None)), \
            patch(f"{_FACADE}._safe_get_json", return_value=(200, {"data": [{"id": "gpt-4"}]})):
        resp = client.post(
            "/api/v1/settings/llm/test-connection",
            json={"endpoint": "https://api.example.com/v1", "api_key": "sk-test", "model": "gpt-4"},
            headers=_headers(),
        )
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["models"] == ["gpt-4"]
    # best-effort persistence wrote last-known health
    stored = json.loads((tmp_path / "llm-settings.json").read_text("utf-8"))
    assert stored["last_test"]["ok"] is True


def test_connection_ssrf_rejected_is_400_failed(client):
    with patch(f"{_FACADE}._guard_llm_endpoint", return_value=("private_ip", "10.0.0.1")):
        resp = client.post(
            "/api/v1/settings/llm/test-connection",
            json={"endpoint": "https://api.example.com/v1", "api_key": "sk-test"},
            headers=_headers(),
        )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "failed"
    assert body["reason"] == "private_ip"


def test_connection_missing_creds_is_error(client):
    resp = client.post(
        "/api/v1/settings/llm/test-connection",
        json={"endpoint": "", "api_key": ""},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"


# ── test-generation ──────────────────────────────────────────────────────────


def test_generation_article_path_returns_body(client):
    # The article-gen path (use_article_gen=True) is the working preview path;
    # the anchor-candidates fallback constructs LLMAnchorRequest(domain=...), which
    # the dataclass rejects — a pre-existing legacy quirk faithfully preserved by
    # the move (it surfaces as status=error, exercised by the failure test below).
    provider = MagicMock()
    provider.generate_article_body.return_value = "生成的文章正文"
    settings = {
        "endpoint": "https://api.example.com/v1", "api_key": "sk", "model": "m",
        "temperature": 0.7, "system_prompt": "", "article_system_prompt": "",
        "use_article_gen": True,
    }
    with patch(f"{_FACADE}._load_llm_settings", return_value=settings), \
            patch("backlink_publisher.publishing.adapters.llm_anchor_provider.OpenAICompatibleProvider",
                  return_value=provider):
        resp = client.post(
            "/api/v1/settings/llm/test-generation",
            json={"test_title": "示例标题"},
            headers=_headers(),
        )
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["result"] == "生成的文章正文"


def test_generation_provider_failure_is_error(client):
    settings = {
        "endpoint": "https://api.example.com/v1", "api_key": "sk", "model": "m",
        "temperature": 0.7, "system_prompt": "", "article_system_prompt": "",
        "use_article_gen": False,
    }
    with patch(f"{_FACADE}._load_llm_settings", return_value=settings), \
            patch("backlink_publisher.publishing.adapters.llm_anchor_provider.OpenAICompatibleProvider",
                  side_effect=RuntimeError("boom")):
        resp = client.post(
            "/api/v1/settings/llm/test-generation",
            json={"test_title": "x"},
            headers=_headers(),
        )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"
