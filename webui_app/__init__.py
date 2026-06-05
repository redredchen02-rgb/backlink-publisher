"""WebUI Flask app factory — Plan 2026-05-18-001 Unit 3.

``create_app()`` returns the configured Flask app with all blueprints
registered, scheduler started (when not in test mode), and pending
draft jobs restored from the queue.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta
from pathlib import Path

from flask import Flask


def _get_version_file() -> Path:
    """Resolve the asset-version stamp path lazily from environment."""
    from backlink_publisher.config.loader import _config_dir
    return _config_dir() / "asset-version.stamp"


def _compute_asset_version(static_folder: str | None) -> str:
    """Per-deploy cache-busting stamp for ``url_for('static', ..., v=…)``.

    Derived once from the newest mtime of any bundled static asset, so an
    operator's long-lived console session cannot serve a stale classic JS
    against freshly-deployed module HTML (no build step / no bundler hash).
    """
    version_file = _get_version_file()

    # Check cache first regardless of static_folder - allows reading cached value
    try:
        if version_file.exists():
            return version_file.read_text().strip() or "0"
    except OSError:
        pass

    if not static_folder:
        return "0"
    try:
        latest = 0
        for root, _dirs, files in os.walk(static_folder):
            for name in files:
                try:
                    latest = max(latest, os.stat(os.path.join(root, name)).st_mtime_ns)
                except OSError:
                    continue
        ver = format(latest, "x") or "0"
        version_file.parent.mkdir(parents=True, exist_ok=True)
        version_file.write_text(ver)
        return ver
    except OSError:
        return "0"


def create_app(*, start_scheduler: bool | None = None) -> Flask:
    """Build the Flask app.

    Args:
        start_scheduler: When True, start APScheduler and restore pending
            draft jobs. When None (default), starts only when not running
            under pytest (detected via PYTEST_CURRENT_TEST env var).
    """
    template_dir = Path(__file__).parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        secret_key = 'backlink-publisher-secret-' + str(uuid.uuid4())
        if os.environ.get('FLASK_ENV') != 'development':
            logging.getLogger(__name__).warning(
                "SECRET_KEY not set in environment; using a random key. "
                "This will invalidate all sessions and CSRF tokens on restart. "
                "Set SECRET_KEY for production use."
            )
    app.secret_key = secret_key
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)
    # Plan 2026-05-21-006 Unit 3.5 — SESSION_COOKIE_SECURE was unconditional
    # `True`, which contradicts the loopback-HTTP framing: under HTTP the
    # Secure flag prevents the cookie from ever being sent back. Loopback
    # operators got CSRF tokens that browsers stripped, then 403 on
    # subsequent POSTs. Now env-driven: True when the operator deploys
    # behind a TLS reverse proxy, False for the default loopback case.
    app.config['SESSION_COOKIE_SECURE'] = (
        os.environ.get('BACKLINK_PUBLISHER_SESSION_COOKIE_SECURE', '0') == '1'
    )
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Plan 2026-06-04-001 Unit 9 / R6 — the internal LITE edition binds
    # loopback-only and refuses a non-loopback BIND_HOST at startup, so
    # ALLOW_NETWORK can no longer expose the app off-loopback. It still
    # *disables* the credential-bind endpoints (see _refuse_when_allow_network),
    # so warn the operator that the flag is now a narrow toggle, not a network
    # opt-in, and they probably do not want it set.
    if os.environ.get('BACKLINK_PUBLISHER_ALLOW_NETWORK') == '1':
        import warnings
        warnings.warn(
            "BACKLINK_PUBLISHER_ALLOW_NETWORK=1 has no effect on binding in this "
            "edition: the WebUI binds loopback-only (a non-loopback BIND_HOST is "
            "refused at startup) and this flag only disables the credential-bind "
            "endpoints while set. Unset it unless you specifically want those "
            "endpoints disabled.",
            RuntimeWarning,
            stacklevel=2,
        )

    # Plan 2026-05-22 P7 C1: register app-context stores so WebUI routes
    # can access them via ``current_app.extensions['webui_stores']``.
    from webui_store.registry import WebUIStores
    WebUIStores().init_app(app)

    # Share the publish-path markdown→HTML renderer with Jinja so preview
    # visual matches the published article (Plan 2026-05-19-007 Unit 2).
    from backlink_publisher._util.markdown import render_to_html
    app.jinja_env.filters['render_markdown'] = render_to_html

    # Register all blueprints
    from .routes import register_blueprints
    register_blueprints(app)

    # Inject the live registered platforms into every template render.
    # Plan 2026-05-19-002 U2 / R6: WebUI is reverse-driven by the publisher
    # registry — register("X", XAdapter) is now sufficient to make X
    # appear in the publish-form select, the history filter-chip row,
    # the JS counter dict, and norm_platform routing without any HTML edit.
    # ``s.title()`` is the v1 display-name source (no _display_name_map dict
    # per scope-guardian F5); i18n migration is a Deferred follow-up.
    @app.context_processor
    def inject_platforms():
        # Importing adapters at first request populates the registry
        # side-effect — same idiom as plan_backlinks.py / publish_backlinks.py.
        import backlink_publisher.publishing.adapters  # noqa: F401
        from backlink_publisher.publishing.registry import (
            bound_platforms as registry_bound_platforms,
            registered_platforms,
            ui_meta,
        )

        # Plan 2026-05-25-002 Unit 4a — display name reverse-lookup.
        # When the channel's manifest declares a UiMeta, use its
        # display_name (e.g. ghpages -> "GitHub Pages", devto -> "Dev.to").
        # Otherwise fall back to the legacy ``s.title()`` derivation.
        # Legacy behaviour preserved for the 7 non-velog channels until
        # Phase 2 migrations populate their UiMeta.
        def _display(slug: str) -> str:
            meta = ui_meta(slug)
            return meta.display_name if meta is not None else slug.title()

        all_slugs = list(registered_platforms())
        # History filter chips still need the FULL list (per
        # ``feedback_platforms_vs_bound_platforms_split``) — already-
        # published unbound channels stay filterable.
        platforms = [
            {"slug": s, "display_name": _display(s)} for s in all_slugs
        ]

        # `bound_platforms` is the publish-form filter: only channels
        # whose offline binding check passes (and that aren't hidden /
        # retired per manifest visibility) appear in the platform select.
        # Falls back to the full list on any load failure so the form
        # never breaks mid-render.
        #
        # Plan U4a: ``registry.bound_platforms(cfg, is_bound)`` composes
        # ``active_platforms()`` (drops hidden + retired + experimental)
        # with the injected ``is_bound`` predicate. The predicate stays
        # at this call site to avoid the publishing -> webui_app layer
        # inversion (see registry.py:bound_platforms docstring).
        try:
            from backlink_publisher.config import load_config
            from .binding_status import get_channel_status
            from .helpers._request_cache import _g_cache
            cfg = _g_cache('config', load_config)

            def _is_bound(_cfg, name: str) -> bool:
                return bool(get_channel_status(name, _cfg).get("bound"))

            bound_slugs = registry_bound_platforms(cfg, _is_bound)
            bound_platforms = [
                {"slug": s, "display_name": _display(s)} for s in bound_slugs
            ]
        except Exception:
            bound_platforms = platforms

        return {"platforms": platforms, "bound_platforms": bound_platforms}

    # Plan 2026-05-20-002 Unit 5 — register csrf_token() Jinja global so
    # the homepage <meta name="csrf-token"> tag can read the per-session
    # token for the new /url-verify POST endpoint. Calling
    # _ensure_csrf_token() is idempotent within a request.
    @app.context_processor
    def inject_csrf_token():
        # Return the STRING value so templates can use ``{{ csrf_token }}``
        # uniformly. Previously this returned the function — templates
        # were split between ``{{ csrf_token }}`` and ``{{ csrf_token() }}``
        # and per-route ``_settings_context`` re-bound to a string, so
        # ``{{ csrf_token() }}`` exploded under /settings. The try/except
        # handles template-only renders that some unit tests do outside
        # of a real request context (session is unavailable there).
        from .helpers.security import _ensure_csrf_token
        try:
            return {"csrf_token": _ensure_csrf_token()}
        except RuntimeError:
            return {"csrf_token": ""}

    # Cache-busting: stamp a per-deploy version onto every base.html
    # url_for('static', ..., v=asset_version) reference. Computed once and
    # cached on app.config so the static-tree walk happens at most once.
    @app.context_processor
    def inject_asset_version():
        version = app.config.get("ASSET_VERSION")
        if version is None:
            version = _compute_asset_version(app.static_folder)
            app.config["ASSET_VERSION"] = version
        return {"asset_version": version}

    # Plan 2026-06-05-003 U1: one enriched ``pro_status`` object is the single
    # source of truth for every Pro-Mode visibility surface (nav pill, index
    # nudge, settings status header). It is a cheap "last known" summary, NOT a
    # live health probe — no network call fires on render; a missing api_key or
    # endpoint is caught at POST time with a 400. ``llm_configured`` is kept as a
    # derived alias so the shipped copilot panel (`_copilot_panel.html`) needs
    # no change (back-compat).
    @app.context_processor
    def inject_pro_status():
        from .services import settings_service
        try:
            summary = settings_service.pro_status_summary(
                settings_service.load_llm_settings()
            )
        except Exception as e:
            # Fail-safe: a malformed llm-settings.json must never 500 every page.
            # Log at debug so the degraded-to-inactive state is diagnosable.
            app.logger.debug("inject_pro_status fell back to inactive: %s", e)
            summary = {
                "configured": False, "endpoint_host": "", "model": "",
                "article_gen": False, "image_gen": False, "last_test": None,
            }
        return {"pro_status": summary, "llm_configured": summary["configured"]}

    # Plan 2026-06-04-001 Unit 10 / R7+R8 — the LITE edition shows the operator
    # only the keep-alive core. ``lite_edition`` drives the nav trim in
    # base.html; the surface gate (registered below, after the CSRF guard) makes
    # the hidden blueprints unreachable, not just unlinked.
    from .helpers.edition import LITE_HIDDEN_BLUEPRINTS, is_lite_edition

    @app.context_processor
    def inject_lite_edition():
        return {"lite_edition": is_lite_edition()}

    # Global CSRF enforcement. SameSite=Lax + loopback already block most
    # cross-site POST, but operators who flip BACKLINK_PUBLISHER_ALLOW_NETWORK
    # to bind off-loopback lose Lax's effective protection. Defence-in-depth
    # so every state-mutating verb checks a token rather than trusting that
    # 12 of 16 blueprints remembered to call _check_csrf_or_abort inline.
    #
    # Tests can opt out via ``app.config['CSRF_ENABLED'] = False`` or the
    # legacy ``WTF_CSRF_ENABLED = False`` (many existing tests already set
    # that flag defensively — both are honored).
    app.config.setdefault('CSRF_ENABLED', True)

    @app.before_request
    def _global_csrf_guard():
        from flask import request as _req
        if _req.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return
        if app.config.get('CSRF_ENABLED', True) is False:
            return
        if app.config.get('WTF_CSRF_ENABLED', True) is False:
            return
        # OAuth callbacks arrive via 302 from Google with their own HMAC-signed
        # state param verified inside the handler; CSRF token can't survive
        # the cross-origin redirect.
        if _req.endpoint and _req.endpoint.endswith('oauth_callback'):
            return
        from .helpers.security import _check_csrf_or_abort
        _check_csrf_or_abort()

    # Plan 2026-06-04-001 Unit 10 / R7+R8 — server-side LITE surface gate.
    # Registered AFTER _global_csrf_guard so the CSRF guard stays the FIRST
    # before_request hook (E3 invariant, tests/test_webui_csrf_ordering.py).
    # Ordering is security-irrelevant for a 404-only denial gate: a GET to a
    # hidden blueprint 404s here; a no-token POST 403s on the CSRF guard first —
    # uniform with any unmatched path, so it leaks no hidden-route existence.
    @app.before_request
    def _lite_surface_gate():
        from flask import abort, request as _req
        if is_lite_edition() and _req.blueprint in LITE_HIDDEN_BLUEPRINTS:
            abort(404)

    # Global rate limiting — POST/PUT/PATCH/DELETE capped at 60 req/min per IP.
    # GET/HEAD/OPTIONS and /api/url-verify/* are exempt (the latter carries its
    # own per-session/per-host throttle via url_verify_throttle.py).
    # Auto-disabled under pytest so existing tests need no change.
    from flask import request as _flask_req
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["60 per minute"],
        default_limits_exempt_when=lambda: (
            _flask_req.method in ("GET", "HEAD", "OPTIONS")
            or _flask_req.path.startswith("/api/url-verify")
        ),
        storage_uri="memory://",
        enabled='PYTEST_CURRENT_TEST' not in os.environ,
    )
    _limiter.init_app(app)

    # Start scheduler unless under pytest (tests don't need background jobs)
    if start_scheduler is None:
        start_scheduler = 'PYTEST_CURRENT_TEST' not in os.environ

    if start_scheduler:
        from .scheduler import _restore_scheduled_jobs, _scheduler
        if not _scheduler.running:
            _scheduler.start()
        _restore_scheduled_jobs()

        # Plan 2026-05-19-001 Unit 4: real-runtime startup hooks. Gated by
        # ``start_scheduler`` so pytest never fires them. Wrapped because a
        # disk read failure must not crash ``create_app``.
        # NB: logging is module-level (imported at line 10) — no local import
        # here to avoid UnboundLocalError from Python's compile-time scope
        # analysis.
        _log = logging.getLogger(__name__)
        try:
            from webui_store.channel_status import reconcile_on_load
            reconcile_on_load()
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            _log.warning("channel_status.reconcile_on_load failed: %s", exc)
        # Plan 2026-05-27-001 Unit 3: one-shot purge of orphaned credential
        # files for hard-removed channels (jianshu/zhihu/cnblogs). Self-disables
        # via a sentinel after first run.
        try:
            from webui_store.channel_status import purge_removed_channel_credentials
            purge_removed_channel_credentials()
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            _log.warning("channel_status.purge_removed_channel_credentials failed: %s", exc)
        try:
            from .services.bind_job import reap_orphans
            reap_orphans()
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            _log.warning("bind_job.reap_orphans failed: %s", exc)

        # Plan 2026-05-21-001 Unit 1: reap stale publish-launched Chrome.
        # Verifies PID-file ownership via cmdline substring (chrome_bin +
        # profile path) before signaling, defending against PID reuse.
        try:
            from backlink_publisher.publishing.browser_publish.chrome_session import (
                reap_orphan_publish_chrome,
            )
            outcome = reap_orphan_publish_chrome()
            if outcome.get("action") != "noop":
                _log.info("chrome_session.reap_orphan_publish_chrome: %s", outcome)
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            _log.warning("chrome_session.reap_orphan_publish_chrome failed: %s", exc)

        # Plan 2026-05-28-007 U4: one-shot history→events.db import.
        try:
            from backlink_publisher.events.history_importer import (
                import_history_to_events,
            )
            import_history_to_events()
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            _log.warning("history_importer.import_history_to_events failed: %s", exc)

        # Plan 2026-06-02-001 U5: start CampaignWorker for batch campaigns.
        try:
            from .campaign_worker import CampaignWorker
            _worker = CampaignWorker()
            app.config['CAMPAIGN_WORKER'] = _worker
            _log.info("CampaignWorker started")
        except Exception as exc:  # noqa: BLE001 — startup must not crash
            _log.warning("CampaignWorker startup failed: %s", exc)

    # Always register CAMPAIGN_WORKER (even when start_scheduler is False),
    # defaulting to None so routes can check availability.
    if 'CAMPAIGN_WORKER' not in app.config:
        app.config['CAMPAIGN_WORKER'] = None

    return app
