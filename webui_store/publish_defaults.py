"""PublishDefaultsSqliteStore — last-used platforms + targets (Plan 2026-06-09-001 U5).

Single-row blob store in ``webui.db`` table ``publish_defaults``.
Stores ``last_platforms`` (JSON list) and ``last_target_ids`` (JSON list)
so the quick-publish button can bypass the full publish flow when defaults exist.

Now a thin :class:`~webui_store.sqlite_base.BlobSqliteStore` subclass. Unlike the
other blob stores it has no JSON predecessor, so ``_json_filename`` /
``_sentinel_name`` are left unset and the inherited ``migrate_from_json`` is a
no-op (and is never called by the factory).
"""

from __future__ import annotations

from .sqlite_base import BlobSqliteStore


class PublishDefaultsSqliteStore(BlobSqliteStore):
    """Single-row blob store for last-used publish defaults.

    Table: ``publish_defaults (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``

    ``load()`` returns ``{"last_platforms": [...], "last_target_ids": [...]}``
    or ``{}`` if no defaults have been saved yet.
    ``save(value)`` replaces the row atomically.
    ``update(fn)`` is inherited (load → fn → save under RLock).
    """

    _table_name = "publish_defaults"
    _value_type = dict
