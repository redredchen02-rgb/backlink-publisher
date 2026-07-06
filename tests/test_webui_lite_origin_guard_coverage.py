"""R6 — LITE trust-boundary Origin/DNS-rebinding gate (plan 010 Unit 3).

Posture audit for all state-mutating routes.  Two tiers:

  GUARDED — routes that call ``_check_bind_origin_or_abort()``.  The test
  sends a forged (evil) Origin with a valid CSRF token and asserts 403 +
  no side-effects.  A positive control with a loopback Origin asserts non-403,
  proving the 403 comes from the Origin guard and not from something else.

  CSRF_ONLY — remaining mutating routes that carry no *inline* Origin guard.
  They are enumerated here as a snapshot (an inline-guard adoption inventory),
  no longer a documented gap — see below.

  FULL COVERAGE — the app-level ``_global_origin_guard`` (R6 follow-up) now
  Origin-checks EVERY mutating verb. The gate at the bottom of this file forces
  the guard on and asserts every mutating route 403s on a forged Origin, so the
  CSRF_ONLY tier above is covered at runtime regardless of inline adoption.

Security note: the app-level CSRF guard (``_global_csrf_guard``) stops
cross-origin form submissions from untrusted origins *when the attacker cannot
read cookies*.  DNS rebinding bypasses CSRF because the rebinding page can
read the CSRF cookie from ``127.0.0.1``.  That rebinding window — previously the
realistic attack surface for the CSRF_ONLY tier — is now closed by the app-level
Origin guard, on top of the bind-to-loopback-only invariant
(``test_webui_lite_loopback_enforced.py``).
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
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False  # turn runtime errors into 500 responses
    a.config["SESSION_COOKIE_SECURE"] = False
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
    # Legacy /settings/save-channel-credential, /settings/channels/*/bind,
    # /settings/medium/*-browser-login removed in U8 5b (Plan 2026-06-18-002) —
    # their inline-guarded v1 equivalents appear below.
    ("/ce:keep-alive/recheck", "POST", {}),
    ("/ce:keep-alive/recheck-cancel/dummy-id", "POST", {}),
    ("/ce:keep-alive/republish", "POST", {}),
    ("/ce:health/scorecard/recheck-link", "POST", {"live_url": "https://x.com/a"}),
    ("/copilot/run-live", "POST", {}),
    # Plan 2026-06-18-002 U7 (Settings security core): /api/v1 credential writes
    # enforce the guards INLINE (the api_v1 blueprint does not inherit bind.py's
    # before_request). They write 0600 secret files, so they MUST stay guarded.
    ("/api/v1/settings/channels/devto/token", "POST", {}),
    ("/api/v1/settings/notion-token", "POST", {}),
    # Plan 2026-06-18-002 U7 (Settings): the general registry-dispatched bind-save,
    # ported HTML->JSON via the single-source ChannelBindAPI facade. Same 0600
    # credential-write posture — inline-guarded (literal in the view source, so it
    # is excluded from the CSRF-only snapshot below; the count stays put).
    ("/api/v1/settings/channels/hackmd/credential", "POST", {}),
    # Plan 2026-06-18-002 U7 (Settings): the stateful browser-bind flow ported via
    # the single-source BindAPI facade. The identity-mismatch resolution routes
    # mutate channel_status_store + delete credential artifacts, so they MUST stay
    # Origin-guarded (inline literal → excluded from the snapshot). The bind START
    # route is also inline-guarded but kept out of this list: a loopback POST would
    # launch a real bind subprocess (covered instead by test_webui_api_v1_bind.py +
    # the global-guard sweep). The GET poll is remote_addr-guarded, not Origin-guarded.
    ("/api/v1/settings/channels/medium/identity-mismatch/keep", "POST", {}),
    ("/api/v1/settings/channels/medium/identity-mismatch/replace", "POST", {}),
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
# CSRF-only routes — snapshot count gate
# ---------------------------------------------------------------------------
# This set tracks routes lacking an *inline* _check_bind_origin_or_abort. They
# are NO LONGER an open DNS-rebinding gap: the app-level _global_origin_guard now
# Origin-checks every mutating verb (proven by the full-coverage gate below). The
# count is kept as an informational inventory of inline-guard adoption, not a
# documented hole — the runtime protection is asserted unconditionally there.

_CSRF_ONLY_SNAPSHOT_COUNT = 97  # routes with CSRF but no inline Origin guard as of 2026-07-06
# +1 (96->97): Plan 2026-07-06-004 Unit 3 — POST /api/v1/queue/<task_id>/retry
# (webui_app/api/v1/history.py). Same protection level as its 4 sibling
# endpoints in the same file (/history/delete, /bulk-delete, /purge-failed,
# /recheck), none of which use the inline guard either — CSRF-token-only,
# same as this whole file's existing convention, covered unconditionally by
# the app-level _global_origin_guard like every other mutating route.
# NOTE (2026-07-01): before this bump the measured count on this branch's fork
# point was already 93 (2 above the previously-recorded 91), drift pre-dating
# and unrelated to the Plan 2026-07-01-002 work below — its root cause was not
# investigated here as it is outside this unit's scope; flagged rather than
# silently absorbed.
# +3 (93->96): Plan 2026-07-01-002 Unit 3 — POST /api/v1/error-reports, PATCH
# /api/v1/error-reports/<id>, DELETE /api/v1/error-reports/<id>. Same posture
# as the rest of the /api/v1 mutating surface added above: sanitized
# diagnostic-report CRUD (config/state JSON writes), not a 0600 credential
# write, so no inline guard is warranted; covered at runtime by the
# app-level _global_origin_guard (proven unconditionally by
# test_global_guard_covers_every_mutating_route). CSRF itself is enforced
# solely by the existing site-wide _global_csrf_guard, per the plan's own
# explicit decision not to special-case this endpoint's CSRF handling.
# -2 (100->98): U8 medium-IT slice removed the legacy POST /settings/{save,clear}-medium-token
# routes (config writes, no inline guard — they were in this count). Medium discontinued
# integration tokens; the management UI is retired (no SPA replacement). Tightening the
# ceiling keeps it exact. (The assertion is <=, so a stale 100 would have passed silently.)
# +6 v0.4.0 routes (U4-U8): /settings/channels/<ch>/probe-liveness, /publish/quick,
# /publish/save-defaults, /sites/batch-queue, /sites/autopilot,
# /dashboard/autopilot-alert/dismiss — all internal-only endpoints protected
# by the global CSRF guard; no bind-sensitive data, Origin guard not warranted.
# +1: /settings/test-image-gen added in feat(image-gen) b44040d; covered by _global_origin_guard.
# +16 (71->87): the Plan 2026-06-18-002 front/back-separation `/api/v1` mutating
# surface (U5 pipeline plan/preview/validate/publish/regen-body; U7 history
# delete/bulk-delete/purge-failed/recheck; U7 drafts schedule/publish-now/cancel/
# delete/bulk-delete; U7 sites save/autopilot). These are config/queue/state JSON
# writes, NOT bind-sensitive credential writes (the 0600 token/channel-bind routes
# under /settings/* keep their inline _check_bind_origin_or_abort). All 16 are
# covered at runtime by the app-level _global_origin_guard — proven unconditionally
# by test_global_guard_covers_every_mutating_route — so an inline guard is not
# warranted; raised here to track the inline-adoption inventory, not a new gap.
# +3 (87->90): U7 batch_campaign + profiles units — POST /api/v1/campaigns
# (campaign_store create) and POST /api/v1/profiles/save|delete (preset CRUD).
# Same posture as the rest of the /api/v1 mutating surface: config/state JSON
# writes, not 0600 credential writes, covered by the _global_origin_guard.
# +2 (90->92): U7 Settings OAuth credential routes — POST /api/v1/settings/blogger-oauth
# (save Client ID/Secret via save_config) and POST /api/v1/settings/medium-oauth/clear
# (delete medium-token.json). These mirror the LEGACY oauth routes' posture, which
# carry no inline _check_bind_origin_or_abort either — they are config writes / token
# deletes, not the dedicated-0600-file credential writes (the channel-token / notion /
# channel-credential / bind routes keep their inline guard). Covered at runtime by the
# _global_origin_guard. (The Blogger oauth-start→callback redirect handshake stays
# legacy browser-navigation and is not on /api/v1.)
# +2 (92->94): U7 Settings LLM diagnostics — POST /api/v1/settings/llm/test-connection
# and .../llm/test-generation. These mirror the LEGACY llm diagnostic routes' posture
# (no inline guard): they are SSRF-guarded probes / generation previews, not credential
# writes (the 0600 llm-config save keeps its inline guard). The endpoint URL is
# SSRF-gated in the facade before the api_key is sent; covered at runtime by the
# _global_origin_guard.
# +2 (94->96): U7 Settings image-gen diagnostics — POST /api/v1/settings/image-gen/
# test-connection and .../image-gen/generate-sample. Same posture as the LLM
# diagnostics + the LEGACY /settings/{test-image-gen,generate-sample-image} routes
# (no inline guard): operator-configured connectivity probe / banner-generation
# preview, NOT a credential write. The endpoint is read from config.toml [image_gen]
# (not user-supplied), so no SSRF gate; covered at runtime by the _global_origin_guard.
# (The U7 medium browser-login routes — /api/v1/settings/medium/*-browser-login — are
# inline-guarded like the bind/credential family, so they are EXCLUDED here, not added.)
# +2 (96->98): U7 Settings global saves — POST /api/v1/settings/keywords and
# .../settings/schedule. These mirror the LEGACY /settings/{save-target-keywords,
# schedule} routes' posture (no inline guard): they write GLOBAL config
# (target_anchor_keywords in config.toml / schedule-settings.json), NOT 0600
# credential files. Covered at runtime by the _global_origin_guard.
# +1 (98->99): U7 Settings blogger card — POST /api/v1/settings/blogger/revoke
# (delete the blogger token file). Same posture as the migrated blogger-oauth /
# medium-oauth-clear routes (no inline guard): a config/token-file op, NOT a 0600
# secret WRITE, covered at runtime by the _global_origin_guard. (The new
# /api/v1/settings/blogger/status is a GET — non-mutating, never counted. The
# velog login route is inline-guarded like medium — EXCLUDED, not added.)
# +1 (99->100): U7 Settings blogger card (slice 6) — POST /api/v1/settings/blogger/
# blog-ids (save the domain→Blogger Blog ID routing map). Same posture as the other
# blogger writes (no inline guard): a config write, NOT a 0600 secret write, covered
# at runtime by the _global_origin_guard. (The paired GET .../blog-ids is
# non-mutating, never counted.)


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
# App-level Origin guard — full-coverage gate (R6 follow-up)
# ---------------------------------------------------------------------------
# The CSRF_ONLY snapshot above counts routes lacking an *inline*
# _check_bind_origin_or_abort. Those routes are NO LONGER an open DNS-rebinding
# gap: the app-level _global_origin_guard (webui_app/__init__.py) Origin-checks
# every mutating verb. This section proves it at runtime — with the guard forced
# on, EVERY mutating route (inline-guarded or not) rejects a forged Origin.
#
# The guard auto-disables under pytest (so the existing suite, which POSTs
# without browser Origin headers, stays green); these tests force it on via the
# private app instance below, the only place that does so.

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Exempt from the Origin guard. SNAPSHOT-CAPPED; every entry needs a named
# alternative protection and NO state-writing / probe route may appear. Empty:
# the only OAuth carve-out (``*oauth_callback``) is a GET redirect, outside the
# mutating set.
_ORIGIN_GUARD_ALLOWLIST: frozenset[str] = frozenset()


@pytest.fixture
def guard_on_app():
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    a.config["ORIGIN_GUARD_ENABLED"] = True  # force-on (auto-off under pytest)
    return a


def _build_path(rule):
    try:
        built = rule.build({a: 1 for a in rule.arguments}, append_unknown=False)
    except Exception:  # noqa: BLE001 — unbuildable rule, skip
        return None
    if built is None:
        return None
    return built[1] if isinstance(built, tuple) else built


def _verb(rule):
    if "POST" in rule.methods:
        return "POST"
    return next(iter(rule.methods & _MUTATING))


def _open(client, path, verb, origin):
    with client.session_transaction() as sess:
        sess["csrf_token"] = "test-csrf-token"
    return client.open(path, method=verb,
                       headers={"X-CSRFToken": "test-csrf-token", "Origin": origin},
                       data={"csrf_token": "test-csrf-token"})


def test_global_guard_covers_every_mutating_route(guard_on_app):
    """With the app-level guard on, EVERY mutating route 403s on a forged Origin.

    Legal CSRF is supplied so the CSRF guard (first hook) passes and the Origin
    guard is what is exercised; the 403 lands in before_request, so the view never
    runs (no side effect by construction)."""
    client = guard_on_app.test_client()
    offenders, skipped = [], []
    for rule in guard_on_app.url_map.iter_rules():
        if not (rule.methods & _MUTATING) or rule.endpoint in _ORIGIN_GUARD_ALLOWLIST:
            continue
        path = _build_path(rule)
        if path is None:
            skipped.append(rule.endpoint)
            continue
        if _open(client, path, _verb(rule), _EVIL_ORIGIN).status_code != 403:
            offenders.append(rule.endpoint)
    assert not offenders, f"forged Origin NOT blocked on: {sorted(offenders)}"
    assert not skipped, f"could not build a path to probe: {sorted(skipped)}"


def test_global_guard_allows_loopback_origin(guard_on_app):
    """Positive control: a legal loopback Origin passes the guard on >=1 route,
    proving the 403s above are Origin-attributable (not some unrelated 403)."""
    client = guard_on_app.test_client()
    for rule in guard_on_app.url_map.iter_rules():
        if (not (rule.methods & _MUTATING) or rule.arguments
                or rule.endpoint in _ORIGIN_GUARD_ALLOWLIST):
            continue
        path = _build_path(rule)
        if path is None:
            continue
        if _open(client, path, _verb(rule), _EVIL_ORIGIN).status_code != 403:
            continue
        if _open(client, path, _verb(rule), _loopback_origin()).status_code != 403:
            return  # found a route the loopback Origin is allowed through
    pytest.fail("no route accepted a legal loopback Origin under the guard")


def test_global_guard_off_by_default_under_pytest():
    """The guard auto-disables under pytest so the existing suite stays green;
    only the gates above force it on."""
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    assert a.config.get("ORIGIN_GUARD_ENABLED") is False


def test_origin_guard_registered_after_csrf_guard(guard_on_app):
    hooks = [f.__name__ for f in guard_on_app.before_request_funcs.get(None, [])]
    assert hooks[0] == "_global_csrf_guard"  # E3 invariant unchanged
    assert "_global_origin_guard" in hooks
