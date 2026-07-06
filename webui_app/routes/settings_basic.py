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


@bp.route('/api/<channel>/verify', methods=['POST'])
def api_channel_verify(channel: str) -> Any:
    """Live verify — calls platform's lightweight verify endpoint.

    CSRF guarded by app-level ``_global_csrf_guard``. Per-channel live impl
    deferred to Unit 6 backfill — Unit 4 ships the dispatch + JSON contract.
    """
    _require_known_channel(channel)
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
