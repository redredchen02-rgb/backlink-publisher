"""Plan 2026-07-06-004 Unit 3 — ``POST /api/<channel>/verify`` gap-fills:

1. Syncs the live-verify verdict into ``webui_store.channel_status`` (in
   addition to the pre-existing ``verify_health`` write) — but only for
   channels in the ``CHANNELS`` whitelist (blogger/medium/velog). Every other
   channel (telegraph/ghpages/devto/...) must keep writing only to
   ``verify_health``, never attempting a ``channel_status`` write (which
   would raise ``UsageError`` for an unknown channel).
2. ``medium`` gets the real ``medium_liveness_check()`` probe instead of the
   generic ``verify_adapter_setup(..., mode='live')`` stub, mapped onto the
   same ``VerifyResult`` JSON shape every other channel returns.
"""

from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher.publishing._verify import VerifyResult
from webui_app import create_app
from webui_app.routes import settings_basic
from webui_store import channel_status, verify_health


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Per-test config dir → fresh channel_status/verify_health stores."""
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


def _patch_verify(monkeypatch, literal, ok=None):
    monkeypatch.setattr(
        settings_basic,
        "verify_adapter_setup",
        lambda *a, **k: VerifyResult(
            ok=(literal == "ok") if ok is None else ok,
            last_verify_result=literal,
        ),
    )


def _failed_channels() -> list[str]:
    return sorted(
        name for name, rec in channel_status.list_all().items()
        if (rec.get("status") or "") in ("expired", "identity_mismatch")
    )


# ── whitelisted channels (blogger/velog): channel_status_store must sync ───


class TestChannelStatusSyncWhitelisted:
    def test_ok_restores_expired_to_bound_and_clears_failed_list(
        self, client, monkeypatch, tmp_path
    ):
        state_path = tmp_path / "blogger-storage-state.json"
        state_path.write_text("{}", encoding="utf-8")
        channel_status.mark_bound("blogger", state_path)
        channel_status.mark_expired("blogger")
        assert "blogger" in _failed_channels()

        _patch_verify(monkeypatch, "ok")
        resp = client.post("/api/blogger/verify", headers=_csrf(client))

        assert resp.status_code == 200
        assert "blogger" not in _failed_channels()
        assert channel_status.get_status("blogger")["status"] == "bound"
        assert "blogger" not in verify_health.expired_channels()

    def test_ok_on_never_bound_channel_just_stamps_verified(self, client, monkeypatch):
        """Operator clicks 'Verify' on a channel that was never bound — must not
        crash; only last_verified_at is stamped, status stays 'unbound'."""
        _patch_verify(monkeypatch, "ok")
        resp = client.post("/api/velog/verify", headers=_csrf(client))
        assert resp.status_code == 200
        rec = channel_status.get_status("velog")
        assert rec["status"] == "unbound"
        assert rec["last_verified_at"] is not None

    def test_token_expired_marks_expired_and_verify_health(self, client, monkeypatch):
        _patch_verify(monkeypatch, "token_expired")
        resp = client.post("/api/velog/verify", headers=_csrf(client))
        assert resp.status_code == 200
        assert channel_status.get_status("velog")["status"] == "expired"
        assert "velog" in verify_health.expired_channels()

    def test_token_expired_does_not_overwrite_identity_mismatch(self, client, monkeypatch):
        channel_status.mark_identity_mismatch(
            "velog", old_account="alice", new_account="bob"
        )
        _patch_verify(monkeypatch, "token_expired")
        resp = client.post("/api/velog/verify", headers=_csrf(client))
        assert resp.status_code == 200
        # R6: identity_mismatch requires explicit operator resolution — a plain
        # token_expired verdict must never silently downgrade/overwrite it.
        assert channel_status.get_status("velog")["status"] == "identity_mismatch"

    def test_transient_verdict_does_not_change_channel_status(self, client, monkeypatch, tmp_path):
        state_path = tmp_path / "blogger-storage-state.json"
        state_path.write_text("{}", encoding="utf-8")
        channel_status.mark_bound("blogger", state_path)
        before = channel_status.get_status("blogger")

        _patch_verify(monkeypatch, "timeout")
        resp = client.post("/api/blogger/verify", headers=_csrf(client))
        assert resp.status_code == 200
        assert channel_status.get_status("blogger") == before


# ── non-whitelisted channels: channel_status_store must stay untouched ─────


class TestChannelStatusSkippedForNonWhitelisted:
    @pytest.mark.parametrize("channel", ["telegraph", "ghpages"])
    def test_ok_verify_never_writes_channel_status(self, client, monkeypatch, channel):
        _patch_verify(monkeypatch, "ok")
        resp = client.post(f"/api/{channel}/verify", headers=_csrf(client))
        assert resp.status_code == 200
        # No UsageError raised (would 500 without the whitelist guard), and
        # channel_status_store gains no row for a channel outside CHANNELS.
        assert channel_status.list_all() == {}

    def test_devto_unverifiable_live_is_honest_not_an_error(self, client, monkeypatch):
        """No live-verify support (e.g. devto) → the existing honest
        unverifiable_live-style response is preserved, never faked as a
        success/failure, and channel_status is left alone."""
        _patch_verify(monkeypatch, "unverifiable_live", ok=False)
        resp = client.post("/api/devto/verify", headers=_csrf(client))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["last_verify_result"] == "unverifiable_live"
        assert channel_status.list_all() == {}


# ── medium special case: real liveness probe, not the generic stub ─────────


class TestMediumLivenessVerify:
    def _patch_liveness(self, monkeypatch, outcome):
        import webui_app.services.medium_liveness_service as mls
        monkeypatch.setattr(mls, "medium_liveness_check", lambda *a, **k: outcome)

    def _patch_generic_stub_should_not_be_called(self, monkeypatch):
        calls: list[bool] = []
        monkeypatch.setattr(
            settings_basic,
            "verify_adapter_setup",
            lambda *a, **k: calls.append(True) or VerifyResult(ok=False),
        )
        return calls

    def test_logged_in_maps_to_ok_and_skips_generic_stub(self, client, monkeypatch):
        from backlink_publisher.publishing.adapters.medium_liveness import LivenessResult

        self._patch_liveness(monkeypatch, LivenessResult.LOGGED_IN)
        calls = self._patch_generic_stub_should_not_be_called(monkeypatch)

        resp = client.post("/api/medium/verify", headers=_csrf(client))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["last_verify_result"] == "ok"
        assert calls == []  # generic verify_adapter_setup stub never invoked
        assert channel_status.get_status("medium")["last_verified_at"] is not None

    def test_cached_bound_maps_to_ok(self, client, monkeypatch):
        from backlink_publisher.publishing.adapters.medium_liveness import LivenessResult

        self._patch_liveness(monkeypatch, LivenessResult.CACHED_BOUND)
        resp = client.post("/api/medium/verify", headers=_csrf(client))
        body = resp.get_json()
        assert body["ok"] is True
        assert body["last_verify_result"] == "ok"

    def test_expired_maps_to_token_expired_and_syncs_channel_status(self, client, monkeypatch):
        from backlink_publisher.publishing.adapters.medium_liveness import LivenessResult

        self._patch_liveness(monkeypatch, LivenessResult.EXPIRED)
        resp = client.post("/api/medium/verify", headers=_csrf(client))
        body = resp.get_json()
        assert body["ok"] is False
        assert body["last_verify_result"] == "token_expired"
        assert channel_status.get_status("medium")["status"] == "expired"
        assert "medium" in verify_health.expired_channels()

    def test_never_bound_maps_to_never(self, client, monkeypatch):
        from backlink_publisher.publishing.adapters.medium_liveness import LivenessResult

        self._patch_liveness(monkeypatch, LivenessResult.NEVER_BOUND)
        resp = client.post("/api/medium/verify", headers=_csrf(client))
        body = resp.get_json()
        assert body["ok"] is False
        assert body["last_verify_result"] == "never"
        assert body["blockers"]

    def test_needs_recheck_maps_to_timeout_and_no_store_mutation(self, client, monkeypatch):
        from backlink_publisher.publishing.adapters.medium_liveness import LivenessResult

        self._patch_liveness(monkeypatch, LivenessResult.NEEDS_RECHECK)
        resp = client.post("/api/medium/verify", headers=_csrf(client))
        body = resp.get_json()
        assert body["ok"] is False
        assert body["last_verify_result"] == "timeout"
        assert channel_status.list_all() == {}
        assert "medium" not in verify_health.expired_channels()
