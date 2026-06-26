"""Contract for the ``/api/v1`` image-gen (AI cover) diagnostics routes.

Plan 2026-06-18-002 U7 (Settings). The connectivity probe + sample generation
were ported HTML→JSON via the single-source ``ImageGenDiagnosticsAPI`` facade; the
legacy ``/settings/{test-image-gen,generate-sample-image}`` routes + the provider
probes are covered by ``test_webui_image_gen.py``. This suite guards the JSON path:
the diagnostic envelope (``{"ok": bool, ...}``) is returned as-is (NOT problem+json,
always HTTP 200), the provider dispatch reaches the right endpoint, and a real
generation surfaces a base64 data-URL.

Mock note: the probes call the shared ``http_client`` singleton — patched here on
the facade module (``webui_app.api.image_gen_diagnostics_api.http_client.get``),
where the logic moved. ``ImageGenAdapter`` is patched at its source module.
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSRF = "test-csrf-token"

_FACADE = "webui_app.api.image_gen_diagnostics_api"


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


def _seed_openai_config(config_dir):
    (config_dir / "config.toml").write_text(
        '[image_gen]\n'
        'base_url = "https://gateway.example.com/v1"\n'
        'model = "banner-m"\n'
        'banner_size = "1200x630"\n'
    )


def _seed_frw_config(config_dir):
    (config_dir / "config.toml").write_text(
        '[image_gen]\n'
        'provider = "frw"\n'
        'base_url = "https://frw-dreamaiai-api.aiaiartist.com"\n'
        'frw_template_id = "tpl_txt2img_test"\n'
        'model = "sdxl"\n'
        'banner_size = "1200x630"\n'
    )


def _seed_token():
    from backlink_publisher._util.secrets import write_frw_token
    write_frw_token("sk_webui_test")


# ── test-connection ──────────────────────────────────────────────────────────


def test_connection_no_section_is_ok_false(client):
    """No [image_gen] section → 200 + ok=False, no crash."""
    resp = client.post("/api/v1/settings/image-gen/test-connection", headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["ok"] is False
    assert "no_image_gen_section" in body["error"]


def test_connection_openai_success(client, tmp_path):
    """OpenAI provider: 200 from /models → ok with model_count."""
    _seed_openai_config(tmp_path)
    _seed_token()
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"data": [{"id": "m1"}, {"id": "m2"}]}
    fake.text = "ok"
    with patch(f"{_FACADE}.http_client.get", return_value=fake):
        resp = client.post("/api/v1/settings/image-gen/test-connection", headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["model_count"] == 2
    assert body["configured_model"] == "banner-m"


def test_connection_frw_success_uses_balance_endpoint(client, tmp_path):
    """FRW provider: 200 from /balance → ok with credits, X-Api-Key auth."""
    _seed_frw_config(tmp_path)
    _seed_token()
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"success": True, "data": {"creditsRemaining": 867.5}}
    fake.text = "ok"
    with patch(f"{_FACADE}.http_client.get", return_value=fake) as mock_get:
        resp = client.post("/api/v1/settings/image-gen/test-connection", headers=_headers())
    body = resp.get_json()
    assert body["ok"] is True
    assert body["frw_credits_remaining"] == 867.5
    call_args = mock_get.call_args
    assert "/api/frwapi/v1/balance" in call_args[0][0]
    assert call_args[1]["headers"].get("X-Api-Key") == "sk_webui_test"


# ── generate-sample ──────────────────────────────────────────────────────────


def test_generate_sample_no_section_is_ok_false(client):
    """No [image_gen] section → 200 + ok=False (no generation attempted)."""
    resp = client.post("/api/v1/settings/image-gen/generate-sample",
                       json={}, headers=_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "no_image_gen_section" in body["error"]


def test_generate_sample_success_returns_data_url(client, tmp_path):
    """Configured + token → real adapter call → base64 data-URL, prompt echoed."""
    _seed_openai_config(tmp_path)
    _seed_token()
    artifact = MagicMock()
    artifact.data = b"\x89PNG_fake_bytes"
    artifact.mime = "image/png"
    artifact.source_url = "https://cdn.example.com/banner.png"
    adapter = MagicMock()
    adapter.generate.return_value = artifact
    with patch("backlink_publisher.publishing.adapters.image_gen.ImageGenAdapter",
               return_value=adapter):
        resp = client.post("/api/v1/settings/image-gen/generate-sample",
                           json={"prompt": "自定义提示词"}, headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data_url"].startswith("data:image/png;base64,")
    assert body["mime"] == "image/png"
    assert body["prompt"] == "自定义提示词"
    assert body["source_url"] == "https://cdn.example.com/banner.png"
    # the custom prompt reached the adapter
    assert adapter.generate.call_args[0][0] == "自定义提示词"
