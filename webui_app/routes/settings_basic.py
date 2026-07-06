"""/settings/save-* (non-OAuth) + generic /api/<channel>/* channel binding API.

Plan 2026-05-19-006 Unit 4 — generic /api/<channel>/{status,verify,dry-run} routes.
The legacy ``/settings`` GET (Jinja settings page) was retired in U8 (Plan
2026-06-18-002); the SPA settings page at /app/settings replaces it.
``/settings`` now redirects to ``/app/settings`` (Plan 2026-06-24-001).
"""

from __future__ import annotations

from typing import Any

from flask import abort, Blueprint, jsonify, redirect, request, url_for

from backlink_publisher.config import load_config
from backlink_publisher.publishing.adapters import verify_adapter_setup
from backlink_publisher.publishing.registry import registered_platforms

from ..api.global_settings_api import GlobalSettingsAPI
from ..binding_status import get_channel_status
from ..helpers._request_cache import _g_cache
from ..helpers.security import _safe_flash_redirect

bp = Blueprint("settings_basic", __name__)


@bp.get("/settings")
def settings_redirect() -> Any:
    """Redirect legacy /settings → SPA /app/settings (Plan 2026-06-24-001)."""
    return redirect(url_for("spa.spa", subpath="settings"), 302)


# ── Generic channel binding API (Plan 2026-05-19-006 Unit 4) ─────────────────


def _verify_result_to_json(result: Any) -> dict:
    """Serialize VerifyResult dataclass → plain dict for JSON response."""
    return {
        "ok": result.ok,
        "identity": result.identity,
        "last_verified_at": result.last_verified_at,
        "last_verify_result": result.last_verify_result,
        "blockers": list(result.blockers),
        "dofollow": result.dofollow,
    }


def _require_known_channel(channel: str) -> None:
    """404 for any platform not in the dynamic registry. Drift between this
    route and dashboard cards is enforced by ``tests/test_dashboard_drift``.
    """
    if channel not in registered_platforms():
        abort(404)


@bp.route('/api/<channel>/status', methods=['GET'])
def api_channel_status(channel: str) -> Any:
    """Cheap offline status — config presence, no network call."""
    _require_known_channel(channel)
    config = _g_cache('config', load_config)
    return jsonify(get_channel_status(channel, config))


def _medium_verify_result() -> Any:
    """Special-case ``medium``: run the real Playwright liveness probe
    (Plan 2026-07-06-004 Unit 3) instead of falling through to the generic
    ``verify_adapter_setup(..., mode='live')`` stub, which per the plan's own
    research always answers ``unverifiable_live`` for medium.

    Maps :class:`LivenessResult` onto the same
    :class:`~backlink_publisher.publishing._verify.VerifyResult` shape every
    other channel returns, so the frontend needs no channel-specific handling.
    ``LOGGED_IN``/``CACHED_BOUND`` both read as a definite ``ok`` (the liveness
    TTL cache is itself the definition of "still verified enough"); ``EXPIRED``
    and ``NEVER_BOUND`` map onto the existing ``token_expired``/``never``
    literals; ``NEEDS_RECHECK`` (probe timeout/disabled) reads as the existing
    transient ``timeout`` literal — never mutates state, same as any other
    channel's timeout.
    """
    from backlink_publisher.publishing._verify import VerifyResult
    from backlink_publisher.publishing.adapters.medium_liveness import LivenessResult
    from webui_store.channel_status import get_status

    from ..services.medium_liveness_service import medium_liveness_check

    outcome = medium_liveness_check()
    last_verified_at = get_status("medium").get("last_verified_at")

    if outcome in (LivenessResult.LOGGED_IN, LivenessResult.CACHED_BOUND):
        return VerifyResult(
            ok=True, last_verified_at=last_verified_at, last_verify_result="ok"
        )
    if outcome is LivenessResult.EXPIRED:
        return VerifyResult(
            ok=False,
            last_verified_at=last_verified_at,
            last_verify_result="token_expired",
            blockers=["Medium session expired — reconnect via Settings."],
        )
    if outcome is LivenessResult.NEVER_BOUND:
        return VerifyResult(
            ok=False,
            last_verify_result="never",
            blockers=["Medium is not bound — complete browser login first."],
        )
    # NEEDS_RECHECK: probe timed out, is disabled, or storage state vanished
    # mid-check — an honest "couldn't tell right now", not a verdict.
    return VerifyResult(
        ok=False,
        last_verified_at=last_verified_at,
        last_verify_result="timeout",
        blockers=["Medium liveness probe did not complete — try again shortly."],
    )


