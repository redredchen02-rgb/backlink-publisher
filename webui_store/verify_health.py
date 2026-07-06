"""Per-platform credential-expiry verdict store — Plan 2026-06-05-008.

Caches the last *credential* verify verdict so an expired API/OAuth token is
surfaced as needs-reconnect (reusing the plan-007 partition) instead of
masquerading as healthy (offline ``bound`` only checks token presence, not
validity). Only ``token_expired`` / ``ok`` mutate state — transient verdicts
(``timeout`` / ``never`` / ``unverifiable_live``) are ignored so a network blip
never raises a false reconnect alarm. Backed by a ``verify_health`` table in
``webui.db``.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from backlink_publisher.config.loader import _config_dir
from backlink_publisher.events._store_sqlite import _retry_sqlite
from webui_store.base import _LazyStore
from webui_store.sqlite_base import BaseSqliteStore, WebUIDatabase

_EXPIRED = "token_expired"
_OK = "ok"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class VerifyHealthSqliteStore(BaseSqliteStore):
    """Row-table store of the last credential verdict per platform.

    Table::

        verify_health (channel TEXT PRIMARY KEY, result TEXT NOT NULL, at TEXT)

    ``load()`` returns ``{channel: {"result", "at"}}``; ``save(value)`` is a
    whole-table rewrite (matches the channel_status semantics). ``update(fn)``
    is inherited (load → fn → save under the store RLock). ``__init__`` /
    ``_init_table`` are inherited from :class:`BaseSqliteStore`; there is no
    JSON predecessor so ``migrate_from_json`` is the inherited no-op.
    """

    _value_type = dict

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS verify_health ("
            "channel TEXT PRIMARY KEY, result TEXT NOT NULL, at TEXT)"
        )

    def load(self) -> dict[str, dict[str, Any]]:
        def _op() -> dict[str, dict[str, Any]]:
            with self._db.connect() as conn:
                rows = conn.execute(
                    "SELECT channel, result, at FROM verify_health"
                ).fetchall()
            return {c: {"result": r, "at": a} for c, r, a in rows}

        return _retry_sqlite(_op)

    def save(self, value: dict[str, dict[str, Any]]) -> None:
        records = value if isinstance(value, dict) else {}
        rows = [
            (channel, rec.get("result"), rec.get("at"))
            for channel, rec in records.items()
            if isinstance(rec, dict) and rec.get("result")
        ]

        self._replace_all_rows(
            "verify_health", ("channel", "result", "at"), rows
        )


def _make_verify_health_store() -> VerifyHealthSqliteStore:
    return VerifyHealthSqliteStore(WebUIDatabase(_config_dir() / "webui.db"))


verify_health_store: _LazyStore = _LazyStore(_make_verify_health_store)


def record(channel: str, result: str) -> None:
    """Update the cached verdict for ``channel``.

    ``token_expired`` → set/refresh the expired marker; ``ok`` → clear it; any
    other (transient) verdict → no-op. Atomic via the store's RMW ``update``.
    """
    if result not in (_EXPIRED, _OK):
        return

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        current = dict(current)
        if result == _EXPIRED:
            current[channel] = {"result": _EXPIRED, "at": _now_iso()}
        else:  # ok → clear any prior expiry
            current.pop(channel, None)
        return current

    verify_health_store.update(_apply)


def expired_channels() -> frozenset[str]:
    """Channels whose last credential verdict was ``token_expired``."""
    data = verify_health_store.load() or {}
    return frozenset(
        name
        for name, rec in data.items()
        if isinstance(rec, dict) and rec.get("result") == _EXPIRED
    )


def list_all() -> dict[str, dict[str, Any]]:
    """Full store snapshot (debug / parity)."""
    return dict(verify_health_store.load() or {})
