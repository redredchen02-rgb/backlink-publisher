"""OptimizationState — persistent read/write for ``optimization_state.json``.

Thread-safe, atomic-write persistence for dispatch-weight state, per-platform
statistics, and rule configuration. Designed to live alongside ``config.toml``
without modifying it.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, cast

from .models import _upgrade_v1_to_v2, default_state
from backlink_publisher.config.loader import _config_dir

logger = logging.getLogger(__name__)


def _resolve_data_dir() -> Path:
    """Resolve the data directory for ``optimization_state.json``."""
    return _config_dir()


class OptimizationState:
    """Read/write persistent optimization state.

    Thread-safe for concurrent reads; writes are serialised via a
    ``threading.Lock``. Atomic write via tempfile + rename prevents
    partial-write corruption.

    Usage::

        state = OptimizationState()
        data = state.load()
        w = state.get_weight("blogger", default=1.0)
        state.set_weight("blogger", 0.5, rule="canary_drift",
                          reason="forward_path_drift")
        state.update_stats("blogger", {"alive_count": 8})
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._data_dir = Path(data_dir) if data_dir else _resolve_data_dir()
        self._path = self._data_dir / "optimization_state.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load state from disk.

        Returns the default empty state if the file does not exist or is
        corrupt (logs a warning on corruption).
        """
        if not self._path.exists():
            return default_state()

        try:
            raw = self._path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
            # Ensure the 'version' key is present (schema guard)
            if "version" not in data:
                logger.warning(
                    "optimization_state.json missing 'version' key — "
                    "treating as corrupt, returning defaults"
                )
                return default_state()
            if data.get("version") == 1:
                logger.info(
                    "Upgrading optimization state from v1 to v2 in-memory"
                )
                data = _upgrade_v1_to_v2(data)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load optimization_state.json (%s) — "
                "returning default state",
                exc,
            )
            return default_state()

    def save(self, state: dict[str, Any]) -> None:
        """Atomically write state to disk.

        Uses tempfile + rename to prevent partial writes.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(state, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="optimization_state_",
            dir=str(self._data_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, str(self._path))
        except BaseException:
            # Clean up the temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_weight(
        self,
        adapter_name: str,
        default: float = 1.0,
        language: str = "default",
    ) -> float:
        """Return the current dynamic weight for *adapter_name*.

        When *language* is not ``"default"`` and the language-specific
        namespace has no entry for *adapter_name*, falls back to the
        ``"default"`` namespace.

        Returns *default* when no entry exists in either namespace.
        """
        data = self.load()
        weights = data.get("weights", {})
        # Primary: requested language namespace
        lang_space = weights.get(language, {})
        entry = lang_space.get(adapter_name)
        if entry is not None:
            return float(entry.get("current", default))
        # Fallback: "default" language (when not already default)
        if language != "default":
            def_space = weights.get("default", {})
            entry = def_space.get(adapter_name)
            if entry is not None:
                return float(entry.get("current", default))
        return default

    def set_weight(
        self,
        adapter_name: str,
        weight: float,
        rule: str,
        reason: str,
        force: bool = False,
        intentional_zero: bool = False,
        language: str = "default",
    ) -> None:
        """Set the current dynamic weight for *adapter_name*.

        Records an adjustment entry with rule name, timestamp, and reason.
        Thread-safe via internal lock.

        When *force* is ``False`` (default) and the platform has a
        ``locked: true`` flag (set by a manual override), the call is a
        silent no-op so automated rules never overwrite operator choices.
        Pass ``force=True`` only from the manual-override WebUI route.

        *intentional_zero* marks this weight as deliberately set to 0.0 by
        a rule (e.g. canary_drift suppression), so ``dispatch_weight()``
        can distinguish it from an uninitialised/legacy 0 and skip the
        defensive floor clamp.
        """
        with self._lock:
            data = self.load()
            lang_weights = data.setdefault("weights", {}).setdefault(language, {})

            existing = lang_weights.get(adapter_name, {})
            if not force and existing.get("locked", False):
                logger.info(
                    "set_weight: skipping locked platform '%s' (rule=%s) — "
                    "manual override in effect",
                    adapter_name, rule,
                )
                return

            from .models import now_iso

            ts = now_iso()
            if adapter_name in lang_weights:
                entry = lang_weights[adapter_name]
                old_current = entry.get("current", entry.get("base", 1.0))
                adjustments = entry.setdefault("adjustments", [])
            else:
                old_current = 1.0
                adjustments = []
                data.setdefault("stats", {})

            multiplier = weight / old_current if old_current != 0 else 0.0

            locked_flag = existing.get("locked", False)

            lang_weights[adapter_name] = {
                "base": lang_weights.get(adapter_name, {}).get("base", old_current),
                "current": weight,
                "locked": locked_flag,
                "intentional_zero": intentional_zero,
                "updated_at": ts,
                "adjustments": adjustments
                + [
                    {
                        "rule": rule,
                        "applied_at": ts,
                        "multiplier": round(multiplier, 4),
                        "reason": reason,
                    }
                ],
            }
            self.save(data)

    def lock_weight(
        self,
        adapter_name: str,
        locked: bool = True,
        language: str = "default",
    ) -> None:
        """Set or clear the manual-override lock for *adapter_name*.

        A locked platform is skipped by automated rules (``set_weight``
        with ``force=False``).  Use ``locked=False`` to unlock and let
        rules manage the weight again.

        *language* scopes the lock to a specific language namespace.
        """
        with self._lock:
            data = self.load()
            lang_weights = data.setdefault("weights", {}).setdefault(language, {})
            entry = lang_weights.setdefault(adapter_name, {})
            entry["locked"] = locked
            self.save(data)

    def update_stats(
        self,
        adapter_name: str,
        stats_update: dict[str, Any],
        language: str = "default",
    ) -> None:
        """Merge *stats_update* into the per-platform stats for *adapter_name*.

        Existing keys are overwritten; new keys are added. Thread-safe.
        *language* scopes the stats to a specific language namespace.
        """
        with self._lock:
            data = self.load()
            lang_stats = data.setdefault("stats", {}).setdefault(language, {})
            existing = lang_stats.setdefault(adapter_name, {})
            existing.update(stats_update)
            self.save(data)

    def get_rules_config(self) -> dict[str, Any]:
        """Return the rules configuration section.

        Returns an empty dict when no rules config exists (callers should
        provide their own defaults).
        """
        data = self.load()
        return cast(dict[str, Any], data.get("rules", {}))

    def reset_weights(self) -> None:
        """Clear all dynamic weights and adjustments.

        Per-platform statistics are preserved (kept for future reference).
        """
        with self._lock:
            data = self.load()
            data["weights"] = {}
            self.save(data)

    def to_summary(self, language: str = "default") -> dict[str, Any]:
        """Return a compact summary for display (``show-optimization-state``).

        Omits the full adjustment history; each platform gets:
        - base, current, delta (percentage), adjustment count, and stat totals.
        *language* selects the language namespace to summarise.
        """
        data = self.load()
        weights = data.get("weights", {}).get(language, {})
        stats = data.get("stats", {}).get(language, {})
        summary: dict[str, Any] = {
            "platforms": [],
            "last_updated": None,
        }
        latest_ts: str | None = None
        for name, entry in weights.items():
            base = float(entry.get("base", 1.0))
            current = float(entry.get("current", base))
            adj_count = len(entry.get("adjustments", []))
            delta_pct = (
                round((current - base) / base * 100, 1) if base != 0 else 0.0
            )
            plat_stats = stats.get(name, {})
            summary["platforms"].append(
                {
                    "name": name,
                    "base": base,
                    "current": current,
                    "locked": entry.get("locked", False),
                    "delta_pct": delta_pct,
                    "adjustment_count": adj_count,
                    "updated_at": entry.get("updated_at"),
                    "stats": {
                        "total_published": plat_stats.get("total_published", 0),
                        "alive_count": plat_stats.get("alive_count", 0),
                        "dofollow_count": plat_stats.get("dofollow_count", 0),
                        "drift_count": plat_stats.get("drift_count", 0),
                    },
                }
            )
            ts = entry.get("updated_at")
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts = ts
        summary["last_updated"] = latest_ts
        return summary

    @property
    def path(self) -> Path:
        """Return the resolved path to ``optimization_state.json``."""
        return self._path
