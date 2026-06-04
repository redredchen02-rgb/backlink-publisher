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
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import SqliteStore, WebUIDatabase

_log = logging.getLogger(__name__)

_SENTINEL_NAME = ".webui-drafts-migrated-v1"
_JSON_FILENAME = "draft-queue.json"


def _now_ms() -> int:
    return int(time.time() * 1000)


class DraftsSqliteStore(SqliteStore):
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

    def __init__(self, db: WebUIDatabase | Path) -> None:
        if not isinstance(db, WebUIDatabase):
            db = WebUIDatabase(Path(db))
        super().__init__(db)
        self._init_table()

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

    def _init_table(self) -> None:
        with self._db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS drafts ("
                "id TEXT PRIMARY KEY, "
                "campaign_id TEXT, "
                "inserted_at INTEGER NOT NULL, "
                "data_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS drafts_campaign "
                "ON drafts(campaign_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS drafts_inserted "
                "ON drafts(inserted_at DESC)"
            )

    # ── Store protocol ─────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        """Return all drafts newest-first (``ORDER BY inserted_at DESC``)."""
        def _op() -> list[tuple[str]]:
            with self._db.connect() as conn:
                return conn.execute(
                    "SELECT data_json FROM drafts ORDER BY inserted_at DESC"
                ).fetchall()

        rows = _retry_sqlite(_op)
        result: list[dict[str, Any]] = []
        for (data_json,) in rows:
            try:
                draft = json.loads(data_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(draft, dict):
                result.append(draft)
        return result

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

        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute("DELETE FROM drafts")
                    if rows:
                        conn.executemany(
                            "INSERT INTO drafts (id, campaign_id, inserted_at, "
                            "data_json) VALUES (?, ?, ?, ?)",
                            rows,
                        )

            _retry_sqlite(_op)

    # ── Item-level helpers (public API, preserved from JsonStore) ──────────

    def get_item(self, item_id: str) -> dict | None:
        """Return the matching draft, or ``None``. Read-only."""
        def _op() -> tuple[str] | None:
            with self._db.connect() as conn:
                return conn.execute(
                    "SELECT data_json FROM drafts WHERE id = ?", (item_id,)
                ).fetchone()

        row = _retry_sqlite(_op)
        if row is None:
            return None
        try:
            draft = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None
        return draft if isinstance(draft, dict) else None

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
        def _op() -> list[tuple[str]]:
            with self._db.connect() as conn:
                return conn.execute(
                    "SELECT data_json FROM drafts WHERE campaign_id = ? "
                    "ORDER BY inserted_at DESC",
                    (campaign_id,),
                ).fetchall()

        rows = _retry_sqlite(_op)
        result: list[dict[str, Any]] = []
        for (data_json,) in rows:
            try:
                draft = json.loads(data_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(draft, dict):
                result.append(draft)
        return result

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

    # ── Startup migration ─────────────────────────────────────────────────

    def migrate_from_json(self, config_dir: Path) -> None:
        """One-shot import from ``draft-queue.json`` if not yet migrated.

        Same load-bearing sequence as the other SqliteStore migrations:
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
        except (json.JSONDecodeError, OSError):
            _log.warning(
                "drafts_store migration: skipping corrupt/unreadable %s",
                json_path,
            )
            return

        self.save(data if isinstance(data, list) else [])

        try:
            json_path.rename(migrated_path)
        except OSError as exc:
            _log.warning("drafts_store migration: rename failed: %s", exc)
            return

        try:
            os.chmod(migrated_path, 0o600)
        except OSError:
            pass

        sentinel.write_text("migrated", encoding="utf-8")


# Backward-compat alias: existing call sites / tests import ``DraftsStore``.
DraftsStore = DraftsSqliteStore
