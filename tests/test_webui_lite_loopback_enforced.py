"""R6 — enforced LITE loopback security posture (plan 2026-06-04-001 Unit 9).

The internal LITE edition commits to a single enforced invariant: the resolved
bind host is *always* loopback. ``BACKLINK_PUBLISHER_ALLOW_NETWORK`` no longer
grants an off-loopback exception — a non-loopback ``BIND_HOST`` is refused at
startup regardless of every env combination. CSRF + the Origin/Referer guard on
every state-mutating route are the entire defense against a hostile loopback
peer, so the bind surface must never leave loopback.
"""
__tier__ = "unit"

import pytest

import webui
from webui_app.helpers.security import (
    _check_bind_origin_or_abort,
    _check_csrf_or_abort,
    _resolve_bind_host,
)

# Every host an operator might reach for to expose the app to a colleague.
_NON_LOOPBACK = ["0.0.0.0", "::", "192.168.1.10", "10.0.0.5", "0000:0000::0"]
_ALLOW_NETWORK_COMBOS = [None, "0", "1", "true", "yes"]


@pytest.fixture(autouse=True)
def _clean_bind_env(monkeypatch):
    monkeypatch.delenv("BIND_HOST", raising=False)
    monkeypatch.delenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", raising=False)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_hosts_resolve(host, monkeypatch):
    monkeypatch.setenv("BIND_HOST", host)
    assert _resolve_bind_host() == host


def test_default_is_loopback():
    assert _resolve_bind_host() in ("127.0.0.1", "::1", "localhost")


@pytest.mark.parametrize("host", _NON_LOOPBACK)
@pytest.mark.parametrize("allow", _ALLOW_NETWORK_COMBOS)
def test_non_loopback_always_refused(host, allow, monkeypatch):
    # The single committed behavior: NO combination of BIND_HOST / ALLOW_NETWORK
    # resolves to a non-loopback bind host — startup refuses.
    monkeypatch.setenv("BIND_HOST", host)
    if allow is not None:
        monkeypatch.setenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", allow)
    with pytest.raises(RuntimeError, match="loopback"):
        _resolve_bind_host()


def test_resolve_bind_host_is_the_one_webui_uses():
    # webui.py binds via this exact helper — no second bind path to escape.
    assert webui._resolve_bind_host is _resolve_bind_host


def test_csrf_and_bind_origin_guards_protect_future_post_routes():
    # The keep-alive action routes (start-recheck / start-republish, Units 5/7)
    # are not built yet, but they inherit two guards by construction:
    #  1. the app-level CSRF guard runs on EVERY matched POST/PUT/PATCH/DELETE;
    #  2. _check_bind_origin_or_abort is the documented per-route Origin guard.
    # Assert both mechanisms exist so a future state-mutating POST is covered by
    # default rather than depending on the new route remembering to opt in.
    from webui_app import create_app

    app = create_app()
    registered = {f.__name__ for f in app.before_request_funcs.get(None, [])}
    assert "_global_csrf_guard" in registered
    assert callable(_check_bind_origin_or_abort)
    assert callable(_check_csrf_or_abort)
