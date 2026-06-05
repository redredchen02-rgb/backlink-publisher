"""KeepaliveRunState — cycle state and per-target retry limit store.

Persistent JSON store at ``~/.backlink-publisher/keepalive_run_state.json``.
Thread-safe; atomic-write via tempfile + rename (same pattern as OptimizationState).

Schema (version 1)::

    {
      "version": 1,
      "last_run_at": "ISO8601",
      "last_cycle_summary": {
        "gaps_found": 3, "published": 2, "reverified_alive": 1,
        "reverified_dead": 1, "exhausted_skipped": 0
      },
      "retry_counts": {
        "https://example.com/page": {
          "attempts": 2,
          "last_attempt_at": "ISO8601",
          "platforms_tried": ["blogger"],
          "last_outcome": "reverify_dead"
        }
      }
    }
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from backlink_publisher.config.loader import _config_dir

logger = logging.getLogger(__name__)

#: Default max republish+reverify attempts per target URL before marking exhausted.
_DEFAULT_MAX_RETRY = 3

_ENV_MAX_RETRY = "KEEPALIVE_MAX_RETRY"


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "last_run_at": None,
        "last_cycle_summary": {},
        "retry_counts": {},
    }


class KeepaliveRunState:
    """Persistent cycle state and per-target retry tracking.

    Usage::

        state = KeepaliveRunState()
        if state.is_exhausted("https://example.com/page"):
            skip...
        state.record_attempt("https://example.com/page", "blogger", "reverify_dead")
        state.update_cycle_summary({...})
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._data_dir = Path(data_dir) if data_dir else _config_dir()
        self._path = self._data_dir / "keepalive_run_state.json"

    @property
    def MAX_RETRY(self) -> int:
        try:
            return int(os.environ.get(_ENV_MAX_RETRY, _DEFAULT_MAX_RETRY))
        except (ValueError, TypeError):
            return _DEFAULT_MAX_RETRY

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load state; return defaults if missing or corrupt."""
        if not self._path.exists():
            return _default_state()
        try:
            raw = self._path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
            if "version" not in data:
                logger.warning(
                    "keepalive_run_state.json missing 'version' — returning defaults"
                )
                return _default_state()
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load keepalive_run_state.json (%s) — returning defaults",
                exc,
            )
            return _default_state()

    def save(self, state: dict[str, Any]) -> None:
        """Atomically write state to disk."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(state, indent=2, ensure_ascii=False)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="keepalive_run_state_",
            dir=str(self._data_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, str(self._path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_exhausted(self, target_url: str) -> bool:
        """Return True if ``target_url`` has >= MAX_RETRY failed attempts."""
        data = self.load()
        entry = data.get("retry_counts", {}).get(target_url, {})
        return int(entry.get("attempts", 0)) >= self.MAX_RETRY

    def record_attempt(
        self, target_url: str, platform: str, outcome: str
    ) -> None:
        """Increment attempt count and record platform/outcome.

        Only ``link_stripped`` and ``host_gone`` outcomes increment ``attempts``.
        ``probe_error`` does NOT increment (CDN propagation delay; indeterminate).
        """
        with self._lock:
            data = self.load()
            retry_counts = data.setdefault("retry_counts", {})
            entry = retry_counts.setdefault(target_url, {
                "attempts": 0,
                "last_attempt_at": None,
                "platforms_tried": [],
                "last_outcome": None,
            })
            from datetime import datetime, timezone
            entry["last_attempt_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            entry["last_outcome"] = outcome
            if platform not in entry.get("platforms_tried", []):
                entry.setdefault("platforms_tried", []).append(platform)
            # Only definitive-dead verdicts count toward exhaustion.
            if outcome in ("link_stripped", "host_gone", "reverify_dead"):
                entry["attempts"] = entry.get("attempts", 0) + 1
            self.save(data)

    def reset_exhausted(self, target_url: str) -> None:
        """Remove ``target_url`` from retry_counts (operator reset)."""
        with self._lock:
            data = self.load()
            data.get("retry_counts", {}).pop(target_url, None)
            self.save(data)

    def update_cycle_summary(self, summary: dict[str, Any]) -> None:
        """Persist last_run_at and cycle summary."""
        with self._lock:
            from datetime import datetime, timezone
            data = self.load()
            data["last_run_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            data["last_cycle_summary"] = summary
            self.save(data)
