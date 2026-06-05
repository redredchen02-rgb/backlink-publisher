"""Plan 2026-06-05-008 Unit 2 — /api/<channel>/verify persists its credential
verdict into the verify_health store so expiry survives a reload.
"""

from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher.publishing._verify import VerifyResult
from webui_app import create_app
from webui_app.routes import settings_basic
from webui_store import verify_health


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Per-test config dir → fresh verify_health store (no cross-test leak)."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store import _refresh_paths
    _refresh_paths()


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _csrf(client):
    with client.session_transaction() as sess:
        sess["csrf_token"] = "t"
    return {"X-CSRFToken": "t"}


def _patch_verify(monkeypatch, literal):
    monkeypatch.setattr(
        settings_basic,
        "verify_adapter_setup",
        lambda *a, **k: VerifyResult(ok=(literal == "ok"), last_verify_result=literal),
    )


class TestVerifyHealthPersistence:
    def test_token_expired_is_persisted(self, client, monkeypatch):
        _patch_verify(monkeypatch, "token_expired")
        resp = client.post("/api/devto/verify", headers=_csrf(client))
        assert resp.status_code == 200
        assert resp.get_json()["last_verify_result"] == "token_expired"
        assert "devto" in verify_health.expired_channels()

    def test_ok_clears_prior_expiry(self, client, monkeypatch):
        verify_health.record("devto", "token_expired")
        assert "devto" in verify_health.expired_channels()
        _patch_verify(monkeypatch, "ok")
        resp = client.post("/api/devto/verify", headers=_csrf(client))
        assert resp.status_code == 200
        assert "devto" not in verify_health.expired_channels()

    def test_transient_does_not_change_state(self, client, monkeypatch):
        verify_health.record("devto", "token_expired")
        _patch_verify(monkeypatch, "timeout")
        client.post("/api/devto/verify", headers=_csrf(client))
        assert "devto" in verify_health.expired_channels()  # unchanged

    def test_store_failure_does_not_break_verify(self, client, monkeypatch):
        _patch_verify(monkeypatch, "token_expired")
        monkeypatch.setattr(
            verify_health, "record",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        resp = client.post("/api/devto/verify", headers=_csrf(client))
        assert resp.status_code == 200
        assert resp.get_json()["last_verify_result"] == "token_expired"
