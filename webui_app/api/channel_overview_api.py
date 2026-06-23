"""ChannelOverviewAPI — read-only channel binding status list, transport-neutral.

Plan 2026-06-18-002 U7, settings section 3 (channels). The SPA settings page's
channel section needs the same per-channel status the legacy ``dashboard_channels``
context built: each WebUI-visible platform with its auth type + offline binding
status (bound / identity / dofollow / last-verify / blockers). This composes the
existing single sources — ``registered_platforms()`` minus ``hidden_from_ui()``,
``get_channel_status()``, ``registry.auth_type()`` and ``app_meta.display_name()`` —
so the SPA and the Jinja dashboard cannot drift on "which channels, what state".

Read-only: no secrets cross the wire (``identity`` is the bound account name, not a
credential), so the GET route carries no inline guard. The per-channel binding
WRITES already migrated (ChannelBindAPI / BindAPI / OAuthAPI / token-paste); the
SPA binding forms consuming them land in later section-3 slices.
"""

from __future__ import annotations


class ChannelOverviewAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def list_channels(self) -> list[dict]:
        """One row per WebUI-visible platform, in registry order."""
        from backlink_publisher.config import load_config
        from backlink_publisher.publishing.registry import auth_type, registered_platforms

        from ..binding_status import get_channel_status, hidden_from_ui
        from ..services import app_meta

        cfg = load_config()
        hidden = hidden_from_ui()
        rows: list[dict] = []
        for slug in registered_platforms():
            if slug in hidden:
                continue
            # Guard per-channel so one adapter's status error doesn't blank the whole
            # list (this is a fresh diagnostic read, not a faithful move of the legacy
            # all-or-nothing context build).
            try:
                st = get_channel_status(slug, cfg)
            except Exception as e:
                st = {"blockers": [f"status unavailable: {e}"]}
            rows.append({
                "slug": slug,
                "display_name": app_meta.display_name(slug),
                "auth_type": auth_type(slug),
                "bound": bool(st.get("bound")),
                "identity": st.get("identity"),
                "dofollow": st.get("dofollow"),
                "last_verify_result": st.get("last_verify_result"),
                "blockers": list(st.get("blockers") or []),
            })
        return rows
