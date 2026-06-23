"""Security regression + contract for the ``/api/v1`` channel browser-bind flow.

Plan 2026-06-18-002 U7 (Settings). The stateful bind flow was ported HTML→JSON by
extracting a single-source facade (``BindAPI``); the legacy
``/settings/channels/<ch>/...`` routes are covered by ``test_webui_bind_routes.py``.
This suite guards the JSON path:

  * the identity_mismatch TOCTOU guard still 409s a fresh bind
  * keep restores bound / demotes to expired (NEVER destroys siblings) / no-ops
  * replace wipes artifacts and drops to unbound
  * loopback transport guards: forged Origin → 403, ALLOW_NETWORK=1 → 403
  * channel allow-list (anti-traversal) → 400

The fixtures mirror ``test_webui_bind_routes.py`` (CSRF-enabled app, fake bind
subprocess, channel_status_store reset) so behaviour parity is exercised identically.
"""

from __future__ import annotations

__tier__ = "integration"

import io
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CSRF = "test-csrf-token-fixture"


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path):
    fake_config_dir = tmp_path / "config"
    with patch("backlink_publisher.config._config_dir", return_value=fake_config_dir):
        yield fake_config_dir


@pytest.fixture(autouse=True)
def _reset_channel_status_store():
    from webui_store import channel_status_store
    channel_status_store.update(lambda _: {})
    yield
    channel_status_store.update(lambda _: {})


@pytest.fixture
def app():
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["csrf_token"] = CSRF
    return c


def _loopback_origin() -> str:
    from webui_app.helpers.security import _FLASK_PORT
    return f"http://127.0.0.1:{_FLASK_PORT}"


def _headers(*, origin: str | None = None):
    h = {"X-CSRFToken": CSRF}
    if origin is not None:
        h["Origin"] = origin
    else:
        h["Origin"] = _loopback_origin()
    return h


class _FakeProc:
    def __init__(self, lines, returncode=0):
        self.stdout = io.StringIO("".join(lines))
        self.stderr = io.StringIO("")
        self._returncode = returncode

    def wait(self, timeout=None):  # noqa: ARG002
        return self._returncode

    def kill(self):
        pass


@pytest.fixture
def fake_subprocess():
    from webui_app.services.bind_job import registry as r

    def _install(lines, returncode=0):
        r.reset_for_tests()
        r._popen = lambda *a, **kw: _FakeProc(lines, returncode=returncode)
        return r

    yield _install
    r.reset_for_tests()


def _seed_mismatch(channel="medium"):
    from backlink_publisher.config.loader import _config_dir
    from webui_store.channel_status import mark_bound, mark_identity_mismatch
    cfg = _config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    storage = cfg / f"{channel}-storage-state.json"
    storage.write_text('{"cookies": [], "origins": []}')
    (cfg / f"{channel}-last-account.txt").write_text("alice\n")
    mark_bound(channel, storage)
    mark_identity_mismatch(channel, old_account="alice", new_account="bob")


# ── start ────────────────────────────────────────────────────────────────────


