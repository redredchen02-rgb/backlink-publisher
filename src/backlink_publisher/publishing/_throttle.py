"""ThrottleEngine — dynamic inter-publish delay computation (Plan U2.2).

Each platform adapter already declares a static ``post_publish_delay_seconds``
per publish result and reads an optional ``<PLATFORM>_PUBLISH_DELAY_S`` env var.
The ThrottleEngine layers dynamic adjustments on top of these baselines:

  - Recent HTTP 429 responses → delay × 2
  - Last publish failed → delay × 1.5
  - Randomized jitter ±20 %

Data sources for history: events.db (publish.failed, publish.throttled).

Usage::

    engine = ThrottleEngine()
    delay = engine.get_delay("medium", base_delay=30)
    # → e.g. 54.0 (30 × 1.5 for past failure, ±20% jitter)
"""

from __future__ import annotations

import os
from pathlib import Path
import random
import sqlite3
from typing import Any

from backlink_publisher.config import _cache_dir


def _default_events_db() -> str:
    """Resolve the events.db path from environment or default cache dir."""
    return os.path.join(str(_cache_dir()), "events.db")


# Time window for recent failures (seconds: 1 hour)
_RECENT_WINDOW_S = 3600


class ThrottleEngine:
    """Dynamic throttle calculator that adjusts base delays from publish history.

    This is a pure advisory calculator — it does not enforce delays itself.
    Callers (publish-backlinks, CampaignWorker) call ``get_delay()`` and
    ``sleep()`` independently.
    """

    def __init__(
        self,
        events_db_path: str | None = None,
    ) -> None:
        self._events_db = events_db_path or _default_events_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_delay(self, platform: str, base_delay: float = 30.0) -> float:
        """Compute recommended inter-publish delay for *platform*.

        Args:
            platform: Platform name (e.g. ``"medium"``, ``"blogger"``).
            base_delay: Static baseline from adapter or env var (seconds).

        Returns:
            Recommended delay in seconds (≥1.0).
        """
        history = self._recent_events(platform, window_s=_RECENT_WINDOW_S)

        delay = base_delay

        # Recent 429 → 2×
        recent_429_count = sum(
            1 for e in history if e.get("status") == 429
        )
        if recent_429_count > 0:
            delay *= 2.0

        # Last publish failed → 1.5×
        if history and history[0].get("event") in (
            "publish.failed",
            "publish.throttled",
        ):
            delay *= 1.5

        # Jitter ±20 % (uniform distribution)
        jitter = random.uniform(-0.2, 0.2) * delay
        delay += jitter

        return max(round(delay, 1), 1.0)

    # ------------------------------------------------------------------
    # History loader
    # ------------------------------------------------------------------

    def _recent_events(
        self, platform: str, window_s: int = _RECENT_WINDOW_S
    ) -> list[dict[str, Any]]:
        """Load recent publish events for *platform* from events.db.

        Returns newest-first events within the time window.
        """
        db_path = Path(self._events_db)
        if not db_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT event, status, inserted_at
                FROM events
                WHERE platform = ?
                  AND event IN ('publish.failed', 'publish.throttled',
                                'publish.succeeded', 'publish.rate_limited')
                  AND (unixepoch(inserted_at) * 1000) > ?
                ORDER BY inserted_at DESC
                LIMIT 20
                """,
                (platform, int(time_now_ms() - window_s * 1000)),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except (sqlite3.Error, OSError):
            return []


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def time_now_ms() -> int:
    """Current time in milliseconds (UTC)."""
    import time
    return int(time.time() * 1000)
