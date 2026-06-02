"""Template context builders and render helper — Plan 2026-05-21-007 Unit 5.

Flask-facing layer only: _render and _settings_context (Flask/session coupling).
All Flask-free helpers are in webui_app.services.settings_service (U4).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import render_template

from backlink_publisher.config import (
    load_blogger_token,
    load_config,
)

from webui_store import (
    drafts_store as _drafts_store,
    history_store as _history_store,
    profiles_store as _profiles_store,
    queue_store as _queue_store,
)

from .security import _FLASK_PORT, _ensure_csrf_token, _oauth_callback_uri
from ._request_cache import _g_cache
from .channel_probes import (
    _get_blogger_token_status,
    _get_medium_browser_status,
    _get_velog_status,
    _image_gen_status,
)
from ..services import settings_service


# ── Thin wrappers with per-request caching ────────────────────────────────────

def _llm_settings_file():
    return settings_service.llm_settings_file()


def _load_llm_settings() -> dict:
    return settings_service.load_llm_settings()


def _load_schedule_settings() -> dict:
    return _g_cache("schedule", settings_service.load_schedule_settings)


def _save_schedule_settings(data: dict) -> None:
    settings_service.save_schedule_settings(data)


def _calc_next_available(requested_dt: datetime) -> datetime:
    return settings_service.calc_next_available(requested_dt)


def _persist_three_tier_config(main_url: str, category_url: str, work_url: str) -> None:
    settings_service.persist_three_tier_config(main_url, category_url, work_url)


def _load_incomplete_run():
    return settings_service.load_incomplete_run()


def _token_paste_status(cfg, channel: str, load_fn, *, token_field: str = "token") -> dict:
    return settings_service.token_paste_status(cfg, channel, load_fn, token_field=token_field)


def _token_paste_status_notion(cfg, load_fn) -> dict:
    return settings_service.token_paste_status_notion(cfg, load_fn)


def _group_history(items: list[dict]) -> list[dict]:
    return settings_service.group_history(items)




def _settings_context(flash=None):
    """Build template context for the settings page."""
    from flask import session as _flask_session

    from backlink_publisher.config import (
        load_devto_token,
        load_ghpages_token,
        load_medium_token,
        load_notion_token,
    )
    from backlink_publisher.cli._bind.channels import CHANNELS
    from webui_store.channel_status import list_all as _channel_list_all
    from ..services.bind_job import BIND_ERROR_MESSAGES

    cfg = _g_cache('config', load_config)
    token_data = load_blogger_token(cfg.blogger_token_path)
    medium_token_data = load_medium_token()

    ghpages_status = _token_paste_status(cfg, "ghpages", load_ghpages_token)
    ghpages_config_summary = [
        ("repo", cfg.ghpages.repo if cfg.ghpages else ""),
        ("branch", cfg.ghpages.branch if cfg.ghpages else "gh-pages"),
        ("path_template", cfg.ghpages.path_template if cfg.ghpages else "_posts/{date}-{slug}.md"),
    ]

    notion_status = _token_paste_status_notion(cfg, load_notion_token)
    devto_status = _token_paste_status(cfg, "devto", load_devto_token, token_field="api_key")
    notion_config_summary: list[tuple[str, str]] = []
    devto_config_summary: list[tuple[str, str]] = []

    from backlink_publisher.config.tokens import load_medium_integration_token as _load_it
    _it_data = _load_it()
    _it_val = (_it_data or {}).get("integration_token", "").strip()
    token = _it_val or cfg.medium_integration_token or ""
    masked = ("*" * 8 + token[-4:]) if len(token) > 4 else ("*" * len(token))

    all_targets = sorted(
        set(cfg.blogger_blog_ids.keys()) | set(cfg.target_anchor_keywords.keys())
    )

    try:
        from ..medium_liveness import medium_liveness_check
        medium_liveness_check()
    except Exception:  # noqa: BLE001 — Settings render must not depend on probe
        pass

    try:
        channel_statuses = _channel_list_all()
    except Exception:
        channel_statuses = {}

    try:
        csrf_token = _ensure_csrf_token()
    except Exception:
        csrf_token = ""

    velog_status = _get_velog_status()

    try:
        # Plan 2026-05-25-002 Unit 4a — use ``active_platforms()`` from
        # the registry; this composes ``registered_platforms()`` with the
        # manifest ``visibility`` filter, so the dashboard card list now
        # automatically excludes any future ``visibility='hidden'`` or
        # ``visibility='retired'`` channel without needing to touch this
        # helper. ``HIDDEN_FROM_UI`` (Unit 2a PEP 562 alias) is still the
        # legacy fallback path but redundant once we read from
        # ``active_platforms()`` directly.
        from backlink_publisher.publishing.registry import active_platforms
        from ..binding_status import get_channel_status
        dashboard_channels = [
            (name, get_channel_status(name, cfg))
            for name in active_platforms()
        ]
    except Exception:
        dashboard_channels = []

    # Plan 2026-05-29-003 Unit 2 — pre-group the overview channels into
    # automation tiers for the settings overview panel. Rendering must never
    # fail because grouping failed: fall back to [] (template renders no groups).
    try:
        from .channel_tiers import group_channels_by_tier
        dashboard_channel_tiers = group_channels_by_tier(dashboard_channels)
    except Exception:
        dashboard_channel_tiers = []

    return dict(
        flash=flash,
        csrf_token=csrf_token,
        dashboard_channels=dashboard_channels,
        dashboard_channel_tiers=dashboard_channel_tiers,
        medium_browser_status=_get_medium_browser_status(cfg, session=_flask_session),
        blogger_token=bool(token_data),
        blogger_client_id=cfg.blogger_oauth.client_id if cfg.blogger_oauth else "",
        blogger_client_secret_set=bool(cfg.blogger_oauth and cfg.blogger_oauth.client_secret),
        blog_ids=cfg.blogger_blog_ids,
        medium_token_set=bool(token),
        medium_token_masked=masked if token else "",
        medium_token_file_exists=bool(medium_token_data),
        medium_oauth_configured=bool(medium_token_data and cfg.medium_oauth),
        config_path=str(cfg.config_dir / "config.toml"),
        token_path=str(cfg.blogger_token_path),
        port=_FLASK_PORT,
        callback_uri=_oauth_callback_uri(),
        profiles=_g_cache('profiles', _profiles_store.load),
        plans_list=[],
        schedule_settings=_load_schedule_settings(),
        llm_settings=_load_llm_settings(),
        image_gen_status=_image_gen_status(cfg),
        all_targets=all_targets,
        target_anchor_keywords=cfg.target_anchor_keywords,
        binding_channels=sorted(CHANNELS),
        channel_statuses=channel_statuses,
        bind_error_messages=BIND_ERROR_MESSAGES,
        velog_status=velog_status,
        velog_cookies_path=velog_status.get('cookies_path', ''),
        ghpages_status=ghpages_status,
        ghpages_config_summary=ghpages_config_summary,
        notion_status=notion_status,
        notion_config_summary=notion_config_summary,
        devto_status=devto_status,
        devto_config_summary=devto_config_summary,
    )


def _draft_tab_extra() -> dict:
    """Extra template context for the draft tab."""
    return {
        'schedule_settings': _load_schedule_settings(),
    }


def _render(template_name: str, **kwargs):
    """Render a Jinja2 template, auto-injecting common context.

    Auto-injected context (when not provided by caller):
      - history, blogger_token_status, profiles, draft_queue, tasks,
        now_iso, suggested_next, incomplete_run
    """
    if 'history' not in kwargs:
        kwargs['history'] = _g_cache('history', _history_store.load)
    if 'grouped_history' not in kwargs:
        kwargs['grouped_history'] = _group_history(kwargs['history'])
    if 'blogger_token_status' not in kwargs:
        kwargs['blogger_token_status'] = _get_blogger_token_status()
    if 'profiles' not in kwargs:
        kwargs['profiles'] = _g_cache('profiles', _profiles_store.load)
    if 'draft_queue' not in kwargs:
        kwargs['draft_queue'] = _g_cache('drafts', _drafts_store.load)
    if 'tasks' not in kwargs:
        try:
            kwargs['tasks'] = _g_cache('tasks', _queue_store.load)
        except Exception:
            kwargs['tasks'] = []
    if 'now_iso' not in kwargs:
        now = datetime.now()
        kwargs['now_iso'] = now.strftime('%Y-%m-%dT%H:%M')
        kwargs.setdefault(
            'suggested_next',
            _calc_next_available(now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
        )
    if 'incomplete_run' not in kwargs:
        kwargs['incomplete_run'] = _load_incomplete_run()
    return render_template(template_name, **kwargs)
