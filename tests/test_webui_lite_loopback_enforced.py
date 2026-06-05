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
from webui_app.helpers.security import _resolve_bind_host

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


def test_csrf_guard_runs_first_before_lite_gate():
    # The app-level CSRF guard must be the FIRST before_request hook so every
    # matched state-mutating POST is token-checked (E3 invariant — see
    # tests/test_webui_csrf_ordering.py). The LITE surface gate is registered
    # AFTER it: a 404-only denial is order-independent for security, and putting
    # it first would displace the CSRF guard (the bug this branch's review found).
    #
    # The app-level _global_origin_guard (R6 follow-up, registered after the CSRF
    # guard) now covers every mutating verb — see test_webui_lite_origin_guard_coverage.py
    # for full-coverage assertions including hook-ordering and per-route 403 probes.
    from webui_app import create_app

    app = create_app()
    hooks = [f.__name__ for f in app.before_request_funcs.get(None, [])]
    assert hooks[0] == "_global_csrf_guard"
    assert "_lite_surface_gate" in hooks
    assert hooks.index("_global_csrf_guard") < hooks.index("_lite_surface_gate")
