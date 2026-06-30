"""Shared constants — single source of truth for cross-package values.

Moved from ``cli._bind.channels`` to resolve the ``_util → cli`` layer
violation (Plan 2026-06-24-002 U7). All packages import ``CHANNELS``
and ``EVENTS`` from here; ``cli._bind.channels`` re-exports them for
backward compat.
"""

from __future__ import annotations

CHANNELS: frozenset[str] = frozenset({"velog", "medium", "blogger"})

EVENTS: dict[str, str] = {
    "attempt_login": "cli_bind_attempt_login",
}

#: User-Agent string for preflight content fetches — identifies this fetcher
#: distinctly so targets can rate-limit it separately.
#: P14 A5: moved from content._preflight_fetch to resolve _util → domain violation.
PREFLIGHT_UA: str = "backlink-publisher/0.1 preflight-targets"

#: Legacy alias kept for backward compat.
USER_AGENT: str = PREFLIGHT_UA
