"""Session factory — single entry point for authenticated ``requests.Session``.

``SessionManager.get_session(channel, config)`` is the call publish code
paths use instead of ad-hoc token loading:

1. Look up the channel's ``SessionDescriptor`` from the registry.
2. Load credential via the ``CredentialProvider``.
3. Optionally refresh if near expiry (OAuth ``expires_at`` window).
4. Attach auth (cookies / Bearer header) to a ``requests.Session``.
5. Probe liveness via the descriptor's ``ProbeConfig``.
6. Return the authenticated session (or raise ``AuthExpiredError``).
"""

from __future__ import annotations

import time

import requests

from backlink_publisher._util.errors import AuthExpiredError, DependencyError
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.publishing._manifest_types import SessionDescriptor

from .credential import Credential
from .provider import CredentialProvider

# Module-level name so tests can patch it via
# "...session.session_manager.get_descriptor"
from backlink_publisher.publishing._registry_manifest import session as get_descriptor  # noqa: E402


class SessionManager:
    """Manages the full session lifecycle for a channel.

    Usage::

        provider = DefaultCredentialProvider()
        mgr = SessionManager(provider)
        session = mgr.get_session("velog", config)
        response = session.get("https://velog.io/api/v2/...")

    The session returned by ``get_session()`` is fully authenticated and
    liveness-confirmed. Callers may reuse it across multiple requests
    within a publish batch; the SessionManager does NOT cache sessions
    (the caller decides reuse policy).
    """

    def __init__(self, provider: CredentialProvider) -> None:
        self._provider = provider

    # ── Public API ──────────────────────────────────────────────────────────

    def get_session(self, channel: str, config: Config) -> requests.Session:
        """Return an authenticated ``requests.Session`` for *channel*.

        Steps:
        1. Load credential from the stored artifact.
        2. Refresh if near expiry (OAuth tokens with ``expires_at``).
        3. Create ``requests.Session`` with auth attached.
        4. Probe session liveness against the configured endpoint.
        5. Return the session (or raise ``AuthExpiredError``).

        Raises:
            DependencyError: channel has no ``SessionDescriptor`` or
                credential files are missing.
            AuthExpiredError: credential expired or probe confirms
                the session is no longer authenticated.
        """
        descriptor = get_descriptor(channel)
        if descriptor is None:
            raise DependencyError(
                f"No SessionDescriptor registered for channel: {channel!r}"
            )

        # Step 1 — load credential
        cred = self._provider.load(channel, config, descriptor)

        # Step 2 — refresh near-expiry credentials
        cred = self._maybe_refresh(cred, descriptor, config, channel)

        # Step 3 — build authenticated session
        session = requests.Session()
        self._apply_session(session, cred, descriptor)

        # Step 4 — probe liveness
        alive, reason = self._provider.probe(session, descriptor)
        if not alive:
            log.warning(f"Session probe failed for {channel}: {reason}")
            raise AuthExpiredError(
                channel=channel,
                reason=(
                    f"Session expired (probe: {reason}). "
                    f"Re-bind the channel to continue."
                ),
            )

        log.info(f"Session established for {channel} (probe: {reason})")
        return session

    # ── Internal helpers ────────────────────────────────────────────────────

    def _maybe_refresh(
        self,
        cred: Credential,
        descriptor: SessionDescriptor,
        config: Config,
        channel: str = "unknown",
    ) -> Credential:
        """Refresh *cred* if its ``expires_at`` is within the window.

        Returns the (possibly updated) credential. ``cookie-implicit``
        refresh config is skipped (returns the original credential).
        """
        if descriptor.refresh is None:
            return cred
        if cred.expires_at is None:
            return cred

        window = descriptor.refresh.expiration_window_sec or 300
        if time.time() + window < cred.expires_at:
            return cred  # not yet near expiry

        log.info(
            f"Credential for {descriptor.credential_type} near expiry "
            f"(expires_at={cred.expires_at}, window={window}s) "
            "— attempting refresh",
        )

        updated = self._provider.refresh(cred, descriptor, config, channel=channel)
        if updated is not None:
            return updated

        # cookie-implicit returns None — no explicit refresh possible,
        # but the session may still work (Set-Cookie handles it).
        return cred

    def _apply_session(
        self,
        session: requests.Session,
        cred: Credential,
        descriptor: SessionDescriptor,
    ) -> None:
        """Attach auth to *session* based on credential type."""
        if cred.type == "cookie" and cred.cookies:
            session.cookies.update(cred.cookies)
            # Apply any probe-required headers (origin, referer, UA)
            if descriptor.probe and descriptor.probe.headers:
                session.headers.update(
                    dict(descriptor.probe.headers)
                )
        elif cred.type in ("bearer", "oauth") and cred.token:
            session.headers.update(
                {"Authorization": f"Bearer {cred.token}"}
            )
