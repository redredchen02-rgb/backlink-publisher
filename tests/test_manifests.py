"""Manifest descriptor tests — SessionDescriptor lookup via session().

Validates that each channel's ``session=SessionDescriptor(...)`` declare
the correct credential_type, config_path, probe, and refresh config.
"""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher.publishing._manifest_types import (
    ProbeConfig,
    RefreshConfig,
    SessionDescriptor,
)
from backlink_publisher.publishing._registry_manifest import session as get_descriptor


def test_velog_session_descriptor():
    """VELOG_MANIFEST session declares cookie-type with probe + implicit refresh."""
    desc = get_descriptor("velog")
    assert desc is not None
    assert isinstance(desc, SessionDescriptor)
    assert desc.credential_type == "cookie"
    assert "velog-cookies.json" in desc.config_path
    assert isinstance(desc.probe, ProbeConfig)
    assert "velog.io/graphql" in desc.probe.endpoint
    assert isinstance(desc.refresh, RefreshConfig)
    assert desc.refresh.method == "cookie-implicit"


def test_substack_session_descriptor():
    """SUBSTACK_MANIFEST session declares cookie-type with implicit refresh."""
    desc = get_descriptor("substack")
    assert desc is not None
    assert isinstance(desc, SessionDescriptor)
    assert desc.credential_type == "cookie"
    assert "substack-credentials.json" in desc.config_path
    # Substack has no liveness probe — detects expiry from 401/403
    assert desc.probe is None
    assert isinstance(desc.refresh, RefreshConfig)
    assert desc.refresh.method == "cookie-implicit"


def test_blogger_session_descriptor():
    """BLOGGER_MANIFEST session declares oauth-type with oauth-refresh-token."""
    desc = get_descriptor("blogger")
    assert desc is not None
    assert isinstance(desc, SessionDescriptor)
    assert desc.credential_type == "oauth"
    assert "blogger-token.json" in desc.config_path
    assert desc.probe is None  # No probe — adapter catches AuthExpiredError directly
    assert isinstance(desc.refresh, RefreshConfig)
    assert desc.refresh.method == "oauth-refresh-token"
    assert "googleapis.com" in (desc.refresh.token_endpoint or "")


def test_medium_session_descriptor():
    """MEDIUM_MANIFEST session declares bearer-type with no probe or refresh."""
    desc = get_descriptor("medium")
    assert desc is not None
    assert isinstance(desc, SessionDescriptor)
    assert desc.credential_type == "bearer"
    assert "medium-token.json" in desc.config_path
    assert desc.probe is None
    assert desc.refresh is None


def test_telegraph_has_no_session_descriptor():
    """TELEGRAPH_MANIFEST has no session key — must return None."""
    desc = get_descriptor("telegraph")
    assert desc is None


def test_ghpages_has_no_session_descriptor():
    """GHPAGES_MANIFEST has no session key — must return None."""
    desc = get_descriptor("ghpages")
    assert desc is None


def test_nonexistent_channel_returns_none():
    """An unregistered channel must return None, not raise."""
    desc = get_descriptor("_nonexistent_channel_")
    assert desc is None
