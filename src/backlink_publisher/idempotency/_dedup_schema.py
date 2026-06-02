"""Schema helpers for the dedup store."""

from ._store_types import DedupRecord

# Column list shared by SELECT helpers, in DedupRecord field order.
_COLS = (
    "platform, account, target_url, state, verify_ok, live_url, run_id, "
    "owner_pid, owner_run_id, owner_started_at, updated_at"
)

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS dedup_keys (
    platform           TEXT NOT NULL,
    account            TEXT NOT NULL,
    account_binding_id TEXT,
    target_url         TEXT NOT NULL,
    state              TEXT NOT NULL,
    verify_ok          INTEGER,
    live_url           TEXT,
    run_id             TEXT,
    owner_pid          INTEGER,
    owner_run_id       TEXT,
    owner_started_at   REAL,
    updated_at         REAL NOT NULL,
    PRIMARY KEY (platform, account, target_url)
)
"""


def _row_to_record(row: tuple) -> DedupRecord:
    (
        platform,
        account,
        target_url,
        state,
        verify_ok,
        live_url,
        run_id,
        owner_pid,
        owner_run_id,
        owner_started_at,
        updated_at,
    ) = row
    return DedupRecord(
        platform=platform,
        account=account,
        target_url=target_url,
        state=state,
        verify_ok=None if verify_ok is None else bool(verify_ok),
        live_url=live_url,
        run_id=run_id,
        owner_pid=owner_pid,
        owner_run_id=owner_run_id,
        owner_started_at=owner_started_at,
        updated_at=updated_at,
    )
