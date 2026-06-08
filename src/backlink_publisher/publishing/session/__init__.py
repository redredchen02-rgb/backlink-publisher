"""Session credential management — credential lifecycle & session factory.

``CredentialProvider`` loads, probes, and refreshes channel credentials.
``SessionManager`` wraps provider + descriptor lookup into a single
``get_session(channel, config) -> requests.Session`` call that publish
code paths use instead of ad-hoc token loading.

Usage::

    from backlink_publisher.publishing.session import DefaultCredentialProvider, SessionManager

    provider = DefaultCredentialProvider()
    mgr = SessionManager(provider)
    session = mgr.get_session("velog", config)
    # session is authenticated, probed, and optionally refreshed
"""

from __future__ import annotations

from .credential import Credential
from .provider import CredentialProvider, DefaultCredentialProvider
from .session_manager import SessionManager

__all__ = [
    "Credential",
    "CredentialProvider",
    "DefaultCredentialProvider",
    "SessionManager",
]
