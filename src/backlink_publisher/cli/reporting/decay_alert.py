"""decay-alert — check for backlink decay and emit decay.alert events.

Run after recheck-backlinks. Queries link.rechecked events in the last
WINDOW_DAYS days; for each target with ≥ THRESHOLD distinct dead URLs,
emits one decay.alert event (deduped: skip if a decay.alert for the same
target already exists within the window).

Callable as ``python -m backlink_publisher.cli.decay_alert`` or via the
scripts/run-recheck-periodic.sh wrapper.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any


WINDOW_DAYS = 14
THRESHOLD = 2
DEAD_VERDICTS = frozenset({"host_gone", "link_stripped", "dofollow_lost"})


def _utc_since(window_days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=window_days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(store: Any = None) -> int:
    """Check decay and emit alerts. Returns count of new decay.alert events emitted."""
    from backlink_publisher.events import EventStore
    from backlink_publisher.events.kinds import DECAY_ALERT, LINK_RECHECKED

    if store is None:
        store = EventStore()

    since = _utc_since(WINDOW_DAYS)

    # Count distinct dead URLs per target within the window.
    rows = store.query(
        """
        SELECT
            target_url,
            COUNT(DISTINCT live_url) AS dead_url_count
        FROM events
        WHERE kind = ?
          AND ts_utc >= ?
          AND target_url IS NOT NULL
          AND live_url IS NOT NULL
          AND json_extract(payload_json, '$.verdict') IN ('host_gone','link_stripped','dofollow_lost')
        GROUP BY target_url
        HAVING COUNT(DISTINCT live_url) >= ?
        """,
        (LINK_RECHECKED, since, THRESHOLD),
    )

    if not rows:
        return 0

    # Find targets that already have a decay.alert in the window (dedup).
    alerted = store.query(
        """
        SELECT DISTINCT target_url
        FROM events
        WHERE kind = ?
          AND ts_utc >= ?
          AND target_url IS NOT NULL
        """,
        (DECAY_ALERT, since),
    )
    already_alerted = {r["target_url"] for r in alerted}

    emitted = 0
    for row in rows:
        target_url = row["target_url"]
        if target_url in already_alerted:
            continue
        store.append(
            kind=DECAY_ALERT,
            target_url=target_url,
            payload={"target_url": target_url, "lost_count": int(row["dead_url_count"]), "window_days": WINDOW_DAYS},
        )
        emitted += 1

    return emitted


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="decay-alert",
        description="Check for backlink decay and emit decay.alert events to events.db",
    )
    parser.parse_args(argv)

    try:
        count = run()
        if count:
            print(f"decay-alert: {count} new decay.alert event(s) emitted", file=sys.stderr)
        else:
            print("decay-alert: no new decay alerts", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"decay-alert: error — {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