def test_start_happy_path_returns_job_id(client, fake_subprocess):
    fake_subprocess([json.dumps({"event": "channel.bind.start", "channel": "medium"}) + "\n"])
    resp = client.post("/api/v1/settings/channels/medium/bind", headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert body["channel"] == "medium"
    assert body["status"] == "running"
    assert body["job_id"]


def test_start_forged_origin_is_403(client, fake_subprocess):
    fake_subprocess([])
    resp = client.post("/api/v1/settings/channels/medium/bind",
                       headers=_headers(origin="http://evil.example.com"))
    assert resp.status_code == 403


def test_start_refused_under_allow_network(client, fake_subprocess, monkeypatch):
    fake_subprocess([])
    monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", "1")
    resp = client.post("/api/v1/settings/channels/medium/bind", headers=_headers())
    assert resp.status_code == 403


def test_start_unknown_channel_is_400(client):
    resp = client.post("/api/v1/settings/channels/tiktok/bind", headers=_headers())
    assert resp.status_code == 400
    assert resp.headers["Content-Type"].startswith("application/problem+json")


def test_start_during_identity_mismatch_is_409(client, fake_subprocess):
    fake_subprocess([])
    _seed_mismatch("medium")
    resp = client.post("/api/v1/settings/channels/medium/bind", headers=_headers())
    assert resp.status_code == 409
    assert resp.headers["Content-Type"].startswith("application/problem+json")


# ── poll ───────────────────────────────────────────────────────────────────


def test_poll_unknown_job_is_404(client):
    resp = client.get("/api/v1/settings/channels/medium/bind/deadbeef")
    assert resp.status_code == 404


def test_poll_unknown_channel_is_400(client):
    resp = client.get("/api/v1/settings/channels/foobar/bind/anything")
    assert resp.status_code == 400


def test_poll_returns_snapshot(client, fake_subprocess):
    fake_subprocess([json.dumps({"event": "channel.bind.start", "channel": "medium"}) + "\n"])
    start = client.post("/api/v1/settings/channels/medium/bind", headers=_headers())
    job_id = start.get_json()["job_id"]
    resp = client.get(f"/api/v1/settings/channels/medium/bind/{job_id}")
    assert resp.status_code == 200
    assert resp.get_json()["channel"] == "medium"


def test_poll_channel_mismatch_is_404(client, fake_subprocess):
    fake_subprocess([json.dumps({"event": "channel.bind.start", "channel": "medium"}) + "\n"])
    start = client.post("/api/v1/settings/channels/medium/bind", headers=_headers())
    job_id = start.get_json()["job_id"]
    resp = client.get(f"/api/v1/settings/channels/velog/bind/{job_id}")
    assert resp.status_code == 404


# ── identity-mismatch keep ───────────────────────────────────────────────────


def test_keep_restores_bound(client):
    _seed_mismatch("medium")
    resp = client.post("/api/v1/settings/channels/medium/identity-mismatch/keep",
                       headers=_headers())
    assert resp.status_code == 200, resp.data[:300]
    assert resp.get_json()["resolved"] == "kept"
    from webui_store.channel_status import get_status
    assert get_status("medium")["status"] == "bound"


def test_keep_preserves_artifacts(client):
    _seed_mismatch("medium")
    from backlink_publisher.config.loader import _config_dir
    cfg = _config_dir()
    client.post("/api/v1/settings/channels/medium/identity-mismatch/keep", headers=_headers())
    assert (cfg / "medium-storage-state.json").exists()
    assert (cfg / "medium-last-account.txt").read_text().strip() == "alice"


def test_keep_missing_storage_demotes_to_expired_without_destroying_siblings(client):
    from backlink_publisher.config.loader import _config_dir
    from webui_store.channel_status import get_status, mark_bound, mark_identity_mismatch
    cfg = _config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    storage = cfg / "medium-storage-state.json"
    storage.write_text('{"cookies": []}')
    (cfg / "medium-last-account.txt").write_text("alice\n")
    mark_bound("medium", storage)
    mark_identity_mismatch("medium", old_account="alice", new_account="bob")
    storage.unlink()  # external wipe between mismatch + click

    resp = client.post("/api/v1/settings/channels/medium/identity-mismatch/keep", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["resolved"] == "expired"
    assert get_status("medium")["status"] == "expired"
    # Sibling must survive — the UI said "keep", not "replace".
    assert (cfg / "medium-last-account.txt").exists()


def test_keep_forged_origin_is_403(client):
    _seed_mismatch("medium")
    resp = client.post("/api/v1/settings/channels/medium/identity-mismatch/keep",
                       headers=_headers(origin="http://evil.example.com"))
    assert resp.status_code == 403
    # Guard fired before any state change.
    from webui_store.channel_status import get_status
    assert get_status("medium")["status"] == "identity_mismatch"


def test_keep_unknown_channel_is_400(client):
    resp = client.post("/api/v1/settings/channels/tiktok/identity-mismatch/keep", headers=_headers())
    assert resp.status_code == 400


# ── identity-mismatch replace ────────────────────────────────────────────────


def test_replace_wipes_artifacts_and_unbinds(client):
    _seed_mismatch("medium")
    from backlink_publisher.config.loader import _config_dir
    from webui_store.channel_status import get_status
    cfg = _config_dir()
    resp = client.post("/api/v1/settings/channels/medium/identity-mismatch/replace", headers=_headers())
    assert resp.status_code == 200
    assert resp.get_json()["resolved"] == "replaced"
    assert not (cfg / "medium-storage-state.json").exists()
    assert not (cfg / "medium-last-account.txt").exists()
    # Status record dropped (unbound).
    assert get_status("medium").get("status") in (None, "unbound")


def test_replace_forged_origin_is_403(client):
    _seed_mismatch("medium")
    from backlink_publisher.config.loader import _config_dir
    cfg = _config_dir()
    resp = client.post("/api/v1/settings/channels/medium/identity-mismatch/replace",
                       headers=_headers(origin="http://evil.example.com"))
    assert resp.status_code == 403
    # Guard fired before any deletion.
    assert (cfg / "medium-storage-state.json").exists()
