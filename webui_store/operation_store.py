"""OperationSqliteStore — persistent record of async pipeline operations.

Backed by ``webui.db`` (same DB as campaigns/queue/batch-ops). One row per
operation; the full op dict lives in ``data_json`` (source of truth) with a
few mirrored columns (``kind`` / ``status`` / ``stage`` / ``progress_pct`` /
``created_at`` / ``updated_at``) for querying + ordering, exactly like
``CampaignSqliteStore``.

Operations are the WebUI's async job records: a publish / publish-chain /
plan / validate call returns an ``op_id`` immediately and runs in a background
worker thread (``webui_app.services.operation_worker``), updating this store as
it progresses so the SPA can poll ``GET /api/v1/operations/<id>``.

Plan: docs/plans/2026-07-09-webui-operation-progress-plan.md (U1).
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
from typing import Any
import uuid

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .sqlite_base import BaseSqliteStore

_OP_SCHEMA_VERSION = 1

# Module-level alias: OperationSqliteStore defines a method named ``list``,
# which shadows the builtin inside the class body — a bare ``list[...]``
# annotation on later methods resolves to the method and mypy rejects it as
# not-a-type. ruff (UP006) bans typing.List, so alias the builtin here instead.
_OpRows = list[dict[str, Any]]

_OP_STATUS_VALUES = frozenset({
    "pending", "running", "success", "failed", "canceled",
})

_OP_KIND_VALUES = frozenset({
    "plan", "validate", "publish", "publish_chain",
})

# Ordered stage labels per kind — drives the SPA step indicator. The worker
# advances ``stage`` through these as it progresses; the SPA renders them
# generically without re-deriving the sequence.
_STAGES_FOR_KIND: dict[str, list[str]] = {
    "plan": ["生成"],
    "validate": ["验证"],
    "publish": ["发布"],
    "publish_chain": ["生成", "验证", "发布"],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_op_id() -> str:
    return str(uuid.uuid4())


def _validate_status(value: str, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise ValueError(
            f"{label} must be one of {sorted(allowed)}, got {value!r}"
        )


class OperationSqliteStore(BaseSqliteStore):
    """Row-table store for async operations, backed by ``webui.db``.

    Schema (per op dict)::

        {
            "op_id": str,
            "kind": "plan" | "validate" | "publish" | "publish_chain",
            "status": "pending" | "running" | "success" | "failed" | "canceled",
            "stage": str,            # current stage label (human readable)
            "progress_pct": float,   # 0-100
            "detail": str,           # free-form progress note
            "result": dict | None,   # terminal result payload
            "error": str | None,     # terminal error message
            "cfg": dict,             # the request payload that started the op
            "created_at": ISO-8601,
            "updated_at": ISO-8601,
        }

    Table::

        operations (
          id           TEXT PRIMARY KEY,
          kind         TEXT NOT NULL,
          status       TEXT NOT NULL,
          stage        TEXT,
          progress_pct REAL,
          created_at   TEXT,
          updated_at   TEXT,
          detail       TEXT,
          result_json  TEXT,
          error        TEXT,
          data_json    TEXT NOT NULL
        )
        CREATE INDEX operations_created ON operations(created_at DESC)
        CREATE INDEX operations_status  ON operations(status)
    """

    _value_type = dict

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS operations ("
            "id TEXT PRIMARY KEY, "
            "kind TEXT NOT NULL, "
            "status TEXT NOT NULL, "
            "stage TEXT, "
            "progress_pct REAL, "
            "created_at TEXT, "
            "updated_at TEXT, "
            "detail TEXT, "
            "result_json TEXT, "
            "error TEXT, "
            "data_json TEXT NOT NULL)"
        )

    def _indices_sql(self) -> list[str]:
        return [
            "CREATE INDEX IF NOT EXISTS operations_created ON operations(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS operations_status ON operations(status)",
        ]

    # ── Store protocol ─────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        """Return all operations sorted by ``created_at`` DESC (mirrors list)."""
        return self._load_rows(
            "SELECT data_json FROM operations ORDER BY created_at DESC"
        )

    def save(self, value: Any) -> None:
        """Replace the whole table: delete-all + bulk-insert in one transaction."""
        ops = value if isinstance(value, list) else []
        rows: list[tuple[Any, ...]] = []
        for op in ops:
            op = op if isinstance(op, dict) else {}
            rows.append(
                (
                    op.get("op_id"),
                    op.get("kind"),
                    op.get("status"),
                    op.get("stage"),
                    op.get("progress_pct"),
                    op.get("created_at"),
                    op.get("updated_at"),
                    op.get("detail"),
                    _json_or_none(op.get("result")),
                    op.get("error"),
                    _json_or_none(op),
                )
            )
        self._replace_all_rows(
            "operations",
            (
                "id", "kind", "status", "stage", "progress_pct",
                "created_at", "updated_at", "detail", "result_json", "error",
                "data_json",
            ),
            rows,
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def create(self, *, kind: str, cfg: dict[str, Any]) -> str:
        """Create a new pending operation and return its ``op_id``."""
        if kind not in _OP_KIND_VALUES:
            raise ValueError(f"kind must be one of {sorted(_OP_KIND_VALUES)}, got {kind!r}")
        op_id = _new_op_id()
        now = _now_iso()
        op: dict[str, Any] = {
            "op_id": op_id,
            "kind": kind,
            "status": "pending",
            "stage": "",
            "stages": list(_STAGES_FOR_KIND.get(kind, [])),
            "progress_pct": 0.0,
            "detail": "",
            "result": None,
            "error": None,
            "cfg": cfg,
            "_schema_version": _OP_SCHEMA_VERSION,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT INTO operations (id, kind, status, stage, "
                        "progress_pct, created_at, updated_at, detail, "
                        "result_json, error, data_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            op_id,
                            op["kind"],
                            op["status"],
                            op["stage"],
                            op["progress_pct"],
                            op["created_at"],
                            op["updated_at"],
                            op["detail"],
                            None,
                            op["error"],
                            _json_or_none(op),
                        ),
                    )

            _retry_sqlite(_op)
        return op_id

    def get(self, op_id: str) -> dict[str, Any] | None:
        """Return the op dict, or ``None`` if not found. Read-only."""
        return self._get_one_json(
            "SELECT data_json FROM operations WHERE id = ?", (op_id,)
        )

    def update_fields(self, op_id: str, **updates: Any) -> bool:
        """Merge ``updates`` into the matching op (SELECT → merge → UPDATE).

        Accepted keyword arguments (at least one required):
          - ``status`` — validated against ``_OP_STATUS_VALUES``
          - ``stage`` — str (current stage label)
          - ``progress_pct`` — float 0-100 (auto-clamped)
          - ``detail`` — str
          - ``result`` — dict or ``None`` (terminal payload)
          - ``error`` — str or ``None`` (terminal error)
          - any other key is stored verbatim (future-proof)

        Returns ``True`` if the op was found and updated.
        """
        if not updates:
            return False

        _status = updates.get("status")
        if _status is not None:
            _validate_status(_status, _OP_STATUS_VALUES, "op status")

        _pct = updates.get("progress_pct")
        if _pct is not None:
            updates["progress_pct"] = max(0.0, min(100.0, float(_pct)))

        updates["updated_at"] = _now_iso()

        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT data_json FROM operations WHERE id = ?",
                        (op_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    try:
                        op = json.loads(row[0])
                    except (json.JSONDecodeError, TypeError):
                        op = {}
                    if not isinstance(op, dict):
                        op = {}
                    op.update(updates)
                    conn.execute(
                        "UPDATE operations SET kind = ?, status = ?, stage = ?, "
                        "progress_pct = ?, created_at = ?, updated_at = ?, "
                        "detail = ?, result_json = ?, error = ?, data_json = ? "
                        "WHERE id = ?",
                        (
                            op.get("kind"),
                            op.get("status"),
                            op.get("stage"),
                            op.get("progress_pct"),
                            op.get("created_at"),
                            op.get("updated_at"),
                            op.get("detail"),
                            _json_or_none(op.get("result")),
                            op.get("error"),
                            _json_or_none(op),
                            op_id,
                        ),
                    )
                    return True

            return _retry_sqlite(_op)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent ``limit`` operations, newest first."""
        return self._load_rows(
            "SELECT data_json FROM operations ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        )

    def list_active(self) -> _OpRows:
        """Return ops still pending or running, newest first.

        Annotated via the module-level ``_OpRows`` alias — see its comment
        (the ``list`` method above shadows the builtin in this class body).
        """
        return self._load_rows(
            "SELECT data_json FROM operations WHERE status IN ('pending', 'running') "
            "ORDER BY created_at DESC"
        )


def _json_or_none(value: Any) -> str | None:
    """Serialise ``value`` to JSON, or ``None`` for ``None``/missing payloads."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


# Backward-compat alias.
OperationStore = OperationSqliteStore

# The ``operation_store`` singleton lives in ``webui_store/__init__.py``
# (package-level ``_LazyStore`` over the shared ``_get_webui_db()`` instance,
# wired into ``_refresh_paths()`` for test isolation). ``from webui_store
# import operation_store`` binds that package attribute, which shadows this
# submodule's name — do not add a second singleton here.
