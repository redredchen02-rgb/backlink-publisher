"""ProfilesSqliteStore — campaign-profiles backed by webui.db.

Replaces the ``campaign-profiles.json`` JsonStore (a list of profile dicts,
always accessed as a whole) with a single-row blob table. Now a thin
:class:`~webui_store.sqlite_base.BlobSqliteStore` subclass — the table DDL,
``load`` / ``save`` (single-row ``INSERT OR REPLACE``), and the one-shot
``migrate_from_json`` import are all inherited; only the table name, value
type, and migration filenames differ.

Startup migration: on first boot after this code is deployed, the existing
``campaign-profiles.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-15-005-refactor-webui-store-base-sqlite-plan.md Unit 4
(originally 2026-06-03-008 Unit 3).
"""

from __future__ import annotations

from .sqlite_base import BlobSqliteStore

_SENTINEL_NAME = ".webui-profiles-migrated-v1"
_JSON_FILENAME = "campaign-profiles.json"


class ProfilesSqliteStore(BlobSqliteStore):
    """Single-row blob store for campaign profiles (a list of dicts).

    Table: ``profiles (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``

    ``load()`` returns the stored list or ``[]`` if absent.
    ``save(value)`` replaces the row. ``update(fn)`` is inherited
    (load → fn → save under RLock). ``migrate_from_json`` is inherited.
    """

    _table_name = "profiles"
    _value_type = list
    _json_filename = _JSON_FILENAME
    _sentinel_name = _SENTINEL_NAME
