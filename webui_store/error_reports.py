"""ErrorReportSqliteStore — persistent, id-addressable frontend error reports.

Backs the frontend error-reporting feature (Plan
``docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md``, Unit 2).
Every unexpected frontend error (auto-captured) or manually-submitted report
is persisted here so it survives a WebUI process restart (R4) — this is the
store Unit 3's ``/api/v1/error-reports`` endpoints read and write.

Row shape mirrors ``CampaignSqliteStore``, NOT ``VerifyHealthSqliteStore``: an
id-keyed row per report plus queryable mirror columns (``status``,
``severity``, ``source``, ``fingerprint``, ``created_at``, ``last_seen_at``,
``occurrences``) alongside a ``data_json`` blob holding the full (already
sanitized by Unit 1) report as the source of truth on read. Error reports are
a continuously-growing, individually-addressable, filterable record set —
not a fixed-key whole-value cache — so the row+mirror-column shape applies,
not ``verify_health.py``'s "one row per key, overwrite the whole table" shape.

There is no JSON predecessor for this store, so ``migrate_from_json`` is the
inherited no-op from ``BaseSqliteStore`` — exactly the ``verify_health.py``
precedent for a store with no legacy JSON file: ``_json_filename`` /
``_sentinel_name`` are simply left at their ``BaseSqliteStore`` class
defaults (``None``), so the migration hook never fires and never needs to
call ``save()``.

**``add()`` is a hard-constrained single-row bare ``INSERT``** (mirrors
``CampaignSqliteStore.create()``'s ``with self._lock: ... _retry_sqlite(_op)``
shape wrapping a direct ``INSERT``) — never a whole-table overwrite. This is
an explicit implementation constraint, not an incidental style choice: had
``add()`` gone through a ``save()``/``_replace_all_rows()`` whole-table-rewrite
shape (the ``verify_health.py`` style), new reports would silently inherit the
lost-update risk measured for this store family in
``docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md``
(labeled "R5" there) — and the failure mode would be *worse* here: a
just-added report could vanish outright under concurrent writers, rather than
merely a status flip failing to apply to an already-persisted row.
``add()`` / ``update_status()`` / ``attach_description()`` /
``increment_occurrence()`` all use targeted SQL (a bare INSERT, or a
SELECT-by-id → merge → UPDATE naming one row), each wrapped in
``_retry_sqlite`` — mirroring ``campaign_store.py``'s ``create`` /
``update_status`` / ``update_seed_status``. None of them ever scans or
rewrites the whole table.

Because this store has no sensible "whole value" to replace (it is an
ever-growing, id-keyed row collection, not a single cached document),
``save()`` intentionally raises ``NotImplementedError`` — mirroring
``BatchOpsSqliteStore.save()``'s identical choice for the identical shape.
This is safe precisely because there is no JSON predecessor: ``migrate_from_json``
never calls ``save()`` in that no-predecessor path, and none of this store's
own methods call it either. ``load()`` (required by the ``Store`` protocol
and by ``BaseSqliteStore``'s abstract contract) is implemented as a plain
alias for ``list()`` with no filters, not as the read-side counterpart of a
``save()`` that replaces everything.

**R5 acceptance, restated for this store:** this store inherits the same
documented limitation as R5 above — ``SqliteStore.__init__`` gives *every*
store instance (this one included) its own ``threading.RLock``; it is a
per-instance lock, **not** one lock shared globally across the whole site —
and that ``RLock`` only guarantees intra-process safety, never a
cross-process ``flock``. The acceptance rationale here matches R5's exactly:
this is non-safety-critical UI/diagnostic state (error reports, not secrets
or throttle counters) served by a single-process WebUI. Because ``add()``
really is a bare single-row INSERT (never a read-modify-write), this store
does not reproduce the ~44/100 lost-update rate R5 measured for same-key
read-modify-write counters — that failure mode requires a shared mutable key,
and ``add()`` never reads before it writes.

That per-instance ``RLock`` question is nonetheless a *distinct* concern from
a second, unrelated one: every store defined in this package — including this
one — shares one physical ``webui.db`` file, and SQLite allows only one
writer at a time regardless of any Python-level lock. A burst of error-report
writes (e.g., a bug that fires on every page load across many open tabs) can
therefore transiently slow down or force a retry of unrelated background jobs
that happen to be writing to ``webui.db`` at the same moment. That is a
SQLite-file-level contention property, independent of the ``RLock``
discussion above.

Plan: docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md Unit 2.
"""

