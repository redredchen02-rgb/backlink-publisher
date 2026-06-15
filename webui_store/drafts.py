"""DraftsSqliteStore — draft-queue persistence backed by webui.db.

Replaces the ``draft-queue.json`` JsonStore with a proper row table keyed by
draft id, with indexed ``campaign_id`` and ``inserted_at`` columns so
``get_by_campaign_id`` is a single SQL WHERE and the newest-first ordering of
the legacy ``insert_first`` head-insert is preserved explicitly.

**Ordering is load-bearing.** The legacy ``insert_first`` put new items at
position 0 (newest-first). ``load()`` is ``SELECT … ORDER BY inserted_at DESC``
so that contract is preserved without relying on rowid (which would silently
reverse it and break the drafts UI). ``inserted_at`` is an epoch-millisecond
integer assigned at INSERT (preserved from the item dict if already present).

The public API (``get_item`` / ``update_item`` / ``delete_item`` /
``get_by_campaign_id`` / ``bulk_delete`` / ``bulk_update`` / ``insert_first`` /
``bulk_publish_now`` plus inherited ``load`` / ``save`` / ``update``) is
preserved exactly, including return contracts.

Startup migration: on first boot after this code is deployed, the existing
``draft-queue.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
Unit 6.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import BaseSqliteStore

_SENTINEL_NAME = ".webui-drafts-migrated-v1"
_JSON_FILENAME = "draft-queue.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


class DraftsSqliteStore(BaseSqliteStore):
    """Row-table store for the draft queue, backed by webui.db.

    Table::

        drafts (
          id           TEXT PRIMARY KEY,
          campaign_id  TEXT,
          inserted_at  INTEGER NOT NULL,
          data_json    TEXT NOT NULL
        )
        CREATE INDEX drafts_campaign ON drafts(campaign_id)
        CREATE INDEX drafts_inserted ON drafts(inserted_at DESC)

    ``load()`` returns the full ``list[dict]`` newest-first (``ORDER BY
    inserted_at DESC``); ``save(value)`` is a delete-all + bulk-insert rewrite.
    ``update(fn)`` is inherited (load → fn → save under RLock).

    Accepts either a :class:`WebUIDatabase` (the migrated factory path) or a
    plain :class:`~pathlib.Path` (backward compat for callers/tests that still
    pass a file path) — in the latter case a ``WebUIDatabase`` is wrapped
    around it.
    """

    _value_type = list
    _json_filename = _JSON_FILENAME
    _sentinel_name = _SENTINEL_NAME

    # Backward-compat: legacy route tests do
    # ``monkeypatch.setattr(drafts_store, "_path", tmp_path / "drafts.json")``
    # (the old JsonStore slot name). Mirror it onto the ``path`` redirect so
    # those tests keep isolating the store to a tmp db.
    @property
    def _path(self) -> Path:
        return self._db.path

    @_path.setter
    def _path(self, value: Path) -> None:
        self.path = value

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS drafts ("
            "id TEXT PRIMARY KEY, "
            "campaign_id TEXT, "
            "inserted_at INTEGER NOT NULL, "
            "data_json TEXT NOT NULL)"
        )

    def _indices_sql(self) -> list[str]:
        return [
            "CREATE INDEX IF NOT EXISTS drafts_campaign ON drafts(campaign_id)",
            "CREATE INDEX IF NOT EXISTS drafts_inserted ON drafts(inserted_at DESC)",
        ]

    # ── Store protocol ─────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        """Return all drafts newest-first (``ORDER BY inserted_at DESC``)."""
        return self._load_rows(
            "SELECT data_json FROM drafts ORDER BY inserted_at DESC"
        )

    def save(self, value: Any) -> None:
        """Replace the whole queue: delete-all + bulk-insert in one transaction.

        Each item keeps its existing ``inserted_at`` if present; absent ones get
        a current epoch-millisecond value. To preserve the incoming list order
        (newest-first by convention) when items share/lack timestamps, a small
        descending offset is applied so ``load()``'s ``inserted_at DESC`` yields
        the same order it was saved in.
        """
        drafts = value if isinstance(value, list) else []
        rows: list[tuple[Any, ...]] = []
        n = len(drafts)
        base = _now_ms()
        for idx, draft in enumerate(drafts):
            draft = draft if isinstance(draft, dict) else {}
            inserted_at = draft.get("inserted_at")
            if not isinstance(inserted_at, int):
                # Higher value = earlier in the list (newest-first preserved).
                inserted_at = base + (n - idx)
            rows.append(
                (
                    draft.get("id"),
                    draft.get("campaign_id"),
                    inserted_at,
                    json.dumps(draft, ensure_ascii=False),
                )
            )
        self._replace_all_rows(
            "drafts", ("id", "campaign_id", "inserted_at", "data_json"), rows
        )

    # ── Item-level helpers (public API, preserved from JsonStore) ──────────

    def get_item(self, item_id: str) -> dict | None:
        """Return the matching draft, or ``None``. Read-only."""
        return self._get_one_json(
            "SELECT data_json FROM drafts WHERE id = ?", (item_id,)
        )

    def update_item(self, item_id: str, **fields: Any) -> bool:
        """Locate by id, merge ``fields``, UPDATE. Returns False if absent
        (no write). ``status`` stays inside ``data_json`` (single source)."""
        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT inserted_at, data_json FROM drafts WHERE id = ?",
                        (item_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    inserted_at = row[0]
                    try:
                        draft = json.loads(row[1])
                    except (json.JSONDecodeError, TypeError):
                        draft = {}
                    if not isinstance(draft, dict):
                        draft = {}
                    draft.update(fields)
                    conn.execute(
                        "UPDATE drafts SET campaign_id = ?, data_json = ? "
                        "WHERE id = ?",
                        (
                            draft.get("campaign_id"),
                            json.dumps(draft, ensure_ascii=False),
                            item_id,
                        ),
                    )
                    _ = inserted_at  # ordering column unchanged on update
                    return True

            return _retry_sqlite(_op)

    def delete_item(self, item_id: str) -> bool:
        """Remove the matching draft. Returns False if absent."""
        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    cur = conn.execute(
                        "DELETE FROM drafts WHERE id = ?", (item_id,)
                    )
                    return cur.rowcount > 0

            return _retry_sqlite(_op)

    def insert_first(self, item: dict) -> list[dict]:
        """Head-insert (legacy ``items.insert(0, item)``): newest-first.

        ``inserted_at = int(time.time() * 1000)`` makes this draft sort to the
        top via ``load()``'s ``ORDER BY inserted_at DESC``. Returns the full
        list (newest-first) to match the legacy ``update()`` return contract.
        """
        with self._lock:
            inserted_at = _now_ms()
            item = dict(item)

            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO drafts (id, campaign_id, "
                        "inserted_at, data_json) VALUES (?, ?, ?, ?)",
                        (
                            item.get("id"),
                            item.get("campaign_id"),
                            inserted_at,
                            json.dumps(item, ensure_ascii=False),
                        ),
                    )

            _retry_sqlite(_op)
            return self.load()

    def get_by_campaign_id(self, campaign_id: str) -> list[dict[str, Any]]:
        """Return all drafts whose ``campaign_id`` matches (indexed WHERE).

        Read-only. Returns empty list when no drafts match or the store is
        empty. Preserves newest-first ordering.
        """
        return self._load_rows(
            "SELECT data_json FROM drafts WHERE campaign_id = ? "
            "ORDER BY inserted_at DESC",
            (campaign_id,),
        )

    def bulk_delete(self, ids: list[str]) -> int:
        """Delete multiple drafts by id. Returns count actually removed."""
        if not ids:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in ids)

            def _op() -> int:
                with self._db.connect() as conn:
                    cur = conn.execute(
                        f"DELETE FROM drafts WHERE id IN ({placeholders})",
                        tuple(ids),
                    )
                    return cur.rowcount

            return _retry_sqlite(_op)

    def bulk_update(self, ids: list[str], **fields: Any) -> int:
        """Merge ``fields`` into every draft whose id is in ``ids``.
        Returns count actually mutated."""
        if not ids or not fields:
            return 0
        with self._lock:
            def _op() -> int:
                n = 0
                with self._db.connect() as conn:
                    for item_id in ids:
                        row = conn.execute(
                            "SELECT data_json FROM drafts WHERE id = ?",
                            (item_id,),
                        ).fetchone()
                        if row is None:
                            continue
                        try:
                            draft = json.loads(row[0])
                        except (json.JSONDecodeError, TypeError):
                            draft = {}
                        if not isinstance(draft, dict):
                            draft = {}
                        draft.update(fields)
                        conn.execute(
                            "UPDATE drafts SET campaign_id = ?, data_json = ? "
                            "WHERE id = ?",
                            (
                                draft.get("campaign_id"),
                                json.dumps(draft, ensure_ascii=False),
                                item_id,
                            ),
                        )
                        n += 1
                return n

            return _retry_sqlite(_op)

    def bulk_publish_now(
        self,
        ids: list[str],
        publish_fn: Callable[[dict], dict],
    ) -> dict:
        """Call ``publish_fn`` for each draft id, update status, return summary.

        Unknown ids are silently skipped. ``publish_fn`` must return a dict with
        at least ``{"ok": bool}``; optionally ``{"error": str}`` on failure.
        Exceptions from ``publish_fn`` are caught and reported as failures (no
        re-raise) — the loop continues for remaining items. Each ``update_item``
        is now a targeted SQL UPDATE.
        """
        published = 0
        failed = 0
        errors: list[str] = []
        for item_id in ids:
            draft = self.get_item(item_id)
            if draft is None:
                continue
            try:
                result = publish_fn(draft)
                if result.get("ok"):
                    self.update_item(item_id, status="published")
                    published += 1
                else:
                    err_msg = result.get("error") or "unknown error"
                    self.update_item(item_id, status="failed", error=err_msg)
                    failed += 1
                    errors.append(f"{item_id}: {err_msg}")
            except Exception as exc:  # noqa: BLE001
                err_msg = str(exc)
                self.update_item(item_id, status="failed", error=err_msg)
                failed += 1
                errors.append(f"{item_id}: {err_msg}")
        return {"published": published, "failed": failed, "errors": errors}


# Backward-compat alias: existing call sites / tests import ``DraftsStore``.
DraftsStore = DraftsSqliteStore
