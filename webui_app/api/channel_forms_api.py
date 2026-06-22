"""ChannelFormsAPI — static binding-form schemas for the SPA channel section.

Plan 2026-06-18-002 U7 (Settings section 3, slice 2 — binding forms). The SPA's
channel binding workbench needs, per WebUI-visible channel, the form to render:
which auth type, which fields (name + presentation), whether clear is supported.

This is PURE STATIC metadata — no ``get_channel_status`` probe, no secrets, no
``flask.request``. Bind-state (bound / identity) is NOT returned here: the SPA reads
it from the read-only overview (``ChannelOverviewAPI`` / ``GET …/channels``) and
joins by slug, so this endpoint stays cheap, cacheable and obviously leak-free.

Only the four FIXED-credential auth types get a form: ``token`` / ``token_fields`` /
``paste_blob`` / ``userpass``. Each form carries a ``save_via`` discriminator: most
channels persist through ``ChannelBindAPI``'s generic dispatch
(``/channels/<ch>/credential``); the channels ``ChannelBindAPI`` does NOT handle
(its ``_SKIP_CHANNELS``) but that DO have a single-token paste route — devto /
ghpages — persist through ``/channels/<ch>/token`` instead (``save_via="token"``).
Notion is the remaining ``_SKIP_CHANNELS`` member: it is two-field with its own
dedicated SPA card (NotionCard), so it is excluded here. ``oauth`` (blogger) and
``live_browser`` (mastodon / medium / velog) are card actions; ``anon`` needs no
credentials. Field NAMES come from ``credential_service`` (the save-path single
source); presentation comes from ``binding_forms``.
"""

from __future__ import annotations

_FIXED_CREDENTIAL_AUTH_TYPES = frozenset({"token", "token_fields", "paste_blob", "userpass"})

# Former _SKIP_CHANNELS members with a DEDICATED SPA card (own component/endpoint),
# excluded from the generic workbench. Notion is two-field (NotionCard); devto /
# ghpages are single-token and ARE folded in (save_via="token").
_DEDICATED_CARD_CHANNELS = frozenset({"notion"})


def _field_names(channel: str, auth_type: str, cs) -> list[str]:
    """Authoritative form-field names for *channel*, from the save-path dispatch
    maps. Empty list when the generic writer has no entry (then no form is shown)."""
    if auth_type == "token":
        return ["token"] if channel in cs._TOKEN_DISPATCH else []
    if auth_type == "userpass":
        return ["username", "password"] if channel in cs._USERPASS_CRED_BASENAMES else []
    if auth_type == "paste_blob":
        return ["blob"] if cs.paste_blob_expected_domain(channel) else []
    if auth_type == "token_fields":
        return cs.token_field_names(channel) or []
    return []


class ChannelFormsAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def list_forms(self) -> list[dict]:
        """One form schema per WebUI-visible fixed-credential channel, registry order."""
        from backlink_publisher.publishing.registry import auth_type, registered_platforms

        from ..binding_forms import field_presentation
        from ..binding_status import hidden_from_ui
        from ..services import app_meta, credential_service
        from .channel_bind_api import _SKIP_CHANNELS

        hidden = hidden_from_ui()
        # Channels ChannelBindAPI skips that still belong in this workbench (i.e. not
        # the dedicated-card ones) persist via the token-paste route, not /credential.
        token_route = _SKIP_CHANNELS - _DEDICATED_CARD_CHANNELS  # {devto, ghpages}
        forms: list[dict] = []
        for slug in registered_platforms():
            if slug in hidden or slug in _DEDICATED_CARD_CHANNELS:
                continue
            at = auth_type(slug)
            if at not in _FIXED_CREDENTIAL_AUTH_TYPES:
                continue
            names = _field_names(slug, at, credential_service)
            if not names:
                continue
            forms.append({
                "slug": slug,
                "display_name": app_meta.display_name(slug),
                "auth_type": at,
                "supports_clear": True,
                "save_via": "token" if slug in token_route else "credential",
                "fields": field_presentation(slug, at, names),
            })
        return forms
