"""ProfilesSqliteStore — campaign-profiles backed by webui.db.

Replaces the ``campaign-profiles.json`` JsonStore (a list of profile dicts,
always accessed as a whole) with a single-row blob table. Mirrors the
``ScheduleSqliteStore`` blob pattern; the only difference is the default is
a list (``[]``) rather than a dict.

Startup migration: on first boot after this code is deployed, the existing
``campaign-profiles.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
Unit 3.
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

_SENTINEL_NAME = ".webui-profiles-migrated-v1"
_JSON_FILENAME = "campaign-profiles.json"


class ProfilesSqliteStore(SqliteStore):
    """Single-row blob store for campaign profiles (a list of dicts).

    Table: ``profiles (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``

    ``load()`` returns the stored list or ``[]`` if absent.
    ``save(value)`` replaces the row.
    ``update(fn)`` is inherited (load → fn → save under RLock).
    """

    def __init__(self, db: WebUIDatabase) -> None:
        super().__init__(db)
        self._init_table()

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS profiles "
                "(id INTEGER PRIMARY KEY, data_json TEXT NOT NULL DEFAULT '[]')"
            )

    def load(self) -> list[Any]:
        def _op() -> list[Any]:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT data_json FROM profiles WHERE id = 1"
                ).fetchone()
            if row is None:
                return []
            try:
                result = json.loads(row[0])
                return result if isinstance(result, list) else []
            except (json.JSONDecodeError, TypeError):
                return []

        return _retry_sqlite(_op)

    def save(self, value: Any) -> None:
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO profiles (id, data_json) "
                        "VALUES (1, ?)",
                        (json.dumps(value, ensure_ascii=False),),
                    )
            _retry_sqlite(_op)

    # ── Startup migration ─────────────────────────────────────────────────

    def migrate_from_json(self, config_dir: Path) -> None:
        """One-shot import from ``campaign-profiles.json`` if not yet migrated.

        Same load-bearing sequence as ``ScheduleSqliteStore.migrate_from_json``:
        commit to webui.db → rename ``.json`` → chmod 0o600 → write sentinel.
        Corrupt/absent JSON is silently skipped (sentinel NOT written so a
        later-appearing file can still be imported).
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

        try:
            text = json_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            _log.warning("profiles_store migration: skipping corrupt/unreadable %s", json_path)
            return

        self.save(data if isinstance(data, list) else [])

        try:
            json_path.rename(migrated_path)
        except OSError as exc:
            _log.warning("profiles_store migration: rename failed: %s", exc)
            return

        try:
            os.chmod(migrated_path, 0o600)
        except OSError:
            pass

        sentinel.write_text("migrated", encoding="utf-8")
