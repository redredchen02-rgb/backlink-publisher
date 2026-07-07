"""Tests for the Plan 2026-07-07-002 production WSGI entrypoint (serve.py).

serve.py replaces the Werkzeug dev server (webui.py's ``app.run()``) with
waitress for real launches, while reusing the exact same Flask ``app``
instance. These tests cover import-time safety, the two small resolver
helpers (``_resolve_threads``, ``_force_production_debug_off``,
``_warn_if_multithreaded``), and the plan's core safety claim: that
``threads=1`` preserves the dev server's de facto request serialization,
so the documented drafts.py bulk-publish-now single-flight gap
(``webui_app/routes/drafts.py`` -- the legacy, unlocked route; see
``webui_app/api/v1/drafts.py:39-52`` for the sibling ``/api/v1`` route's
own lock, which already exists and is not the gap) stays latent.
"""
from __future__ import annotations

__tier__ = "unit"

import socket
import threading
import time

from flask import Flask
import pytest
import requests
import waitress

import serve
import webui


def test_serve_app_is_webui_app():
    assert serve.app is webui.app


def test_resolve_threads_defaults_to_one(monkeypatch):
    monkeypatch.delenv("WSGI_THREADS", raising=False)
    assert serve._resolve_threads() == 1


def test_resolve_threads_honors_override(monkeypatch):
    monkeypatch.setenv("WSGI_THREADS", "4")
    assert serve._resolve_threads() == 4


def test_resolve_threads_rejects_zero(monkeypatch):
    # waitress's own dispatcher never starts a worker when threads<=0, so
    # every request would hang forever -- worse than the race this default
    # guards against. Fail loudly at startup instead of hanging silently.
    monkeypatch.setenv("WSGI_THREADS", "0")
    with pytest.raises(ValueError, match="positive integer"):
        serve._resolve_threads()


def test_resolve_threads_rejects_negative(monkeypatch):
    monkeypatch.setenv("WSGI_THREADS", "-1")
    with pytest.raises(ValueError, match="positive integer"):
        serve._resolve_threads()


def test_resolve_threads_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv("WSGI_THREADS", "many")
    with pytest.raises(ValueError, match="positive integer"):
        serve._resolve_threads()


def test_force_production_debug_off_disables_debug_regardless_of_flag():
    app = Flask(__name__)
    app.debug = True
    serve._force_production_debug_off(app)
    assert app.debug is False


def test_warn_if_multithreaded_silent_at_one_thread(capsys):
    result = serve._warn_if_multithreaded(1)
    assert result is None
    assert capsys.readouterr().out == ""


def test_warn_if_multithreaded_names_the_drafts_gap(capsys):
    result = serve._warn_if_multithreaded(4)
    assert result is not None
    # Assert the exact unlocked route's path, not just the substrings
    # "drafts.py"/"bulk-publish-now" -- both webui_app/routes/drafts.py
    # (unlocked) and webui_app/api/v1/drafts.py (already locked) satisfy
    # those substrings, so a weaker assertion wouldn't catch a citation of
    # the wrong file.
    assert "webui_app/routes/drafts.py" in result
    assert "webui_app/routes/drafts.py" in capsys.readouterr().out


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"nothing listening on {host}:{port} after {timeout}s")


@pytest.fixture
def _real_sockets():
    """Re-enable real sockets for one test that needs a live loopback server.

    conftest's autouse ``_disable_real_network`` calls ``disable_socket()``
    before every test (CI safety net against missed mocks hitting the real
    network). This fixture runs after it and re-enables sockets so a real
    waitress server can ``accept()`` a loopback connection -- mirrors the
    established pattern in ``tests/e2e/publish_journey.py`` for the same
    need, scoped to only the one test that requests this fixture rather than
    the whole file.
    """
    try:
        from pytest_socket import enable_socket
    except ImportError:
        yield
        return
    enable_socket()
    yield


def test_threads_one_serializes_concurrent_requests(_real_sockets):
    """Empirically verify the plan's core safety claim.

    This does not spin up the full application (its scheduler, lazy stores,
    and CSRF machinery are irrelevant to the question being tested) --
    it verifies the underlying mechanism the plan's Key Technical Decisions
    section relies on: that ``waitress.serve(..., threads=1)`` serializes
    concurrent requests the same way webui.py's unthreaded ``app.run()``
    already does today, so the drafts.py bulk-publish-now single-flight
    gap does not become a live race under this entrypoint's default.
    """
    active = {"count": 0, "max": 0}
    lock = threading.Lock()
    stub_app = Flask("concurrency-probe")

    @stub_app.route("/slow")
    def slow():
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.3)
        with lock:
            active["count"] -= 1
        return "ok"

    port = _free_port()
    server_thread = threading.Thread(
        target=waitress.serve,
        args=(stub_app,),
        kwargs={"host": "127.0.0.1", "port": port, "threads": 1},
        daemon=True,
    )
    server_thread.start()
    _wait_for_port("127.0.0.1", port)

    responses = []

    def _hit():
        responses.append(
            requests.get(f"http://127.0.0.1:{port}/slow", timeout=5)
        )

    t1 = threading.Thread(target=_hit)
    t2 = threading.Thread(target=_hit)
    t1.start()
    time.sleep(0.05)  # give the first request a head start into the handler
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(responses) == 2
    assert all(r.status_code == 200 for r in responses)
    assert active["max"] == 1, (
        "waitress with threads=1 let two requests run concurrently -- this "
        "would reopen the drafts.py bulk-publish-now double-schedule race"
    )
