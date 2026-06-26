"""Cross-process-safe mutable per-platform health state store.

State is persisted in ``<config_dir>/platform-health.json`` and protected by
an ``fcntl.LOCK_EX`` flock on a sibling ``.lock`` file — same pattern as
``publishing/reliability/circuit.py``.

Fail-SAFE contract: any read failure returns safe defaults (consecutive_failures=0,
paused=False) rather than raising — health-state unavailability must never block
a publish run.

Only mutable operator state lives here. Immutable facts (last_success_at,
last_failure_at, last_error_msg) are derived live from EventStore.
"""

from __future__ import annotations

from collections.abc import Callable
from backlink_publisher._compat import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any, cast, TYPE_CHECKING

from backlink_publisher._util.io import atomic_write_json
from backlink_publisher._util.logger import opencli_logger as _log

if TYPE_CHECKING:
    from backlink_publisher.config import Config


_LOCK_TIMEOUT: float = 60.0
_LOCK_POLL_INTERVAL: float = 0.1

_STATE_FILE = "platform-health.json"
_LOCK_FILE = "platform-health.lock"

_SAFE_DEFAULTS: dict[str, Any] = {"consecutive_failures": 0, "paused": False}


def _acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    finally:
        os.umask(old_umask)
    os.chmod(lock_path, 0o600)

    deadline = time.monotonic() + _LOCK_TIMEOUT
    while time.monotonic() < deadline:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            time.sleep(_LOCK_POLL_INTERVAL)

    os.close(fd)
    raise OSError("platform-health lock held > 60 s; check for stale process")


def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except OSError:
        pass


def _state_path(config: Config) -> Path:
    return config.config_dir / _STATE_FILE


def _lock_path(config: Config) -> Path:
    return config.config_dir / _LOCK_FILE


def _read_state_unsafe(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    return cast(dict[str, Any], json.loads(state_path.read_text(encoding="utf-8")))


def _write_state_unsafe(state_path: Path, state: dict[str, Any]) -> None:
    atomic_write_json(state_path, state)


def get(platform: str, config: Config) -> dict[str, Any]:
    """Return mutable health state for *platform* with safe defaults on any error."""
    try:
        state = _read_state_unsafe(_state_path(config))
        entry = state.get(platform, {})
        return {
            "consecutive_failures": int(entry.get("consecutive_failures", 0)),
            "paused": bool(entry.get("paused", False)),
        }
    except Exception as exc:
        _log.warning(f"platform-health: read error for {platform}: {exc}")
        return dict(_SAFE_DEFAULTS)


def update(platform: str, fn: Callable[[dict[str, Any]], dict[str, Any]], config: Config) -> None:
    """Hold flock across read-modify-write for *platform* entry.

    *fn* receives the current entry dict and returns the updated one.
    Any exception from *fn* aborts the write (state unchanged).
    """
    lock_path = _lock_path(config)
    state_path = _state_path(config)
    fd = _acquire_lock(lock_path)
    try:
        state = _read_state_unsafe(state_path)
        entry = state.get(platform, {})
        updated = fn(dict(entry))
        state[platform] = updated
        _write_state_unsafe(state_path, state)
    finally:
        _release_lock(fd)


def set_paused(platform: str, paused: bool, config: Config) -> bool:
    """Set the operator pause flag for *platform*, preserving other state.

    Returns the new paused value. Lock-protected read-modify-write so a
    concurrent failure-counter update is not lost.
    """
    update(platform, lambda e: {**e, "paused": bool(paused)}, config)
    return bool(paused)


def is_paused(platform: str, config: Config) -> bool:
    """Fail-SAFE read of the pause flag (False on any read error)."""
    return cast(bool, get(platform, config)["paused"])
