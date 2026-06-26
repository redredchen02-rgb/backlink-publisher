"""Drift guard for the credential-save dispatch cluster (U3b migration).

Maps consolidated in ``webui_app.services.credential_service`` (U3b):

  - ``_TOKEN_DISPATCH``          (auth_type "token")
  - ``_TOKEN_FIELDS_DISPATCH``   (auth_type "token_fields"; includes ghpages)
  - ``_PASTE_BLOB_CHANNELS``     (auth_type "paste_blob")
  - ``_USERPASS_CRED_BASENAMES`` (auth_type "userpass")

Plus ``channel_bind_api._SKIP_CHANNELS`` (dedicated-route guard; moved into the
ChannelBindAPI facade in Plan 2026-06-18-002 U7).

Authority is SUBSET, not equality.
"""
__tier__ = "unit"

import pytest

import backlink_publisher.publishing.adapters  # noqa: F401 — trigger registration
from backlink_publisher.publishing.registry import (
    active_platforms,
    platforms_by_auth_type,
)
from webui_app.api.channel_bind_api import _SKIP_CHANNELS
from webui_app.services.credential_service import (
    _PASTE_BLOB_CHANNELS,
    _TOKEN_DISPATCH,
    _TOKEN_FIELDS_DISPATCH,
    _USERPASS_CRED_BASENAMES,
)


def _allowed_for(*auth_types: str) -> frozenset[str]:
    """Union of the active-platform buckets for the given auth_types."""
    out: set[str] = set()
    for t in auth_types:
        out |= platforms_by_auth_type(t)
    return frozenset(out)


# (map name, its keys, the auth_type bucket(s) every key must belong to).
_DISPATCH_CASES = [
    ("_TOKEN_DISPATCH",        set(_TOKEN_DISPATCH),        ("token",)),
    ("_TOKEN_FIELDS_DISPATCH", set(_TOKEN_FIELDS_DISPATCH), ("token_fields",)),
    ("_PASTE_BLOB_CHANNELS",   set(_PASTE_BLOB_CHANNELS),   ("paste_blob",)),
    ("_USERPASS_CRED_BASENAMES", set(_USERPASS_CRED_BASENAMES), ("userpass",)),
]


@pytest.mark.parametrize("name,keys,buckets", _DISPATCH_CASES, ids=lambda v: v if isinstance(v, str) else "")
def test_dispatch_keys_are_registered_active_and_correct_auth_type(name, keys, buckets):
    """Every key in each typed save-dispatch map is a registered, active
    platform whose auth_type matches the handler's bucket."""
    allowed = _allowed_for(*buckets)
    stale = keys - allowed
    assert not stale, (
        f"{name} has keys {sorted(stale)} that are not active platforms of "
        f"auth_type {buckets} — a removed/renamed platform left a stale entry, "
        f"or its auth_type drifted. Allowed: {sorted(allowed)}"
    )


def test_skip_channels_are_all_registered_active():
    """_SKIP_CHANNELS names channels routed to dedicated save endpoints; each
    must still be a registered, active platform (else the skip is stale)."""
    stale = set(_SKIP_CHANNELS) - set(active_platforms())
    assert not stale, (
        f"_SKIP_CHANNELS has stale entries {sorted(stale)} no longer registered/active"
    )


def test_subset_check_flags_a_planted_unregistered_key():
    """R7 red->green honesty: the subset check the guard relies on must FAIL on
    a planted unregistered/wrong-bucket key, so it is not tautological."""
    paste_blob = platforms_by_auth_type("paste_blob")
    planted = set(_PASTE_BLOB_CHANNELS) | {"not_a_real_platform"}
    assert planted - paste_blob == {"not_a_real_platform"}
    # And a wrong-bucket key (a real platform of the wrong auth_type) is caught:
    assert ({"livejournal"} - paste_blob) == {"livejournal"}
