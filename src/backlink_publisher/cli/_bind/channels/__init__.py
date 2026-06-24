"""Channel recipe registry — re-exports CHANNELS/EVENTS from _util.channels.

CHANNELS is the *only* place new browser-binding channels are added.
Every entry point (CLI argparse, webui routes, AuthExpiredError ctor,
mark_bound / mark_expired) may import from here; the constants live in
``backlink_publisher._util.channels`` so domain packages can validate
channel names without importing the cli/ layer (plan 2026-06-24-002 U7).
"""

from __future__ import annotations

from backlink_publisher._util.channels import CHANNELS, EVENTS  # noqa: F401

__all__ = ["CHANNELS", "EVENTS"]
