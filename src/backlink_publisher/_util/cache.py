"""Simple TTL cache for read-heavy, write-light data.

Thread-safe, zero-dependency, process-scoped cache. Designed for data that
is read frequently but changes infrequently (e.g. TOML config, JSON state).

Usage::

    # On read
    data = _ttl_cache_get("load_config")
    if data is None:
        data = _expensive_load()
        _ttl_cache_set("load_config", data, ttl=15.0)

    # In tests
    _ttl_cache_clear()
"""

from __future__ import annotations

import threading
import time
from typing import Any

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _ttl_cache_get(key: str) -> Any | None:
    """Return cached *key*, or ``None`` if missing or expired."""
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        now = time.monotonic()
        if now > expires_at:
            del _cache[key]
            return None
        return value


def _ttl_cache_set(key: str, value: Any, ttl: float = 15.0) -> None:
    """Store *value* under *key* with a TTL of *ttl* seconds."""
    with _lock:
        _cache[key] = (time.monotonic() + ttl, value)


def _ttl_cache_clear() -> None:
    """Clear all cached entries (used in tests)."""
    with _lock:
        _cache.clear()


def _ttl_cache_delete(key: str) -> None:
    """Remove a single key from the cache (for targeted invalidation)."""
    with _lock:
        _cache.pop(key, None)
