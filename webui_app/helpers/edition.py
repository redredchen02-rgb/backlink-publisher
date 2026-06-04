"""LITE-edition gate (plan 2026-06-04-001 Unit 10 / R7+R8).

The internal edition ships a focused operator surface: keep-alive core only,
with Pro / not-yet-implemented blueprints hidden server-side (404), not merely
unlinked. ``BACKLINK_PUBLISHER_LITE`` selects the edition at launch; the env is
read per call (never cached) so a test can flip it with ``monkeypatch.setenv``.

Default is *off* (full surface) so the existing Pro test suite is unaffected;
the launcher exports ``BACKLINK_PUBLISHER_LITE=1`` for the operator.
"""
from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes"}

#: Blueprint names hidden (404) in the LITE edition — Pro surfaces and the
#: reserved-but-unimplemented copilot live-run (501) seam. Routes stay
#: registered in code; the gate makes them unreachable, not absent.
LITE_HIDDEN_BLUEPRINTS = frozenset({"copilot", "seo_viz", "metrics", "pr_queue"})


def is_lite_edition() -> bool:
    return os.environ.get("BACKLINK_PUBLISHER_LITE", "").strip().lower() in _TRUTHY
