"""Credential value object for channel session management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backlink_publisher.publishing._manifest_types import SessionCredentialType


@dataclass(frozen=True)
class Credential:
    """Loaded credential data for a single channel.

    Created by ``CredentialProvider.load()``, consumed by
    ``SessionManager.get_session()`` to attach auth to a ``requests.Session``.
    """

    type: SessionCredentialType
    cookies: dict[str, str] | None = None
    token: str | None = None
    oauth_data: dict[str, Any] | None = None
    expires_at: float | None = None
    refresh_token: str | None = None
