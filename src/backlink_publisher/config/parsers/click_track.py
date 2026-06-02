"""Parser for the ``[click_track]`` TOML section."""

from __future__ import annotations

from typing import Any

from ..types import ClickTrackConfig


def _parse_click_track(raw: dict[str, Any] | None) -> ClickTrackConfig | None:
    """Parse ``[click_track]`` TOML section into ``ClickTrackConfig``.

    Expected schema::

        [click_track]
        credential_path = "/path/to/service-account.json"
        sites = {"https://example.com" = "123456789", ...}

    Returns ``None`` when the section is absent.
    """
    if not raw:
        return None

    credential_path: str | None = raw.get("credential_path")
    raw_sites: dict[str, Any] = raw.get("sites", {})
    sites: dict[str, str] = {}
    for k, v in raw_sites.items():
        if isinstance(v, (str, int)):
            sites[str(k)] = str(v)

    return ClickTrackConfig(
        credential_path=credential_path,
        sites=sites,
    )
