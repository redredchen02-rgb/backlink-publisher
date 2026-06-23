"""Shared WebUI bootstrap metadata — Plan 2026-06-18-002 U2.

Single source for the data the Jinja context-processors inject (platform list,
bound platforms, Pro status, edition flags) so the legacy template path and the
new ``/api/v1`` bootstrap endpoints cannot drift on "which platforms are bound /
active" (plan R3 — server-side derived data stays single-source). The authority
underneath is the publisher registry + ``settings_service``; this module only
adds the thin display/predicate wiring that both surfaces share.

Flask-free except where a request-scoped config load is genuinely needed.
"""

from __future__ import annotations

from typing import Any


def display_name(slug: str) -> str:
    """Manifest UiMeta display name, falling back to ``slug.title()`` (legacy)."""
    from backlink_publisher.publishing.registry import ui_meta

    meta = ui_meta(slug)
    return meta.display_name if meta is not None else slug.title()


def platforms_payload() -> list[dict[str, str]]:
    """Full registered-platform list (history filter chips need the FULL list)."""
    import backlink_publisher.publishing.adapters  # noqa: F401 - populate registry
    from backlink_publisher.publishing.registry import registered_platforms

    return [{"slug": s, "display_name": display_name(s)} for s in registered_platforms()]


def bound_platforms_payload() -> list[dict[str, str]]:
    """Publish-form filter: channels whose offline binding check passes and that
    are manifest-visible. Fails open to the full list on any load error — the
    same fail-open the template context-processor uses, so the form never breaks.
    """
    import backlink_publisher.publishing.adapters  # noqa: F401 - populate registry
    from backlink_publisher.publishing.registry import bound_platforms as _bound

    try:
        from backlink_publisher.config import load_config

        from ..binding_status import get_channel_status

        cfg = load_config()

        def _is_bound(_cfg: Any, name: str) -> bool:
            return bool(get_channel_status(name, _cfg).get("bound"))

        return [
            {"slug": s, "display_name": display_name(s)}
            for s in _bound(cfg, _is_bound)
        ]
    except Exception:
        return platforms_payload()


def pro_status_payload() -> dict[str, Any]:
    """Enriched, redaction-safe Pro-Mode summary (never includes api_key)."""
    from . import settings_service

    try:
        return settings_service.pro_status_summary(settings_service.load_llm_settings())
    except Exception:
        return {
            "configured": False,
            "endpoint_host": "",
            "model": "",
            "article_gen": False,
            "image_gen": False,
            "last_test": None,
        }


def lite_edition() -> bool:
    from ..helpers.edition import is_lite_edition

    return is_lite_edition()