from __future__ import annotations

from datetime import datetime, UTC
import json
from typing import Any
import uuid

from backlink_publisher.events._store_sqlite import _retry_sqlite

from .base import _LazyStore
from .sqlite_base import BaseSqliteStore, WebUIDatabase

_STATUS_OPEN = "open"
_STATUS_ACKNOWLEDGED = "acknowledged"
_STATUS_RESOLVED = "resolved"

#: Closed three-state vocabulary (see the plan's Key Technical Decisions
#: table) — used verbatim by Unit 3's PATCH schema and Unit 8's filter UI.
STATUS_VALUES = frozenset({_STATUS_OPEN, _STATUS_ACKNOWLEDGED, _STATUS_RESOLVED})

#: Columns filtered by exact match in ``list()``. Deliberately a fixed,
#: code-controlled tuple (never built from caller-supplied ``filters.keys()``)
#: so the ``f"{column} = ?"`` interpolation below can never see untrusted
#: identifiers.
_FILTER_EXACT_COLUMNS = ("status", "severity", "source", "fingerprint")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_report_id() -> str:
    return str(uuid.uuid4())


def _validate_status(value: str) -> None:
    if value not in STATUS_VALUES:
        raise ValueError(
            f"status must be one of {sorted(STATUS_VALUES)}, got {value!r}"
        )