def _sync_channel_status(channel: str, result: Any) -> None:
    """Mirror a live-verify verdict into ``channel_status_store`` (Plan
    2026-07-06-004 Unit 3 gap-fill) so the dashboard's credentials card
    (which reads ``channel_status.list_all()``, not ``verify_health``)
    reflects the new state.

    Restricted to the ``CHANNELS`` whitelist (blogger/medium/velog) — every
    other channel (telegraph/ghpages/devto/...) would raise ``UsageError``
    from ``channel_status._validate_channel``, so those are skipped entirely
    and keep only the pre-existing ``verify_health.record()`` write above.

    Same transient/definite split as ``verify_health.record()``: only ``ok``
    and ``token_expired`` are definite signals; timeout/never/payload_invalid/
    unverifiable_live never mutate state (a network blip must not fake an
    expiry, nor must an honest "can't check this live" stub fake a bind).

    On ``ok`` while the stored status is already ``expired`` (with a
    recorded ``storage_state_path``), restores to ``bound`` via
    ``mark_bound`` — ``mark_verified`` alone preserves the existing status
    field, so without this the credentials card's failed list would never
    clear on a successful manual re-verify. ``identity_mismatch`` is
    deliberately left untouched either way (R6: operator must resolve it
    explicitly via the keep/replace routes, never an implicit clear).
    """
    from backlink_publisher.cli._bind.channels import CHANNELS
    if channel not in CHANNELS:
        return

    from webui_store import channel_status

    try:
        if result.last_verify_result == "ok":
            current = channel_status.get_status(channel)
            path = current.get("storage_state_path")
            if current.get("status") == "expired" and path:
                channel_status.mark_bound(channel, path)
            else:
                channel_status.mark_verified(channel)
        elif result.last_verify_result == "token_expired":
            if channel_status.get_status(channel).get("status") != "identity_mismatch":
                channel_status.mark_expired(channel)
    except Exception:
        pass


@bp.route('/api/<channel>/verify', methods=['POST'])
def api_channel_verify(channel: str) -> Any:
    """Live verify — calls platform's lightweight verify endpoint.

    CSRF guarded by app-level ``_global_csrf_guard``. Per-channel live impl
    deferred to Unit 6 backfill — Unit 4 ships the dispatch + JSON contract.
    ``medium`` is special-cased (Plan 2026-07-06-004 Unit 3) to a real
    liveness probe; every verdict also syncs into ``channel_status_store``
    for whitelisted channels (see ``_sync_channel_status``).
    """
    _require_known_channel(channel)
    if channel == "medium":
        result = _medium_verify_result()
    else:
        config = _g_cache('config', load_config)
        result = verify_adapter_setup(channel, config, mode='live')
    # Plan 2026-06-05-008: persist the credential verdict so an expired token
    # surfaces as needs-reconnect (plan-007 partition) across reloads. Only
    # token_expired/ok mutate state. Never let a store hiccup break verify.
    try:
        from webui_store import verify_health
        verify_health.record(channel, result.last_verify_result)
    except Exception:
        pass
    _sync_channel_status(channel, result)
    return jsonify(_verify_result_to_json(result))


@bp.route('/api/<channel>/dry-run', methods=['POST'])
def api_channel_dry_run(channel: str) -> Any:
    """Dry-run publish — validates adapter + payload without sending.

    Runs the publish pipeline under ``dry_run_intercept()`` which blocks any
    real HTTP sends. Returns the same VerifyResult JSON shape as /verify so
    the dashboard JS can reuse ``renderResult()``.
    """
    _require_known_channel(channel)
    config = _g_cache('config', load_config)
    result = verify_adapter_setup(channel, config, mode='dry-run')
    return jsonify(_verify_result_to_json(result))


