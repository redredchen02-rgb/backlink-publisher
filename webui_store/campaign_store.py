"""CampaignStore — campaign-level state persistence for batch operations.

Follows the same JSON-file pattern as ``DraftsStore``: a single JSON file
holds a list of campaign dicts.  Thread safety via ``JsonStore.update``.

Plan 2026-06-02-001 U1.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import JsonStore

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


# ── CampaignStore ─────────────────────────────────────────────────────

class CampaignStore(JsonStore):
    """Persists a list of campaign dicts in a single JSON file.

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
            "result_summary": {
                "total_seeds": int,
                "successful_seeds": int,
                "failed_seeds": int,
                "total_drafts": int,
                "platform_breakdown": {str: {"success": int, "failed": int}},
            } | None,
        }

    Thread safety: inherited from ``JsonStore.update`` (per-store lock).
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path, default_factory=list)

    # ── Public API ────────────────────────────────────────────────────

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

        self.update(lambda items: [*items, campaign])
        return campaign_id

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        """Return the campaign dict, or ``None`` if not found."""
        for c in self.load():
            if c.get("campaign_id") == campaign_id:
                return c
        return None

    def update_status(
        self, campaign_id: str, **updates: Any,
    ) -> bool:
        """Update campaign-level fields for the matching campaign.

        Accepted keyword arguments (at least one required):

        - ``status`` — validated against ``_CAMPAIGN_STATUS_VALUES``
        - ``progress_pct`` — float 0-100 (auto-clamped)
        - ``result_summary`` — dict or ``None``
        - Any other key is stored verbatim (future-proof).

        Returns ``True`` if the campaign was found and updated.
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

        found = False

        def _fn(items: list[dict]) -> list[dict]:
            nonlocal found
            for c in items:
                if c.get("campaign_id") == campaign_id:
                    c.update(updates)
                    found = True
                    break
            return items

        self.update(_fn)
        return found

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

        Returns ``True`` if the campaign + seed were found and updated.
        """
        if not updates:
            return False

        _status = updates.get("status")
        if _status is not None:
            _validate_status(_status, _SEED_STATUS_VALUES, "seed status")

        found = False

        def _fn(items: list[dict]) -> list[dict]:
            nonlocal found
            for c in items:
                if c.get("campaign_id") != campaign_id:
                    continue
                for seed in c.get("seeds", []):
                    if seed.get("seed_index") != seed_index:
                        continue
                    seed.update(updates)
                    found = True
                    break
                if found:
                    # Recalculate progress from all seeds.
                    seeds = c.get("seeds", [])
                    done = sum(
                        1 for s in seeds
                        if s.get("status") in ("success", "failed", "skipped")
                    )
                    c["progress_pct"] = (
                        (done / len(seeds)) * 100.0 if seeds else 0.0
                    )
                    c["updated_at"] = _now_iso()
                    break
            return items

        self.update(_fn)
        return found

    def list(self) -> list[dict[str, Any]]:
        """Return all campaigns, sorted by ``created_at`` descending."""
        items = self.load()
        return sorted(
            items,
            key=lambda c: c.get("created_at", ""),
            reverse=True,
        )
