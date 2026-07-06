"""Blueprint registration entry — Plan 2026-05-18-001 Unit 3."""

from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    # Plan 2026-06-18-002 U1 — versioned JSON API surface (/api/v1). First
    # blueprint to use url_prefix; RFC 9457 error handlers wired below.
    from ..api.v1 import bp as api_v1_bp
    from ..api.v1 import register_api_error_handlers

    # llm_bp deregistered in U8 5b; module kept as patch surface for test_webui_unit3_security.
    from . import llm as _llm_patch_surface
    from .batch import bp as batch_bp
    from .batch_campaign import bp as batch_campaign_bp
    from .batch_sites import bp as batch_sites_bp
    from .campaign_progress import bp as campaign_progress_bp
    from .checkpoint import bp as checkpoint_bp
    from .command_center import bp as command_center_bp

    # channel_bind_save_bp deregistered in U8 5b — replaced by /api/v1/settings/channels/*/credential
    from .copilot import bp as copilot_bp
    from .dashboard import bp as dashboard_bp
    from .drafts import bp as drafts_bp
    from .equity_batch_recheck import bp as equity_batch_recheck_bp
    from .equity_gap import bp as equity_gap_bp
    from .equity_ledger import bp as equity_ledger_bp
    from .health import bp as health_bp
    from .health_actions import bp as health_actions_bp
    from .history import bp as history_bp
    from .keep_alive import bp as keep_alive_bp
    from .main import bp as main_bp
    from .metrics import bp as metrics_bp
    from .oauth import bp as oauth_bp
    from .optimization_status import bp as optimization_status_bp
    from .pipeline import bp as pipeline_bp
    from .pipeline import bp_publish as pipeline_publish_bp
    from .pr_queue import bp as pr_queue_bp
    from .profiles import bp as profiles_bp
    from .publish_defaults import bp as publish_defaults_bp
    from .queue import bp as queue_bp
    from .schedule import bp as schedule_bp
    from .seo_viz import bp as seo_viz_bp
    from .settings_basic import bp as settings_basic_bp
    from .sites import bp as sites_bp

    # Plan 2026-06-18-002 U3 — flag-gated SPA catch-all under /app/*.
    from .spa import bp as spa_bp
    from .survival_dashboard import bp as survival_dashboard_bp

    # medium_login_bp, bind_bp, token_paste_bp, image_gen_bp deregistered in U8
    # (Plan 2026-06-18-002 5b) — replaced by /api/v1/settings/* endpoints.
    from .url_verify import bp as url_verify_bp

    for bp in (main_bp, pipeline_bp, pipeline_publish_bp, batch_bp, checkpoint_bp,
               history_bp, drafts_bp, settings_basic_bp, oauth_bp,
               profiles_bp, sites_bp, queue_bp, dashboard_bp,
               url_verify_bp,
               seo_viz_bp, equity_ledger_bp, health_bp, health_actions_bp,
               copilot_bp, schedule_bp, pr_queue_bp, metrics_bp,
               batch_campaign_bp, campaign_progress_bp, keep_alive_bp,
               equity_gap_bp, equity_batch_recheck_bp,
               optimization_status_bp, command_center_bp,
               survival_dashboard_bp, publish_defaults_bp,
               batch_sites_bp, api_v1_bp, spa_bp):
        app.register_blueprint(bp)

    # RFC 9457 problem+json for the /api/v1 surface (path-scoped 404/405 +
    # ApiProblem). Registered here so create_app needs no change.
    register_api_error_handlers(app)