class ErrorReportSqliteStore(BaseSqliteStore):
    """Row-table store for frontend error reports, backed by webui.db.

    Table::

        error_reports (
          id            TEXT PRIMARY KEY,
          status        TEXT NOT NULL DEFAULT 'open',  -- open|acknowledged|resolved
          severity      TEXT,           -- free-form; classification policy lives
                                         -- upstream (Unit 1 / Unit 3), not here
          source        TEXT,           -- e.g. 'legacy-js' | 'vue' | 'manual'
          fingerprint   TEXT,           -- dedup key; nullable (manual reports)
          occurrences   INTEGER NOT NULL DEFAULT 1,
          created_at    TEXT NOT NULL,
          updated_at    TEXT NOT NULL,
          last_seen_at  TEXT NOT NULL,
          data_json     TEXT NOT NULL   -- full sanitized report; source of truth
        )

    Every column except ``data_json`` exists purely so ``list()`` /
    ``find_by_fingerprint()`` can filter/order in SQL without deserializing
    every row — the report dict returned to callers is always reconstructed
    from ``data_json`` (mirrors ``CampaignSqliteStore``'s "mirror columns for
    querying, ``data_json`` for the actual read" split).

    ``severity`` / ``source`` are intentionally free-form (no enum
    validation): this store owns persistence only, not the classification
    policy Unit 1 (sanitizer) / Unit 3 (endpoint) apply on top. ``status`` IS
    validated against :data:`STATUS_VALUES` because the three-state
    vocabulary is a cross-cutting contract this plan defines once (see the
    plan's Key Technical Decisions table) and ``update_status()``/``add()``
    must reject a typo'd status rather than silently persisting an off-canon
    value other code will need to special-case forever after.
    """

    _value_type = list

    def _create_table_sql(self) -> str:
        return (
            "CREATE TABLE IF NOT EXISTS error_reports ("
            "id TEXT PRIMARY KEY, "
            "status TEXT NOT NULL DEFAULT 'open', "
            "severity TEXT, "
            "source TEXT, "
            "fingerprint TEXT, "
            "occurrences INTEGER NOT NULL DEFAULT 1, "
            "created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, "
            "last_seen_at TEXT NOT NULL, "
            "data_json TEXT NOT NULL)"
        )

    def _indices_sql(self) -> list[str]:
        return [
            "CREATE INDEX IF NOT EXISTS error_reports_created "
            "ON error_reports(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS error_reports_status "
            "ON error_reports(status)",
            "CREATE INDEX IF NOT EXISTS error_reports_fingerprint "
            "ON error_reports(fingerprint)",
        ]

    # ── Store protocol ─────────────────────────────────────────────────────

    def load(self) -> list[dict[str, Any]]:
        """Return every report, newest-first. Alias for ``list()`` with no filters."""
        return self.list()

    def save(self, value: Any) -> None:
        """Intentionally unsupported — see module docstring.

        This store is an ever-growing, id-addressable row collection, not a
        single replaceable value, so there is no sensible "whole value" to
        overwrite. Use :meth:`add` / :meth:`update_status` /
        :meth:`attach_description` / :meth:`increment_occurrence` /
        :meth:`delete` instead. Mirrors ``BatchOpsSqliteStore.save()``'s
        identical choice for the identical shape.
        """
        raise NotImplementedError(
            "ErrorReportSqliteStore has no whole-table save(); use add() / "
            "update_status() / attach_description() / increment_occurrence() "
            "/ delete() instead."
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def add(self, report: dict[str, Any]) -> str:
        """Insert one new report and return its generated id.

        Single-row bare ``INSERT`` under ``_retry_sqlite`` — see the module
        docstring for why this must never become a read-modify-write or a
        whole-table rewrite. ``id``, ``occurrences``, ``created_at``,
        ``updated_at``, and ``last_seen_at`` on the incoming dict (if any)
        are ignored and overwritten: those are this store's responsibility,
        not the caller's. ``status`` defaults to ``"open"`` when absent and
        is validated against :data:`STATUS_VALUES`.
        """
        report = dict(report) if isinstance(report, dict) else {}
        status = report.get("status") or _STATUS_OPEN
        _validate_status(status)
        severity = report.get("severity")
        source = report.get("source")
        fingerprint = report.get("fingerprint")

        report_id = _new_report_id()
        now = _now_iso()
        report["id"] = report_id
        report["status"] = status
        report["occurrences"] = 1
        report["created_at"] = now
        report["updated_at"] = now
        report["last_seen_at"] = now

        with self._lock:
            def _op() -> None:
                with self._db.connect() as conn:
                    conn.execute(
                        "INSERT INTO error_reports (id, status, severity, "
                        "source, fingerprint, occurrences, created_at, "
                        "updated_at, last_seen_at, data_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            report_id, status, severity, source, fingerprint,
                            1, now, now, now,
                            json.dumps(report, ensure_ascii=False),
                        ),
                    )

            _retry_sqlite(_op)
        return report_id

    def get(self, report_id: str) -> dict[str, Any] | None:
        """Return the report dict, or ``None`` if not found. Read-only."""
        return self._get_one_json(
            "SELECT data_json FROM error_reports WHERE id = ?", (report_id,)
        )

    def list(
        self, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return reports newest-first (``created_at`` DESC), optionally filtered.

        ``filters`` (all optional, AND-combined; omitted/``None`` values are
        ignored rather than matched literally):

        - ``status`` / ``severity`` / ``source`` / ``fingerprint`` — exact
          match against the mirrored columns.
        - ``since`` / ``until`` — inclusive ISO-8601 string bounds on
          ``created_at``.

        An empty store, or a filter set matching nothing, returns ``[]`` —
        never an error.
        """
        filters = filters or {}
        clauses: list[str] = []
        params: list[Any] = []

        for column in _FILTER_EXACT_COLUMNS:
            value = filters.get(column)
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)

        since = filters.get("since")
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)

        until = filters.get("until")
        if until is not None:
            clauses.append("created_at <= ?")
            params.append(until)

        sql = "SELECT data_json FROM error_reports"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"

        return self._load_rows(sql, tuple(params))

    def update_status(self, report_id: str, status: str) -> bool:
        """Set ``status`` (validated) on one report; all other fields untouched.

        Targeted SELECT → merge → UPDATE in one transaction (mirrors
        ``CampaignSqliteStore.update_status``), wrapped in ``_retry_sqlite``.
        Returns ``True`` if the report was found and updated, ``False`` if
        ``report_id`` does not exist.
        """
        _validate_status(status)
        now = _now_iso()

        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT data_json FROM error_reports WHERE id = ?",
                        (report_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    try:
                        report = json.loads(row[0])
                    except (json.JSONDecodeError, TypeError):
                        report = {}
                    if not isinstance(report, dict):
                        report = {}
                    report["status"] = status
                    report["updated_at"] = now
                    conn.execute(
                        "UPDATE error_reports SET status = ?, updated_at = ?, "
                        "data_json = ? WHERE id = ?",
                        (
                            status, now,
                            json.dumps(report, ensure_ascii=False),
                            report_id,
                        ),
                    )
                    return True

            return _retry_sqlite(_op)

    def attach_description(self, report_id: str, text: str) -> bool:
        """Set the user-supplied free-text description on one report.

        Targeted SELECT → merge → UPDATE (same shape as ``update_status``),
        wrapped in ``_retry_sqlite``. Overwrites any prior description — this
        is "attach a/the description", not an append-only log; a report
        carries one current supplementary user description at a time.
        Returns ``True`` if the report was found and updated.
        """
        now = _now_iso()

        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT data_json FROM error_reports WHERE id = ?",
                        (report_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    try:
                        report = json.loads(row[0])
                    except (json.JSONDecodeError, TypeError):
                        report = {}
                    if not isinstance(report, dict):
                        report = {}
                    report["user_description"] = text
                    report["updated_at"] = now
                    conn.execute(
                        "UPDATE error_reports SET updated_at = ?, "
                        "data_json = ? WHERE id = ?",
                        (
                            now,
                            json.dumps(report, ensure_ascii=False),
                            report_id,
                        ),
                    )
                    return True

            return _retry_sqlite(_op)

    def find_by_fingerprint(self, fingerprint: str | None) -> dict[str, Any] | None:
        """Return the most recently created report with this fingerprint, or ``None``.

        Pure index lookup on the ``fingerprint`` column — it does NOT filter
        by ``status``. A resolved report can share a fingerprint with a fresh
        recurrence of the same underlying bug; callers that need "is there
        currently an *open* report with this fingerprint" (Unit 3's POST
        increment-vs-insert decision) must inspect the returned report's
        ``status`` field themselves and fall back to :meth:`add` when it is
        already ``"resolved"``. Keeping this method status-agnostic keeps the
        open/resolved merge *policy* in the endpoint layer, not hard-coded
        into persistence. A falsy ``fingerprint`` (``None``/``""``) always
        returns ``None`` without querying — manual reports may have no
        fingerprint at all, and "no fingerprint" should never match a row.
        """
        if not fingerprint:
            return None
        return self._get_one_json(
            "SELECT data_json FROM error_reports WHERE fingerprint = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (fingerprint,),
        )

    def increment_occurrence(self, report_id: str) -> bool:
        """Bump the occurrence counter and ``last_seen_at``; nothing else changes.

        Deliberately leaves ``updated_at`` untouched — this call records that
        the *same* error happened again, not that the report content was
        edited. Targeted SELECT → merge → UPDATE, wrapped in
        ``_retry_sqlite``. Returns ``True`` if the report was found and
        updated, ``False`` if ``report_id`` does not exist.
        """
        now = _now_iso()

        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    row = conn.execute(
                        "SELECT occurrences, data_json FROM error_reports "
                        "WHERE id = ?",
                        (report_id,),
                    ).fetchone()
                    if row is None:
                        return False
                    current = row[0] if isinstance(row[0], int) else 0
                    try:
                        report = json.loads(row[1])
                    except (json.JSONDecodeError, TypeError):
                        report = {}
                    if not isinstance(report, dict):
                        report = {}
                    new_count = current + 1
                    report["occurrences"] = new_count
                    report["last_seen_at"] = now
                    conn.execute(
                        "UPDATE error_reports SET occurrences = ?, "
                        "last_seen_at = ?, data_json = ? WHERE id = ?",
                        (
                            new_count, now,
                            json.dumps(report, ensure_ascii=False),
                            report_id,
                        ),
                    )
                    return True

            return _retry_sqlite(_op)

    def delete(self, report_id: str) -> bool:
        """Remove one report by id. Never raises for a nonexistent id.

        Returns ``True`` if a row was actually removed, ``False`` otherwise
        (mirrors ``DraftsSqliteStore.delete_item``). This is the only real
        remediation path once a ``sanitize_degraded``-flagged report is
        suspected of residual leakage — sanitization is documented as "best
        effort, not a guarantee", so manual deletion is the backstop.
        """
        with self._lock:
            def _op() -> bool:
                with self._db.connect() as conn:
                    cur = conn.execute(
                        "DELETE FROM error_reports WHERE id = ?", (report_id,)
                    )
                    return cur.rowcount > 0

            return _retry_sqlite(_op)


def _make_error_report_store() -> ErrorReportSqliteStore:
    from backlink_publisher.config.loader import _config_dir
    return ErrorReportSqliteStore(WebUIDatabase(_config_dir() / "webui.db"))


#: Lazily-resolved singleton — mirrors ``verify_health.py``'s
#: ``verify_health_store`` (path resolution deferred to first access, same
#: as every other lazy store in this package). Unit 3 imports this directly
#: (``from webui_store.error_reports import error_report_store``); no change
#: to ``webui_store/__init__.py`` is required for that import to work.
error_report_store: _LazyStore = _LazyStore(_make_error_report_store)
