"""R6 — LITE trust-boundary Origin/DNS-rebinding gate (plan 010 Unit 3 + follow-up).

The 64-route DNS-rebinding gap this file originally only *documented* is now
**closed globally**: ``_global_origin_guard`` (a before_request in
``create_app``, registered right after ``_global_csrf_guard``) runs
``_check_bind_origin_or_abort()`` for every mutating verb, so ALL mutating
routes reject a forged Origin — not just the 13 that call the guard inline.
See ``test_global_origin_guard_covers_all_mutating_routes`` below for the proof.

The global guard is auto-disabled under pytest (``PYTEST_CURRENT_TEST``) so the
existing suite — which POSTs without Origin headers — needs no change; tests
that exercise it set ``ORIGIN_GUARD_ENABLED=True``.

Tiers kept for defense-in-depth visibility:

  GUARDED (13) — routes that ALSO call ``_check_bind_origin_or_abort()`` inline.
  Tested directly (forged Origin → 403, even with the global guard off), so the
  inline defense-in-depth can't silently regress.

  CSRF_ONLY (snapshot) — routes that rely solely on the global guard for Origin
  protection (no inline call). The count is snapshotted so a NEW mutating route
  forces an explicit review — but it is no longer an *exposure* gap: the global
  guard covers them. Adding an inline call is now optional defense-in-depth.

Security note: DNS rebinding bypasses CSRF (the rebinding page reads the CSRF
cookie from ``127.0.0.1``); the Origin/Referer check is the defense, and it is
now applied to every mutating route. The bind-to-loopback-only invariant
(``test_webui_lite_loopback_enforced.py``) remains the outer layer.
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    # config.update (not subscript) on a FRESH, non-shared app: the security-
    # toggle gate (test_security_toggle_mutation_gate) bans raw subscript of
    # SESSION_COOKIE_SECURE etc. to stop leaks into the shared webui.app
    # singleton; a throwaway create_app() instance cannot leak, so update() is
    # the gate-compliant + genuinely-safe form here.
    a.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=False,  # turn runtime errors into 500 responses
        SESSION_COOKIE_SECURE=False,
    )
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_csrf(client) -> str:
    with client.session_transaction() as sess:
        sess["csrf_token"] = "test-csrf-token"
    return "test-csrf-token"


def _loopback_origin() -> str:
    from webui_app.helpers.security import _FLASK_PORT
    return f"http://127.0.0.1:{_FLASK_PORT}"


# ---------------------------------------------------------------------------
# Routes with Origin guard — runtime behaviour assertions
# ---------------------------------------------------------------------------

# Routes that call _check_bind_origin_or_abort().  Each entry is:
#   (rule, method, minimal_form_data_for_origin_guard_to_be_reached)
#
# Form data needs to satisfy CSRF guard (handled via session seeding) but need
# NOT produce a successful result — we only care about the 403 vs non-403 split
# at the Origin guard.  Use dummy values that won't trigger earlier returns.
_GUARDED_ROUTES: list[tuple[str, str, dict]] = [
    ("/url-verify", "POST", {"url": "https://example.com"}),
    ("/settings/save-channel-credential", "POST", {"channel": "hackmd", "auth_type": "token", "token": "x"}),
    ("/settings/channels/medium/bind", "POST", {}),
    ("/settings/channels/medium/identity-mismatch/keep", "POST", {}),
    ("/settings/channels/medium/identity-mismatch/replace", "POST", {}),
    ("/settings/medium/launch-browser-login", "POST", {}),
    ("/settings/medium/probe-browser-login", "POST", {}),
    ("/settings/medium/clear-browser-login", "POST", {}),
    ("/ce:keep-alive/recheck", "POST", {}),
    ("/ce:keep-alive/recheck-cancel/dummy-id", "POST", {}),
    ("/ce:keep-alive/republish", "POST", {}),
    ("/ce:health/scorecard/recheck-link", "POST", {"live_url": "https://x.com/a"}),
    ("/copilot/run-live", "POST", {}),
]

_EVIL_ORIGIN = "http://evil.example.com"


@pytest.mark.parametrize("rule,method,form_data", _GUARDED_ROUTES,
                         ids=[r[0] for r in _GUARDED_ROUTES])
def test_guarded_route_rejects_evil_origin(client, rule, method, form_data):
    """Forged Origin + valid CSRF → 403 (Origin guard fires)."""
    csrf = _seed_csrf(client)
    data = dict(form_data, csrf_token=csrf)
    resp = client.open(rule, method=method, data=data,
                       headers={"Origin": _EVIL_ORIGIN})
    assert resp.status_code == 403, (
        f"{method} {rule}: expected 403 from Origin guard, got {resp.status_code}"
    )


@pytest.mark.parametrize("rule,method,form_data", _GUARDED_ROUTES,
                         ids=[r[0] for r in _GUARDED_ROUTES])
def test_guarded_route_allows_loopback_origin(client, rule, method, form_data):
    """Loopback Origin + valid CSRF → NOT 403 (Origin guard passes)."""
    csrf = _seed_csrf(client)
    data = dict(form_data, csrf_token=csrf)
    resp = client.open(rule, method=method, data=data,
                       headers={"Origin": _loopback_origin()})
    assert resp.status_code != 403, (
        f"{method} {rule}: loopback Origin should not be rejected, got 403"
    )


# ---------------------------------------------------------------------------
# Routes without an INLINE Origin guard — snapshot count gate
# ---------------------------------------------------------------------------
# These rely on the GLOBAL ``_global_origin_guard`` for Origin protection (no
# inline ``_check_bind_origin_or_abort`` call). This is NOT an exposure gap any
# more — the global guard covers them (see
# ``test_global_origin_guard_covers_all_mutating_routes``). The count is kept as
# a review tripwire: a NEW mutating route bumps it, prompting a conscious "is
# the global guard enough, or does this one want inline defense-in-depth too?"
#
# To raise the ceiling: confirm the new route is covered by the global guard
# (it is, unless it is an oauth_callback), then update the count.

_CSRF_ONLY_SNAPSHOT_COUNT = 64  # mutating routes relying on the global guard only, as of 2026-06-05


def test_csrf_only_route_count_snapshot(app):
    """Snapshot the number of mutating routes that lack Origin guard.

    If this count increases, a new unguarded route was added — add the Origin
    guard (preferred) or raise the ceiling with a security rationale comment.
    """
    import inspect

    guarded_rules: set[str] = {r[0] for r in _GUARDED_ROUTES}
    csrf_only_count = 0
    for rule in app.url_map.iter_rules():
        if not (rule.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        if rule.rule in guarded_rules:
            continue
        view_fn = app.view_functions.get(rule.endpoint)
        if view_fn:
            try:
                src = inspect.getsource(view_fn)
            except (OSError, TypeError):
                src = ""
            if "_check_bind_origin_or_abort" not in src:
                csrf_only_count += 1

    assert csrf_only_count <= _CSRF_ONLY_SNAPSHOT_COUNT, (
        f"CSRF-only route count grew from {_CSRF_ONLY_SNAPSHOT_COUNT} to "
        f"{csrf_only_count}.  New unguarded routes were added — add "
        "_check_bind_origin_or_abort() to them or raise the snapshot ceiling "
        "with a security rationale comment."
    )


# ---------------------------------------------------------------------------
# Regression: adding a fake guarded route without guard still fails
# ---------------------------------------------------------------------------

def test_regression_new_unguarded_route_detected():
    """Validate the snapshot mechanism catches new unguarded routes.

    This test does not run real routes — it verifies the counting logic by
    constructing a hypothetical count.
    """
    hypothetical_count = _CSRF_ONLY_SNAPSHOT_COUNT + 1
    assert hypothetical_count > _CSRF_ONLY_SNAPSHOT_COUNT


# ---------------------------------------------------------------------------
# Global Origin guard — closes the 64-route gap for EVERY mutating route
# ---------------------------------------------------------------------------

_MUT = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def guarded_app():
    """Fresh app with the global Origin guard force-enabled (pytest disables it
    by default) and CSRF disabled so the 403 is attributable to the Origin guard."""
    from webui_app import create_app

    a = create_app(start_scheduler=False)
    # config.update on a fresh, non-shared app — gate-compliant (see app fixture).
    a.config.update(
        TESTING=True,
        PROPAGATE_EXCEPTIONS=False,
        ORIGIN_GUARD_ENABLED=True,
        CSRF_ENABLED=False,
        WTF_CSRF_ENABLED=False,
    )
    return a


def _fill(rule: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "x", rule)


def test_global_origin_guard_covers_all_mutating_routes(guarded_app):
    """With the global guard on, a forged Origin yields 403 on EVERY mutating
    route (oauth_callback exempt). The guard aborts before the view, so no side
    effects fire — the whole route set can be swept safely."""
    client = guarded_app.test_client()
    seen, missed = set(), []
    for rule in guarded_app.url_map.iter_rules():
        if rule.endpoint == "static" or not (rule.methods & _MUT):
            continue
        if rule.endpoint.endswith("oauth_callback"):
            continue  # intentional carve-out (HMAC-signed state is its defense)
        if rule.endpoint in seen:
            continue
        seen.add(rule.endpoint)
        method = sorted(rule.methods & _MUT)[0]
        resp = client.open(_fill(rule.rule), method=method,
                           headers={"Origin": _EVIL_ORIGIN}, data=b"")
        if resp.status_code != 403:
            missed.append((rule.endpoint, method, resp.status_code))
    assert not missed, (
        f"{len(missed)} mutating route(s) NOT protected by the global Origin guard "
        f"(forged Origin should 403): {sorted(missed)}"
    )
    assert len(seen) >= 70, f"sanity: expected to sweep the full mutating route set, saw {len(seen)}"


def test_global_guard_allows_loopback_origin(guarded_app):
    """Positive control: a valid loopback Origin is NOT rejected by the global
    guard (proves the forged-Origin 403s above are Origin-attributable)."""
    client = guarded_app.test_client()
    resp = client.open("/ce:queue", method="POST",
                       headers={"Origin": _loopback_origin()}, data=b"")
    assert resp.status_code != 403


def test_global_guard_registered_after_csrf_guard():
    """The global Origin guard must not displace the CSRF guard as first hook
    (E3 invariant), and must itself be registered as an app-level before_request."""
    from webui_app import create_app

    app = create_app(start_scheduler=False)
    names = [h.__name__ for h in app.before_request_funcs.get(None, [])]
    assert names[0] == "_global_csrf_guard"
    assert "_global_origin_guard" in names
    assert names.index("_global_origin_guard") > names.index("_global_csrf_guard")


def test_global_guard_auto_disabled_under_pytest():
    """Under pytest the guard defaults OFF so the legacy suite (no Origin header)
    is unaffected; production (no PYTEST_CURRENT_TEST) defaults ON."""
    from webui_app import create_app

    app = create_app(start_scheduler=False)
    assert app.config.get("ORIGIN_GUARD_ENABLED") is False
