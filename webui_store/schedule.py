"""ScheduleSqliteStore — schedule-settings backed by webui.db.

Replaces the ``schedule-settings.json`` JsonStore with a single-row blob
table. Now a thin :class:`~webui_store.sqlite_base.BlobSqliteStore` subclass —
the table DDL, ``load`` / ``save``, and the one-shot ``migrate_from_json``
import are all inherited; only the table name, value type, and migration
filenames differ. All access goes through ``load/save/update``; no new public
API.

Startup migration: on first boot after this code is deployed, the existing
``schedule-settings.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-15-005-refactor-webui-store-base-sqlite-plan.md Unit 4
(originally 2026-06-03-008 Unit 2).
"""

from __future__ import annotations

from .sqlite_base import BlobSqliteStore

_SENTINEL_NAME = ".webui-schedule-migrated-v1"
_JSON_FILENAME = "schedule-settings.json"


class ScheduleSqliteStore(BlobSqliteStore):
    """Single-row blob store for schedule settings.

    Table: ``settings (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``

    ``load()`` returns the stored dict or ``{}`` if absent.
    ``save(value)`` replaces the row. ``update(fn)`` is inherited
    (load → fn → save under RLock). ``migrate_from_json`` is inherited.
    """

    _table_name = "settings"
    _value_type = dict
    _json_filename = _JSON_FILENAME
    _sentinel_name = _SENTINEL_NAME
