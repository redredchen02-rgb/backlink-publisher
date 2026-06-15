"""CampaignSqliteStore — campaign-level state persistence backed by webui.db.

Replaces the ``campaigns.json`` JsonStore with a proper row table keyed by
campaign id, with mirrored ``mode`` / ``status`` / ``created_at`` /
``updated_at`` / ``progress_pct`` columns (for querying + ordering) plus a
``seeds_json`` blob (nested seed sub-records) and a ``data_json`` blob that
holds the *whole* campaign dict (the source of truth on load).

The public API (``create`` / ``get`` / ``update_status`` /
``update_seed_status`` / ``list`` plus inherited ``load`` / ``save`` /
``update``) is preserved exactly, including names, signatures, validation,
return values, and the ``created_at`` DESC ordering of ``list()`` / ``load()``.

``update_seed_status`` uses a single connection/transaction (SELECT → mutate →
recompute progress → UPDATE) — it must NOT open a nested connection inside the
transaction (WAL nested-connection deadlock rule).

Startup migration: on first boot after this code is deployed, the existing
``campaigns.json`` is imported and the original file is renamed to
``.migrated``. A sentinel file prevents double-import on subsequent boots.

Plan: docs/plans/2026-06-03-008-refactor-webui-store-sqlite-unification-plan.md
Unit 7.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import BaseSqliteStore

_SENTINEL_NAME = ".webui-campaign-migrated-v1"
_JSON_FILENAME = "campaigns.json"

# ── Schema helpers ────────────────────────────────────────────────────

_CAMPAIGN_SCHEMA_VERSION = 1

_SEED_STATUS_VALUES = frozenset({
    "idle", "processing", "success", "failed", "skipped",
})

_CAMPAIGN_STATUS_VALUES = frozenset({
    "pending", "running", "draft_review", "completed", "failed",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_campaign_id() -> str:
    return str(uuid.uuid4())


def _validate_status(value: str, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise ValueError(
            f"{label} must be one of {sorted(allowed)}, got {value!r}"
        )


# ── CampaignSqliteStore ───────────────────────────────────────────────

class CampaignSqliteStore(BaseSqliteStore):
    """Row-table store for campaigns, backed by webui.db.

    Schema (per campaign dict)::

        {
            "campaign_id": str,
            "status": "pending" | "running" | "draft_review" | "completed" | "failed",
            "mode": "draft" | "publish",
            "platforms": [str, ...],
            "cap": int | None,
            "created_at": ISO-8601 str,
            "updated_at": ISO-8601 str,
            "seeds": [
                {
                    "seed_index": int,
                    "seed_text": str,
                    "status": "idle" | "processing" | "success" | "failed" | "skipped",
                    "error": str | None,
                    "draft_count": int,
                    "published_count": int,
                },
            ],
            "progress_pct": float,   # 0-100
            "result_summary": {...} | None,
        }

    Table::

        campaigns (
          id           TEXT PRIMARY KEY,
          mode         TEXT,
          status       TEXT NOT NULL,
          created_at   TEXT,
          updated_at   TEXT,
          progress_pct REAL,
          seeds_json   TEXT,
          data_json    TEXT NOT NULL
        )
        CREATE INDEX campaigns_created ON campaigns(created_at DESC)

    The campaign dict's primary key field is ``campaign_id``; it is mapped to
    the ``id`` column. ``load()`` reconstructs each campaign from ``data_json``
    (the source of truth) — the mirrored columns exist only for querying and
    ``created_at`` DESC ordering.

    Accepts either a :class:`WebUIDatabase` (the migrated factory path) or a
    plain :class:`~pathlib.Path` (backward compat for callers/tests that still
    pass a file path) — in the latter case a ``WebUIDatabase`` is wrapped
    around it.
    """

    _value_type = list
    _json_filename = _JSON_FILENAME
    _sentinel_name = _SENTINEL_NAME

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS campaigns ("
            "id TEXT PRIMARY KEY, "
            "mode TEXT, "
            "status TEXT NOT NULL, "
            "created_at TEXT, "
            "updated_at TEXT, "
            "progress_pct REAL, "
            "seeds_json TEXT, "
            "data_json TEXT NOT NULL)"
        )

    def _indices_sql(self) -> list[str]:
        return [
            "CREATE INDEX IF NOT EXISTS campaigns_created "
            "ON campaigns(created_at DESC)"
        ]

    # ── Store protocol ─────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        """Return all campaigns sorted by ``created_at`` DESC.

        Reconstructed from ``data_json`` (the source of truth).
        """
        return self._load_rows(
            "SELECT data_json FROM campaigns ORDER BY created_at DESC"
        )

    def save(self, value: Any) -> None:
        """Replace the whole table: delete-all + bulk-insert in one transaction."""
        campaigns = value if isinstance(value, list) else []
        rows: list[tuple[Any, ...]] = []
        for c in campaigns:
            c = c if isinstance(c, dict) else {}
            seeds = c.get("seeds", [])
            rows.append(
                (
                    c.get("campaign_id"),
                    c.get("mode"),
                    c.get("status"),
                    c.get("created_at"),
                    c.get("updated_at"),
                    c.get("progress_pct"),
                    json.dumps(seeds, ensure_ascii=False),
                    json.dumps(c, ensure_ascii=False),
                )
            )

        self._replace_all_rows(
            "campaigns",
            (
                "id", "mode", "status", "created_at", "updated_at",
                "progress_pct", "seeds_json", "data_json",
            ),
            rows,
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def create(
        self,
        *,
        mode: str,
        platforms: list[str],
        seeds: list[dict[str, Any]],
        cap: int | None = None,
    ) -> str:
        """Create a new campaign and return its ``campaign_id``.

        ``seeds`` must be a non-empty list of dicts, each with at least a
        ``"seed_text"`` key.  At least one platform is required.
        """
        if not seeds:
            raise ValueError("At least one seed is required")
        if not platforms:
            raise ValueError("At least one platform is required")
        if mode not in ("draft", "publish"):
            raise ValueError(f"mode must be 'draft' or 'publish', got {mode!r}")

        campaign_id = _new_campaign_id()
        now = _now_iso()

        campaign: dict[str, Any] = {
            "campaign_id": campaign_id,
            "status": "pending",
            "mode": mode,
            "platforms": list(platforms),
            "cap": cap,
            "_schema_version": _CAMPAIGN_SCHEMA_VERSION,
            "created_at": now,
            "updated_at": now,
            "seeds": [
                {
                    "seed_index": i,
                    "seed_text": s["seed_text"],
                    "status": "idle",
                    "error": None,
                    "draft_count": 0,
                    "published_count": 0,
                }
                for i, s in enumerate(seeds)
            ],
            "progress_pct": 0.0,
            "result_summary": None,
        }

        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT INTO campaigns (id, mode, status, created_at, "
                        "updated_at, progress_pct, seeds_json, data_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            campaign_id,
                            campaign["mode"],
                            campaign["status"],
                            campaign["created_at"],
                            campaign["updated_at"],
                            campaign["progress_pct"],
                            json.dumps(campaign["seeds"], ensure_ascii=False),
                            json.dumps(campaign, ensure_ascii=False),
                        ),
                    )

            _retry_sqlite(_op)
        return campaign_id

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        """Return the campaign dict, or ``None`` if not found. Read-only."""
        return self._get_one_json(
            "SELECT data_json FROM campaigns WHERE id = ?", (campaign_id,)
        )

    def update_status(
        self, campaign_id: str, **updates: Any,
    ) -> bool:
        """Update campaign-level fields for the matching campaign.

        Accepted keyword arguments (at least one required):

        - ``status`` — validated against ``_CAMPAIGN_STATUS_VALUES``
        - ``progress_pct`` — float 0-100 (auto-clamped)
        - ``result_summary`` — dict or ``None``
        - Any other key is stored verbatim (future-proof).

        Targeted SELECT-merge-UPDATE in one transaction. Returns ``True`` if
        the campaign was found and updated.
        """
        if not updates:
            return False

        _status = updates.get("status")
        if _status is not None:
            _validate_status(_status, _CAMPAIGN_STATUS_VALUES, "campaign status")

        _pct = updates.get("progress_pct")
        if _pct is not None:
            updates["progress_pct"] = max(0.0, min(100.0, float(_pct)))

        updates["updated_at"] = _now_iso()

        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT data_json FROM campaigns WHERE id = ?",
                        (campaign_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    try:
                        campaign = json.loads(row[0])
                    except (json.JSONDecodeError, TypeError):
                        campaign = {}
                    if not isinstance(campaign, dict):
                        campaign = {}
                    campaign.update(updates)
                    conn.execute(
                        "UPDATE campaigns SET mode = ?, status = ?, "
                        "created_at = ?, updated_at = ?, progress_pct = ?, "
                        "seeds_json = ?, data_json = ? WHERE id = ?",
                        (
                            campaign.get("mode"),
                            campaign.get("status"),
                            campaign.get("created_at"),
                            campaign.get("updated_at"),
                            campaign.get("progress_pct"),
                            json.dumps(
                                campaign.get("seeds", []), ensure_ascii=False
                            ),
                            json.dumps(campaign, ensure_ascii=False),
                            campaign_id,
                        ),
                    )
                    return True

            return _retry_sqlite(_op)

    def update_seed_status(
        self, campaign_id: str, seed_index: int, **updates: Any,
    ) -> bool:
        """Update a single seed within a campaign.

        Accepted keyword arguments (at least one required):

        - ``status`` — validated against ``_SEED_STATUS_VALUES``
        - ``error`` — str or ``None``
        - ``draft_count`` — int
        - ``published_count`` — int

        After updating the seed, ``progress_pct`` is automatically
        recalculated from all seeds.

        Single connection/transaction: SELECT → mutate → recompute → UPDATE.
        No nested connection is opened (WAL deadlock rule). Returns ``True`` if
        the campaign + seed were found and updated.
        """
        if not updates:
            return False

        _status = updates.get("status")
        if _status is not None:
            _validate_status(_status, _SEED_STATUS_VALUES, "seed status")

        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT data_json FROM campaigns WHERE id = ?",
                        (campaign_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    try:
                        campaign = json.loads(row[0])
                    except (json.JSONDecodeError, TypeError):
                        return False
                    if not isinstance(campaign, dict):
                        return False

                    seeds = campaign.get("seeds", [])
                    found = False
                    for seed in seeds:
                        if seed.get("seed_index") != seed_index:
                            continue
                        seed.update(updates)
                        found = True
                        break
                    if not found:
                        return False

                    # Recalculate progress from all seeds.
                    done = sum(
                        1 for s in seeds
                        if s.get("status") in ("success", "failed", "skipped")
                    )
                    campaign["progress_pct"] = (
                        (done / len(seeds)) * 100.0 if seeds else 0.0
                    )
                    campaign["updated_at"] = _now_iso()

                    conn.execute(
                        "UPDATE campaigns SET seeds_json = ?, progress_pct = ?, "
                        "updated_at = ?, data_json = ? WHERE id = ?",
                        (
                            json.dumps(seeds, ensure_ascii=False),
                            campaign["progress_pct"],
                            campaign["updated_at"],
                            json.dumps(campaign, ensure_ascii=False),
                            campaign_id,
                        ),
                    )
                    return True

            return _retry_sqlite(_op)

    def list(self) -> list[dict[str, Any]]:
        """Return all campaigns, sorted by ``created_at`` descending.

        Semantically explicit alias of ``load()`` (which already orders by
        ``created_at`` DESC).
        """
        return self.load()


# Backward-compat alias: existing call sites / tests import ``CampaignStore``.
CampaignStore = CampaignSqliteStore