@bp.route('/settings/save-target-keywords', methods=['POST'])
def settings_save_target_keywords() -> Any:
    """Save SEO anchor keyword pools for all target domains. Validation / de-dup /
    persistence is single-sourced in :class:`GlobalSettingsAPI`; this only adapts
    the form-indexed fields into the neutral per-domain pools mapping."""
    try:
        count = int(request.form.get('domain_count', 0))
        pools: dict[str, list[str]] = {}
        for i in range(1, count + 1):
            domain = request.form.get(f'domain_{i}', '').strip()
            if not domain:
                continue
            pools[domain] = request.form.get(f'keywords_{i}', '').splitlines()
    except Exception as e:
        return _safe_flash_redirect('/app/settings', flash_type='danger', msg=f'保存失败: {e}')
    r = GlobalSettingsAPI().save_keywords(pools)
    return _safe_flash_redirect('/app/settings', flash_type=r.level, msg=r.message, fragment=r.fragment)


@bp.route('/settings/schedule', methods=['POST'])
def settings_schedule_save() -> Any:
    """Save schedule interval settings (parse / clamp / persist single-sourced)."""
    r = GlobalSettingsAPI().save_schedule(request.form)
    return _safe_flash_redirect('/app/settings', flash_type=r.level, msg=r.message, fragment=r.fragment)


@bp.route('/settings/save-blog-ids', methods=['POST'])
def settings_save_blog_ids() -> Any:
    # Cleaning + save moved to BloggerSettingsAPI (single source shared with
    # /api/v1/settings/blogger/blog-ids). The parallel form lists are the legacy
    # transport encoding; the facade strips / drops empties / dedups by domain.
    from ..api.blogger_settings_api import BloggerSettingsAPI
    domains = request.form.getlist('domain[]')
    blog_ids_list = request.form.getlist('blog_id[]')
    r = BloggerSettingsAPI().save_blog_ids(dict(zip(domains, blog_ids_list)))
    return _safe_flash_redirect('/app/settings', flash_type=r.level, msg=r.message, fragment=r.fragment)


# Medium Integration-Token save/clear routes removed (Plan 2026-06-18-002 U8, medium-IT
# slice): Medium discontinued integration tokens (API archived 2023-03-02); the field
# is plaintext config (cfg.medium_integration_token), not a 0600 secret. The publish
# path still honours any existing value, but the management UI is retired — no SPA
# migration (operators with a legacy token edit config.toml directly).


@bp.route('/settings/revoke-blogger', methods=['POST'])
def settings_revoke_blogger() -> Any:
    # Revoke moved to OAuthAPI (single source shared with /api/v1/settings/blogger/revoke).
    from ..api.oauth_api import OAuthAPI
    r = OAuthAPI().revoke_blogger()
    return _safe_flash_redirect('/app/settings', flash_type=r.level, msg=r.message, fragment=r.fragment)


@bp.route('/api/velog/login', methods=['POST'])
def api_velog_login() -> Any:
    """Spawn velog-login in a detached subprocess (headed Playwright).

    The operator completes social login in the popped-up Chromium window. The
    spawn + error_code→message mapping moved to ``VelogLoginAPI`` (single source
    shared with ``/api/v1/settings/velog/login``); this route keeps the legacy
    200/500 status contract.
    """
    from ..api.velog_login_api import VelogLoginAPI

    r = VelogLoginAPI().login()
    body = {"ok": r.ok, "message": r.message, "log_path": r.log_path}
    if r.ok:
        return jsonify(body)
    body["error_code"] = r.error_code
    return jsonify(body), 500


@bp.route('/api/velog/status', methods=['GET'])
def api_velog_status() -> Any:
    """Return current velog channel status as JSON for polling."""
    from ..helpers.contexts import _get_velog_status
    return jsonify(_get_velog_status())


@bp.route('/settings/channels/<channel>/probe-liveness', methods=['POST'])
def probe_channel_liveness_route(channel: str) -> Any:
    """Probe and return liveness status for one channel (R9 — Plan 2026-06-09-001 U4).

    Returns {"status": "alive"|"expired"|"unreachable"}.  CSRF-protected
    automatically by the global POST guard.
    """
    from backlink_publisher.cli._bind.channels import CHANNELS
    if channel not in CHANNELS:
        abort(404)
    from ..services.credential_service import probe_channel_liveness
    status = probe_channel_liveness(channel)
    return jsonify({"status": status})
