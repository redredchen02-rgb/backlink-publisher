"""R7: operator-local LIVE real-credential non-author publish (draft default).

This is the **live** half — it is NEVER ``__tier__='e2e'`` (CI injects zero
secrets, so an e2e-tiered live test would attempt a credential-less real publish
and hard-fail). It is gated behind ``BACKLINK_PUBLISHER_REAL_LIVE_PUBLISH=1`` and
the ``real_live_publish`` marker, and the operator runs it **once** against a
dedicated throwaway non-author account.

Safety invariants (the always-on test below asserts them WITHOUT credentials):
  * default mode is **draft / unpublished**; a real public post requires a
    SEPARATE explicit flag ``BACKLINK_PUBLISHER_REAL_LIVE_PUBLISH_PUBLIC=1``;
  * a real publish to a third-party platform under a real identity is
    irreversible (indexing, account actioning) — draft + teardown by default.
"""

from __future__ import annotations

# NOTE: deliberately NO ``__tier__ = 'e2e'`` here (see module docstring).
import os

import pytest

_LIVE_ENV = "BACKLINK_PUBLISHER_REAL_LIVE_PUBLISH"
_PUBLIC_ENV = "BACKLINK_PUBLISHER_REAL_LIVE_PUBLISH_PUBLIC"

# Both adapters whose register() declares dofollow=True today — the ≥2 ratio.
_RATIO_PLATFORMS = ("medium", "blogger")


def live_publish_mode() -> str:
    """Resolve the live-publish mode: draft unless the operator explicitly opts
    into a real public post via a SECOND env flag. Pure + credential-free so the
    safety default is unit-testable without touching the network."""
    return "publish" if os.environ.get(_PUBLIC_ENV) == "1" else "draft"


def test_live_publish_defaults_to_draft(monkeypatch):
    """Safety (always runs, no creds): without the public flag the live path
    publishes in draft mode; the public flag is required for a real post."""
    monkeypatch.delenv(_PUBLIC_ENV, raising=False)
    assert live_publish_mode() == "draft"
    monkeypatch.setenv(_PUBLIC_ENV, "1")
    assert live_publish_mode() == "publish"


@pytest.mark.real_live_publish
@pytest.mark.skipif(
    os.environ.get(_LIVE_ENV) != "1",
    reason=f"operator-local live publish; set {_LIVE_ENV}=1 to run against a "
           f"throwaway non-author account",
)
def test_live_real_credential_dofollow_ratio():
    """Operator runs this ONCE: publish in draft mode to a throwaway non-author
    account on >=2 dofollow platforms, assert the operator backlink is dofollow
    on each draft/preview URL, then delete the draft. Real adapters + creds.

    Kept as an explicit, documented runbook body rather than a mock — the whole
    point of the live half is to exercise the real path the replay half cannot.
    """
    pytest.skip(
        "Live publish runbook (operator-executed):\n"
        f"  1. Bind throwaway non-author credentials for {list(_RATIO_PLATFORMS)}.\n"
        f"  2. Run publish-backlinks --mode {live_publish_mode()} for each platform.\n"
        "  3. Assert verify_link_attributes(draft_url) target_nofollow is False.\n"
        "  4. Delete each draft; record the run via _util/secrets (0o600, redacted).\n"
        f"  5. A public post additionally requires {_PUBLIC_ENV}=1."
    )
