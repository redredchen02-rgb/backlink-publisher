"""ScheduleSqliteStore — schedule-settings backed by webui.db.

Replaces the ``schedule-settings.json`` JsonStore with a single-row blob
table. All access goes through ``load/save/update``; no new public API.

Startup migration: on first boot after this code is deployed, the existing
``schedule-settings.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
Unit 2.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import SqliteStore, WebUIDatabase

_log = logging.getLogger(__name__)

_SENTINEL_NAME = ".webui-schedule-migrated-v1"
_JSON_FILENAME = "schedule-settings.json"


class ScheduleSqliteStore(SqliteStore):
    """Single-row blob store for schedule settings.

    Table: ``settings (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``

    ``load()`` returns the stored dict or ``{}`` if absent.
    ``save(value)`` replaces the row.
    ``update(fn)`` is inherited (load → fn → save under RLock).
    """

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS settings "
                "(id INTEGER PRIMARY KEY, data_json TEXT NOT NULL DEFAULT '{}')"
            )

    def load(self) -> dict[str, Any]:
        def _op() -> dict[str, Any]:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT data_json FROM settings WHERE id = 1"
                ).fetchone()
            if row is None:
                return {}
            try:
                result = json.loads(row[0])
                return result if isinstance(result, dict) else {}
            except (json.JSONDecodeError, TypeError):
                return {}

        return _retry_sqlite(_op)

    def save(self, value: Any) -> None:
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (id, data_json) "
                        "VALUES (1, ?)",
                        (json.dumps(value, ensure_ascii=False),),
                    )
            _retry_sqlite(_op)

    # ── Startup migration ─────────────────────────────────────────────────

    def migrate_from_json(self, config_dir: Path) -> None:
        """One-shot import from ``schedule-settings.json`` if not yet migrated.

        Sequence (load-bearing order):
        1. Check sentinel → skip if present.
        2. If ``.migrated`` file present + sentinel absent → crash-recovery:
           write sentinel only (data was already committed before prior crash).
        3. Read JSON (corrupt/absent → skip; sentinel NOT written → allows retry).
        4. Commit data to webui.db.
        5. Rename ``.json`` → ``.json.migrated``.
        6. chmod ``.json.migrated`` to 0o600.
        7. Write sentinel.
        """
        sentinel = config_dir / _SENTINEL_NAME
        json_path = config_dir / _JSON_FILENAME
        migrated_path = json_path.with_suffix(".json.migrated")

        if sentinel.exists():
            return

        # Crash-recovery: rename completed but sentinel not written
        if migrated_path.exists() and not sentinel.exists():
            sentinel.write_text("migrated", encoding="utf-8")
            return

        if not json_path.exists():
            return

        # Load from JSON (silent-skip on corrupt)
        try:
            text = json_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, OSError):
            _log.warning("schedule_store migration: skipping corrupt/unreadable %s", json_path)
            return

        # 4. Commit to webui.db first (save() raises on failure — no guard needed)
        self.save(data if isinstance(data, dict) else {})

        # 5. Rename
        try:
            json_path.rename(migrated_path)
        except OSError as exc:
            _log.warning("schedule_store migration: rename failed: %s", exc)
            return

        # 6. Tighten permissions on the migrated file
        try:
            os.chmod(migrated_path, 0o600)
        except OSError:
            pass

        # 7. Write sentinel
        sentinel.write_text("migrated", encoding="utf-8")
