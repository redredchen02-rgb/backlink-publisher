"""Config & cache directory resolution — extracted from ``config/loader`` (P14 A1-A3).

Moved out of ``config/loader`` so ``_util`` modules can resolve config/cache dirs
without importing from a domain package. ``config/loader`` re-exports these for
backward compat. The test monkeypatch target
``backlink_publisher.config._config_dir`` is preserved via re-export through
``config/__init__``.
"""

from __future__ import annotations

import os
from pathlib import Path


_SANDBOX_SENTINEL = "BACKLINK_PUBLISHER_TEST_SANDBOX"
_FAIL_CLOSED_MSG = (
    "{override_key} is unset but {sentinel} is set — the test harness "
    "is active without a sandboxed {desc} directory. "
    "This usually means a subprocess was spawned without propagating the "
    "override env var. Fix: pass {override_key} to the child process, or "
    "unset {sentinel} if you are not running the test suite."
)


def _config_dir() -> Path:
    """Resolve the config directory.

    Honors ``BACKLINK_PUBLISHER_CONFIG_DIR`` when set so tests, CI, and
    containers can point at an isolated directory without touching the
    operator's real ``~/.config/backlink-publisher/``. Falls back to
    platform defaults otherwise.

    **Test-only fail-closed branch:** if the sentinel
    ``BACKLINK_PUBLISHER_TEST_SANDBOX`` is set but no override is configured,
    the call raises ``RuntimeError`` rather than silently resolving to the
    operator's real home. This catches subprocess spawns inside the test
    suite that forgot to propagate ``BACKLINK_PUBLISHER_CONFIG_DIR``.
    Production code is unaffected (the sentinel is never set outside tests).
    """
    override = os.environ.get("BACKLINK_PUBLISHER_CONFIG_DIR")
    if override:
        return Path(override)
    # Fail-closed in test-sandbox mode: no override + sentinel set → raise.
    if os.environ.get(_SANDBOX_SENTINEL):
        raise RuntimeError(
            _FAIL_CLOSED_MSG.format(
                override_key="BACKLINK_PUBLISHER_CONFIG_DIR",
                sentinel=_SANDBOX_SENTINEL,
                desc="config",
            )
        )
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "backlink-publisher"


def _resolve_config_dir() -> Path:
    """Indirect lookup so test monkeypatch on
    ``backlink_publisher.config._config_dir`` intercepts even when called
    from inside loader.py (where the local ``_config_dir`` would otherwise
    be a module-internal globals lookup, missed by the package-level patch).
    Kept in ``_util.paths``; ``config/loader`` imports it from here."""
    from backlink_publisher.config import _config_dir as _cd

    return _cd()


def _cache_dir() -> Path:
    """Resolve the cache directory.

    Honors ``BACKLINK_PUBLISHER_CACHE_DIR`` for the same reasons as
    ``_config_dir`` — keeps ``~/.cache/backlink-publisher/`` (checkpoints,
    anchor profiles) untouched during tests.

    **Test-only fail-closed branch:** mirrors ``_config_dir()`` — raises when
    the sentinel is set but no cache override is configured.
    """
    override = os.environ.get("BACKLINK_PUBLISHER_CACHE_DIR")
    if override:
        return Path(override)
    # Fail-closed in test-sandbox mode.
    if os.environ.get(_SANDBOX_SENTINEL):
        raise RuntimeError(
            _FAIL_CLOSED_MSG.format(
                override_key="BACKLINK_PUBLISHER_CACHE_DIR",
                sentinel=_SANDBOX_SENTINEL,
                desc="cache",
            )
        )
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path.home() / ".cache"
    return base / "backlink-publisher"
