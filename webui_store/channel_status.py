"""Channel binding status store — Plan 2026-05-19-001 Unit 1.

Tracks each browser-binding channel's lifecycle in
``<config_dir>/channel-status.json``.  Singleton is a ``_LazyStore``
proxy (Plan 2026-05-22 P7 C1) so the backing-file path is only resolved
on first access.
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
import logging
import os
from pathlib import Path
from typing import Any

from backlink_publisher._util.errors import UsageError
from backlink_publisher.cli._bind.channels import CHANNELS
from backlink_publisher.config.loader import _config_dir
from backlink_publisher.events._store_sqlite import _retry_sqlite
from webui_store.base import _LazyStore, _now_iso
from webui_store.sqlite_base import BaseSqliteStore, WebUIDatabase

log = logging.getLogger(__name__)


_UNBOUND_DEFAULT: dict[str, Any] = {
    "status": "unbound",
    "bound_at": None,
    "storage_state_path": None,
    "last_verified_at": None,
}

# Columns that get their own dedicated SQLite column. Every other key in a
# record (e.g. identity_mismatch_old / identity_mismatch_new) is folded into
# the ``extra_json`` blob and merged back at the top level on load.
_KNOWN_COLUMNS: tuple[str, ...] = (
    "status",
    "bound_at",
    "storage_state_path",
    "last_verified_at",
)

_SENTINEL_NAME = ".webui-channel-status-migrated-v1"
_JSON_FILENAME = "channel-status.json"


class ChannelStatusSqliteStore(BaseSqliteStore):
    """Row-table store for channel-binding status, backed by webui.db.

    Replaces the ``channel-status.json`` JsonStore. Each channel is a row keyed
    by its slug. The four common fields (``status``, ``bound_at``,
    ``storage_state_path``, ``last_verified_at``) are dedicated columns; any
    additional keys (the infrequent ``identity_mismatch_old`` /
    ``identity_mismatch_new``) live in an ``extra_json`` blob and are merged
    back at the top level on ``load()`` so the public ``dict[str, dict]``
    contract is byte-for-byte preserved.

    Table::

        channel_status (
          channel            TEXT PRIMARY KEY,
          status             TEXT NOT NULL,
          bound_at           TEXT,
          storage_state_path TEXT,
          last_verified_at   TEXT,
          extra_json         TEXT
        )

    ``load()`` returns the full ``dict[str, dict]`` (``{}`` when empty).
    ``save(value)`` is a full delete-all + bulk-insert rewrite (matches the
    JsonStore whole-file rewrite semantics). ``update(fn)`` is inherited
    (load → fn → save under RLock).
    """

    _value_type = dict
    _json_filename = _JSON_FILENAME
    _sentinel_name = _SENTINEL_NAME

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS channel_status ("
            "channel TEXT PRIMARY KEY, "
            "status TEXT NOT NULL, "
            "bound_at TEXT, "
            "storage_state_path TEXT, "
            "last_verified_at TEXT, "
            "extra_json TEXT)"
        )

    def _indices_sql(self) -> list[str]:
        return [
            "CREATE INDEX IF NOT EXISTS channel_status_status "
            "ON channel_status (status)",
            "CREATE INDEX IF NOT EXISTS channel_status_verified "
            "ON channel_status (last_verified_at)",
        ]

    def load(self) -> dict[str, dict[str, Any]]:
        def _op() -> dict[str, dict[str, Any]]:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT channel, status, bound_at, storage_state_path, "
                    "last_verified_at, extra_json FROM channel_status"
                ).fetchall()
            result: dict[str, dict[str, Any]] = {}
            for (
                channel,
                status,
                bound_at,
                storage_state_path,
                last_verified_at,
                extra_json,
            ) in rows:
                rec: dict[str, Any] = {
                    "status": status,
                    "bound_at": bound_at,
                    "storage_state_path": storage_state_path,
                    "last_verified_at": last_verified_at,
                }
                if extra_json:
                    try:
                        extra = json.loads(extra_json)
                        if isinstance(extra, dict):
                            rec.update(extra)
                    except (json.JSONDecodeError, TypeError):
                        pass
                result[channel] = rec
            return result

        return _retry_sqlite(_op)

    def get_one(self, channel: str) -> dict[str, Any] | None:
        """Fetch a single channel record by slug. Returns ``None`` when
        the channel has no row (avoids loading the entire table)."""

        def _op() -> dict[str, Any] | None:
            with self._db.connect() as conn:
                row = conn.execute(
                    "SELECT status, bound_at, storage_state_path, "
                    "last_verified_at, extra_json FROM channel_status "
                    "WHERE channel = ?",
                    (channel,),
                ).fetchone()
            if row is None:
                return None
            status, bound_at, storage_state_path, last_verified_at, extra_json = row
            rec: dict[str, Any] = {
                "status": status,
                "bound_at": bound_at,
                "storage_state_path": storage_state_path,
                "last_verified_at": last_verified_at,
            }
            if extra_json:
                try:
                    extra = json.loads(extra_json)
                    if isinstance(extra, dict):
                        rec.update(extra)
                except (json.JSONDecodeError, TypeError):
                    pass
            return rec

        return _retry_sqlite(_op)

    def save(self, value: dict[str, dict[str, Any]]) -> None:
        records = value if isinstance(value, dict) else {}
        rows: list[tuple[Any, ...]] = []
        for channel, rec in records.items():
            rec = rec if isinstance(rec, dict) else {}
            extra = {k: v for k, v in rec.items() if k not in _KNOWN_COLUMNS}
            rows.append(
                (
                    channel,
                    rec.get("status"),
                    rec.get("bound_at"),
                    rec.get("storage_state_path"),
                    rec.get("last_verified_at"),
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                )
            )

        self._replace_all_rows(
            "channel_status",
            (
                "channel", "status", "bound_at", "storage_state_path",
                "last_verified_at", "extra_json",
            ),
            rows,
        )


def _make_channel_status_store() -> ChannelStatusSqliteStore:
    config_dir = _config_dir()
    store = ChannelStatusSqliteStore(WebUIDatabase(config_dir / "webui.db"))
    store.migrate_from_json(config_dir)
    return store


channel_status_store: _LazyStore = _LazyStore(_make_channel_status_store)


def _validate_channel(channel: str) -> None:
    if not channel or channel not in CHANNELS:
        raise UsageError(
            f"channel_status: unknown channel {channel!r} "
            f"(allowed: {sorted(CHANNELS)})"
        )


def _validate_storage_state_path(path: Path | str) -> Path:
    """Ensure path resolves inside _config_dir(). Raises UsageError for
    traversal / arbitrary absolute paths."""
    resolved = Path(path).resolve()
    config_root = _config_dir().resolve()
    try:
        resolved.relative_to(config_root)
    except ValueError as exc:
        raise UsageError(
            f"channel_status: storage_state_path {str(path)!r} must resolve "
            f"inside {str(config_root)!r}"
        ) from exc
    return resolved


def mark_bound(channel: str, storage_state_path: Path | str) -> None:
    """Record a successful bind for ``channel``. Validates channel
    whitelist + path locality. Initializes ``last_verified_at`` to
    ``None`` so the next Settings GET runs a fresh liveness probe."""
    _validate_channel(channel)
    resolved_path = _validate_storage_state_path(storage_state_path)

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current = dict(current)
        current[channel] = {
            "status": "bound",
            "bound_at": _now_iso(),
            "storage_state_path": str(resolved_path),
            "last_verified_at": None,
        }
        return current

    channel_status_store.update(_apply)


def mark_expired(channel: str) -> None:
    """Flip ``channel`` to status=expired. Preserves bound_at +
    storage_state_path so the UI can render 'last bound at YYYY-MM-DD'.
    Clears ``last_verified_at`` so the cached truth doesn't outlive the
    expired transition."""
    _validate_channel(channel)

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current = dict(current)
        existing = current.get(channel, {})
        current[channel] = {
            "status": "expired",
            "bound_at": existing.get("bound_at"),
            "storage_state_path": existing.get("storage_state_path"),
            "last_verified_at": None,
        }
        return current

    channel_status_store.update(_apply)


def mark_verified(channel: str) -> None:
    """Stamp ``last_verified_at = now`` for ``channel`` (Plan 003 Unit 0).

    Called by the liveness probe (Plan 003 Unit 5) after a definite
    LOGGED_IN outcome. Other fields preserved. If the record doesn't
    exist yet (e.g., operator clicks "Verify Now" on an unbound channel),
    a minimal record is created with status remaining ``unbound`` —
    only ``last_verified_at`` carries information.
    """
    _validate_channel(channel)

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current = dict(current)
        existing = current.get(channel, {})
        current[channel] = {
            "status": existing.get("status", "unbound"),
            "bound_at": existing.get("bound_at"),
            "storage_state_path": existing.get("storage_state_path"),
            "last_verified_at": _now_iso(),
        }
        return current

    channel_status_store.update(_apply)


def mark_identity_mismatch(
    channel: str, *, old_account: str, new_account: str
) -> None:
    """Record account-mismatch state for ``channel`` (Plan 003 Unit 0 / R6).

    Operator must explicitly resolve via Settings UI (keep old vs replace
    with new). ``reconcile_on_load`` does NOT demote this state to expired
    even if the underlying storage_state.json file is missing.

    Defensive guards (PR #83 adversarial review findings):
      - Empty / identical account strings are treated as no-ops rather
        than written to disk. ``alice/alice`` is not an identity mismatch;
        rendering the keep/replace UI for it would either confuse the
        operator or cause a destructive "replace" of a valid credential.
      - An existing ``identity_mismatch`` record is not overwritten — the
        first mismatch wins until the operator resolves it. Prevents
        retry loops or duplicate JSONL events from silently mutating the
        recorded accounts mid-resolution.
    """
    _validate_channel(channel)
    if not old_account or not new_account or old_account == new_account:
        return

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current = dict(current)
        existing = current.get(channel, {})
        if existing.get("status") == "identity_mismatch":
            return current
        current[channel] = {
            "status": "identity_mismatch",
            "bound_at": existing.get("bound_at"),
            "storage_state_path": existing.get("storage_state_path"),
            "last_verified_at": existing.get("last_verified_at"),
            "identity_mismatch_old": old_account,
            "identity_mismatch_new": new_account,
        }
        return current

    channel_status_store.update(_apply)


def get_status(channel: str) -> dict[str, Any]:
    """Read API. Unknown channels return the unbound default (no
    KeyError) so UI rendering doesn't have to branch on membership."""
    # Fast path: direct SQL lookup avoids loading the entire table.
    store = channel_status_store
    if hasattr(store, 'get_one'):
        rec = store.get_one(channel)
        if rec is not None:
            return rec
        return dict(_UNBOUND_DEFAULT)
    # Fallback for legacy JsonStore
    data = store.load() or {}
    rec = data.get(channel)
    if rec is None:
        return dict(_UNBOUND_DEFAULT)
    return rec


def list_all() -> dict[str, dict[str, Any]]:
    """Read API. Returns the full store as a dict."""
    return dict(channel_status_store.load() or {})


def reconcile_on_load() -> None:
    """Demote any bound record whose ``storage_state_path`` is missing
    on disk to status=expired (preserves bound_at + path for UX).

    Called by ``webui_app.create_app`` at startup (single-threaded
    path), not lazy on first access — avoids lazy-init thread races and
    makes the post-startup state strictly consistent with disk.
    """

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current = dict(current)
        for channel, rec in list(current.items()):
            if not isinstance(rec, dict):
                continue
            # identity_mismatch records require explicit operator resolution
            # (Plan 003 Unit 0 / R6). Reconcile must not auto-demote them.
            if rec.get("status") != "bound":
                continue
            path = rec.get("storage_state_path")
            if not path or not os.path.exists(path):
                current[channel] = {
                    "status": "expired",
                    "bound_at": rec.get("bound_at"),
                    "storage_state_path": rec.get("storage_state_path"),
                    "last_verified_at": None,
                }
        return current

    channel_status_store.update(_apply)


# Channels whose bind-save dispatch rows were removed 2026-05-27 (Plan
# 2026-05-27-001 + the same PR's dead-row sweep). Their UI clear path is gone,
# so any orphaned <slug>-credentials.json 0600 secret left on disk can no longer
# be cleared from the UI. The purge below removes them once. Must stay in sync
# with the rows deleted from channel_bind_save._PASTE_BLOB_CHANNELS /
# _USERPASS_MODULES (jianshu/zhihu/habr/pikabu/segmentfault + cnblogs). A closed
# literal set (NOT registry-derived) keeps the blast radius bounded; the sentinel
# makes it one-shot so a future re-registration of any of these slugs can never
# have its fresh credentials silently deleted. If this list changes after the
# sentinel may already exist in the field, bump _PURGE_SENTINEL_NAME to v2.
_REMOVED_CREDENTIAL_SLUGS: tuple[str, ...] = (
    "jianshu", "zhihu", "cnblogs", "habr", "pikabu", "segmentfault",
    "csdn", "juejin", "note",
)
_PURGE_SENTINEL_NAME: str = ".removed-channel-purge-v2.done"


def purge_removed_channel_credentials() -> None:
    """One-shot, self-disabling cleanup of orphaned credential files for
    removed channels. Best-effort: missing files are normal; unlink failures
    are logged (not silently swallowed) so a stranded 0600 secret is
    discoverable. Symlinks are refused, not followed. Idempotent via a sentinel
    stamp — after the first run it no-ops on every subsequent boot.

    Called by ``webui_app.create_app`` at startup (single-threaded path).
    """
    config_dir = _config_dir()
    # Ensure the dir exists so the sentinel write below succeeds even on a fresh
    # install — otherwise FileNotFoundError would prevent stamping and the
    # "one-shot" would re-scan on every boot.
    config_dir.mkdir(parents=True, exist_ok=True)
    sentinel = config_dir / _PURGE_SENTINEL_NAME
    if sentinel.exists():
        return

    for slug in _REMOVED_CREDENTIAL_SLUGS:
        path = config_dir / f"{slug}-credentials.json"
        if path.is_symlink():
            log.warning(
                "purge_removed_channel_credentials: refusing to follow symlink "
                "%s (not unlinked)", path,
            )
            continue
        if not path.exists():
            continue
        try:
            _validate_storage_state_path(path)  # containment guard
            path.unlink()
        except (OSError, UsageError) as exc:
            log.warning(
                "purge_removed_channel_credentials: could not remove %s (%s) — "
                "stranded 0600 secret; remove manually", path, exc,
            )

    try:
        sentinel.write_text(_now_iso())
    except OSError as exc:  # pragma: no cover — startup must not crash
        log.warning("purge_removed_channel_credentials: sentinel write failed: %s", exc)


def credential_age_days(channel: str) -> float | None:
    """Return days since ``bound_at`` for *channel*, or ``None`` if not set.

    Best-effort: returns None on any parse error.  Used for TTL badge (R8).
    """

    rec = get_status(channel)
    raw = rec.get("bound_at")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - ts
        return delta.total_seconds() / 86400
    except (ValueError, OverflowError):
        return None


def is_near_expiry(channel: str, threshold_days: int = 7) -> bool:
    """Return True when credential is older than *threshold_days* (R11)."""
    age = credential_age_days(channel)
    if age is None:
        return False
    return age >= threshold_days


__all__ = [
    "channel_status_store",
    "mark_bound",
    "mark_expired",
    "mark_identity_mismatch",
    "mark_verified",
    "get_status",
    "list_all",
    "reconcile_on_load",
    "purge_removed_channel_credentials",
    "credential_age_days",
    "is_near_expiry",
]
