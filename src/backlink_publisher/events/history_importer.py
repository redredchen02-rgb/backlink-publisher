"""Startup history→events.db one-shot importer (Plan 2026-05-28-007 U4).

Reads existing ``publish-history.json`` content and writes each entry to
events.db via ``publish_writer``.  Idempotent: guarded by a file sentinel
in the config directory so it runs at most once per deployment.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backlink_publisher.config.loader import _config_dir
from backlink_publisher.events.publish_writer import (
    map_history_entry,
    write_event,
)

log = logging.getLogger(__name__)

_SENTINEL = ".history-events-migrated"


def _sentinel_path() -> Path:
    return _config_dir() / _SENTINEL


def _has_migrated() -> bool:
    return _sentinel_path().exists()


def _mark_migrated() -> None:
    from datetime import UTC, datetime
    _sentinel_path().write_text(datetime.now(UTC).isoformat())


def import_history_to_events() -> None:
    """One-shot import: read all history entries, write as events.

    Guarded by a file sentinel — runs at most once.  Logs counts on
    completion.  Never raises (startup must not crash).
    """
    if _has_migrated():
        return

    from webui_store import history_store

    items = history_store.load()
    if not items:
        _mark_migrated()
        log.info("history_importer: no items to import, marking migrated")
        return

    written = 0
    skipped = 0
    for item in items:
        mapped = map_history_entry(item)
        if mapped is None:
            skipped += 1
            continue
        row_id = write_event(
            mapped[0], mapped[1],
            target_url=item.get("target_url"),
        )
        if row_id is not None:
            written += 1
        else:
            skipped += 1

    _mark_migrated()
    log.info(
        "history_importer: wrote %d events to events.db (%d skipped)",
        written, skipped,
    )
