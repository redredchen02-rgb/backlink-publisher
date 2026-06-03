"""Per-channel circuit breaker — Plan 2026-05-28-001 Unit 3.

Extended for Stage 1 (Plan 2026-05-28-001):
- Half-open state support for testing service recovery
- Extended to all adapters (not just browser-tier)
- Multi-error-type trip conditions

State is persisted in ``<config_dir>/publish-circuit-state.json`` and
protected by an ``fcntl.LOCK_EX`` flock on a sibling ``.lock`` file,
matching the ``velog_graphql._acquire_lock`` pattern.

Fail-CLOSED contract: any read failure (JSONDecodeError, OSError, etc.)
causes :func:`is_tripped` to return ``True`` — a corrupt state file is
treated as "all channels tripped" until the operator runs
``reset_circuit()``.

Trip condition (v1): :class:`~backlink_publisher._util.errors.AuthExpiredError`
whose message contains ``ban``, ``banned``, or ``suspended`` (case-insensitive).
Plain session-expiry does NOT trip the breaker.

Extended trip conditions (Stage 1):
- Consecutive transient errors (default: 3)
- Rate limit errors (429 responses)
- External service errors (5xx responses)

States:
- closed: normal operation
- open: circuit tripped, requests blocked
- half-open: test mode, limited traffic allowed

Cooldown: ``BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S`` env var (default 300 s).
Half-open trial count: ``BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES`` (default 1).
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher._util.io import atomic_write_json
from backlink_publisher._util.logger import opencli_logger as _log

if TYPE_CHECKING:
    from backlink_publisher.config import Config


_LOCK_TIMEOUT: float = 60.0
_LOCK_POLL_INTERVAL: float = 0.1
_DEFAULT_COOLDOWN_S: int = 300
_DEFAULT_HALF_OPEN_TRIES: int = 1
_DEFAULT_CONSECUTIVE_ERRORS: int = 3

_BAN_SIGNALS: tuple[str, ...] = ("ban", "banned", "suspended")
_TRANSIENT_STATUS_CODES: tuple[int, ...] = (429, 502, 503, 504)

_STATE_FILE = "publish-circuit-state.json"
_LOCK_FILE = "publish-circuit-state.lock"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cooldown_s() -> int:
    try:
        return int(
            os.environ.get("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", _DEFAULT_COOLDOWN_S)
        )
    except (ValueError, TypeError):
        return _DEFAULT_COOLDOWN_S


def _acquire_lock(lock_path: Path) -> int:
    """Open and LOCK_EX *lock_path*, polling up to 60 s.

    Returns the open file descriptor (caller must close + release).
    Raises ExternalServiceError if the lock cannot be acquired within timeout.
    """
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
    raise ExternalServiceError(
        "publish-circuit-state lock held > 60 s; check for stale process"
    )


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
    """Read state file without flock — caller must hold the lock."""
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _write_state_unsafe(state_path: Path, state: dict[str, Any]) -> None:
    """Write state atomically (tmp + ``os.replace``) without flock — caller holds the lock.

    Atomic replace guarantees the lockless :func:`is_tripped` reader never sees a
    torn write, and a crash mid-write cannot leave a corrupt state file — which
    would otherwise fail-CLOSED and block *every* channel until operator reset.
    """
    atomic_write_json(state_path, state)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _half_open_tries() -> int:
    try:
        return int(
            os.environ.get(
                "BACKLINK_PUBLISHER_CIRCUIT_HALF_OPEN_TRIES", _DEFAULT_HALF_OPEN_TRIES
            )
        )
    except (ValueError, TypeError):
        return _DEFAULT_HALF_OPEN_TRIES


def _consecutive_errors_threshold() -> int:
    try:
        return int(
            os.environ.get(
                "BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS",
                _DEFAULT_CONSECUTIVE_ERRORS,
            )
        )
    except (ValueError, TypeError):
        return _DEFAULT_CONSECUTIVE_ERRORS


def _get_state(platform: str, config: Config) -> dict[str, Any]:
    """Get the full state entry for a platform, including state machine fields.

    Fail-CLOSED contract: corrupt state file returns state indicating tripped.
    """
    state_path = _state_path(config)
    if not state_path.exists():
        return {
            "state": CircuitState.CLOSED.value,
            "tripped": False,
            "tripped_at_iso": None,
            "half_open_tries": 0,
            "consecutive_errors": 0,
        }
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        entry = state.get(platform, {})
        return {
            "state": entry.get("state", CircuitState.CLOSED.value),
            "tripped": entry.get("tripped", False),
            "tripped_at_iso": entry.get("tripped_at_iso"),
            "half_open_tries": entry.get("half_open_tries", 0),
            "consecutive_errors": entry.get("consecutive_errors", 0),
        }
    except Exception:
        # Fail-CLOSED: corrupt state file means we should trip
        return {
            "state": CircuitState.OPEN.value,
            "tripped": True,
            "tripped_at_iso": None,
            "half_open_tries": 0,
            "consecutive_errors": 0,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_tripped(platform: str, config: Config) -> bool:
    """Return True if the circuit is open for *platform*.

    Enhanced for Stage 1 (Plan 2026-05-28-001):
    - Supports CLOSED, OPEN, and HALF_OPEN states
    - HALF_OPEN state allows limited traffic after cooldown to test recovery
    - Extended trip conditions: consecutive transient errors, 429/5xx responses

    Fail-CLOSED: any read error (JSONDecodeError, OSError, etc.) returns
    True — a corrupt state file is treated as all channels tripped.
    """
    try:
        state = _get_state(platform, config)
        current_state = state.get("state", CircuitState.CLOSED.value)
        tripped_at_iso = state.get("tripped_at_iso")
        tripped = state.get("tripped", False)

        # HALF_OPEN state: transition automatically after cooldown
        if current_state == CircuitState.HALF_OPEN and tripped_at_iso:
            cooldown = _cooldown_s()
            try:
                tripped_at = datetime.fromisoformat(tripped_at_iso).timestamp()
                if time.time() - tripped_at >= cooldown:
                    _transition_to_half_open(platform, config)
            except (ValueError, TypeError):
                pass
            # In half-open state, we allow a limited number of requests through
            return False

        # OPEN state: check cooldown; also handle fail-CLOSED case (tripped but no timestamp)
        if current_state == CircuitState.OPEN:
            if tripped_at_iso:
                cooldown = _cooldown_s()
                try:
                    tripped_at = datetime.fromisoformat(tripped_at_iso).timestamp()
                    if time.time() - tripped_at >= cooldown:
                        _transition_to_half_open(platform, config)
                        return False
                except (ValueError, TypeError):
                    pass
            # Either we have tripped_at_iso and cooldown hasn't elapsed, or we have
            # a corrupt entry (tripped=True but no timestamp). Either way, trip.
            return True

        return False
    except Exception as exc:
        _log.warn(f"circuit state read error for {platform!r} (fail-CLOSED): {exc}")
        return True


def trip(platform: str, config: Config) -> None:
    """Trip the circuit for *platform* (flock-across-RMW).

    Enhanced to write extended state including state machine and error counters.
    """
    fd = _acquire_lock(_lock_path(config))
    try:
        try:
            state = _read_state_unsafe(_state_path(config))
        except (json.JSONDecodeError, OSError):
            state = {}
        state[platform] = {
            "state": CircuitState.OPEN.value,
            "tripped": True,
            "tripped_at_iso": _now_iso(),
            "half_open_tries": 0,
            "consecutive_errors": 0,
        }
        _write_state_unsafe(_state_path(config), state)
        _log.info(
            {
                "event": "circuit_tripped",
                "platform": platform,
                "tripped_at_iso": state[platform]["tripped_at_iso"],
            }
        )
    finally:
        _release_lock(fd)


def trip_on_error(
    platform: str, config: Config, status_code: int | None = None
) -> None:
    """Trip or increment error count for *platform* based on error type.

    Extended trip logic (Stage 1):
    - 429/5xx status codes: immediate trip
    - Timeout/connection errors: increment error counter, trip at threshold
    """
    fd = _acquire_lock(_lock_path(config))
    try:
        try:
            state = _read_state_unsafe(_state_path(config))
        except (json.JSONDecodeError, OSError):
            state = {}
        entry = state.get(platform, {})
        current_errors = entry.get("consecutive_errors", 0) + 1

        # Trip on rate limit or consecutive error threshold
        should_trip = False
        if status_code is not None and status_code in _TRANSIENT_STATUS_CODES:
            should_trip = True
        elif current_errors >= _consecutive_errors_threshold():
            should_trip = True

        if should_trip:
            state[platform] = {
                "state": CircuitState.OPEN.value,
                "tripped": True,
                "tripped_at_iso": _now_iso(),
                "half_open_tries": 0,
                "consecutive_errors": 0,
            }
            _log.info(
                {
                    "event": "circuit_tripped",
                    "platform": platform,
                    "reason": (
                        f"status_code={status_code}"
                        if status_code
                        else "consecutive_errors"
                    ),
                    "tripped_at_iso": state[platform]["tripped_at_iso"],
                }
            )
        else:
            entry["consecutive_errors"] = current_errors
            entry["state"] = CircuitState.CLOSED.value
            entry["tripped"] = False
            state[platform] = entry
            _log.info(
                {
                    "event": "circuit_error_counted",
                    "platform": platform,
                    "consecutive_errors": current_errors,
                    "threshold": _consecutive_errors_threshold(),
                }
            )
        _write_state_unsafe(_state_path(config), state)
    finally:
        _release_lock(fd)


def record_success(platform: str, config: Config) -> None:
    """Record a successful operation, resetting error counter."""
    fd = _acquire_lock(_lock_path(config))
    try:
        try:
            state = _read_state_unsafe(_state_path(config))
        except (json.JSONDecodeError, OSError):
            state = {}
        entry = state.get(platform, {})
        entry["consecutive_errors"] = 0
        entry["state"] = CircuitState.CLOSED.value
        state[platform] = entry
        _write_state_unsafe(_state_path(config), state)
    finally:
        _release_lock(fd)


def _transition_to_half_open(platform: str, config: Config) -> None:
    """Transition circuit to half-open state (flock-across-RMW)."""
    fd = _acquire_lock(_lock_path(config))
    try:
        try:
            state = _read_state_unsafe(_state_path(config))
        except (json.JSONDecodeError, OSError):
            state = {}
        state[platform] = {
            "state": CircuitState.HALF_OPEN.value,
            "tripped": True,
            "tripped_at_iso": _now_iso(),
            "half_open_tries": 0,
            "consecutive_errors": 0,
        }
        _write_state_unsafe(_state_path(config), state)
        _log.info({"event": "circuit_half_open", "platform": platform})
    finally:
        _release_lock(fd)


def _increment_half_open_try(platform: str, config: Config) -> bool:
    """Increment half-open try counter, return True if still allowed.

    Returns True if the adapter can proceed; False if trial limit reached.
    """
    fd = _acquire_lock(_lock_path(config))
    try:
        try:
            state = _read_state_unsafe(_state_path(config))
        except (json.JSONDecodeError, OSError):
            state = {}
        entry = state.get(platform, {})
        tries = entry.get("half_open_tries", 0) + 1
        max_tries = _half_open_tries()

        if tries > max_tries:
            # Exceeded trials, trip again
            entry["state"] = CircuitState.OPEN.value
            entry["tripped"] = True
            _log.info({"event": "circuit_trip_on_half_open_fail", "platform": platform})
        else:
            entry["half_open_tries"] = tries
        state[platform] = entry
        _write_state_unsafe(_state_path(config), state)
        return tries <= max_tries
    finally:
        _release_lock(fd)


def reset_circuit(platform: str, config: Config) -> None:
    """Reset tripped circuit for *platform* (operator / test use, flock-across-RMW)."""
    fd = _acquire_lock(_lock_path(config))
    try:
        try:
            state = _read_state_unsafe(_state_path(config))
        except (json.JSONDecodeError, OSError):
            state = {}
        state[platform] = {
            "state": CircuitState.CLOSED.value,
            "tripped": False,
            "tripped_at_iso": None,
            "half_open_tries": 0,
            "consecutive_errors": 0,
        }
        _write_state_unsafe(_state_path(config), state)
        _log.info({"event": "circuit_reset", "platform": platform})
    finally:
        _release_lock(fd)


def _auto_reset(platform: str, config: Config) -> None:
    """Best-effort auto-reset after cooldown. Errors are swallowed."""
    try:
        fd = _acquire_lock(_lock_path(config))
        try:
            try:
                state = _read_state_unsafe(_state_path(config))
            except (json.JSONDecodeError, OSError):
                return  # can't read, skip
            entry = state.get(platform, {})
            if not entry.get("tripped"):
                return  # already reset by another process
            # Re-check cooldown inside lock
            tripped_at_iso = entry.get("tripped_at_iso", "")
            try:
                tripped_at = datetime.fromisoformat(tripped_at_iso).timestamp()
            except (ValueError, TypeError):
                return
            if time.time() - tripped_at >= _cooldown_s():
                state[platform] = {"tripped": False, "tripped_at_iso": None}
                _write_state_unsafe(_state_path(config), state)
                _log.info({"event": "circuit_auto_reset", "platform": platform})
        finally:
            _release_lock(fd)
    except Exception:  # noqa: BLE001
        pass


def is_ban_signal(exc: AuthExpiredError) -> bool:
    """True if *exc* carries a ban/suspend signal."""
    msg = str(exc).lower()
    return any(w in msg for w in _BAN_SIGNALS)
