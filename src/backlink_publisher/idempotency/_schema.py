"""SQLite schema for the dedup store."""

# Column list shared by SELECT helpers, in DedupRecord field order.
_COLS = (
    "platform, account, target_url, state, verify_ok, live_url, run_id, "
    "owner_pid, owner_run_id, owner_started_at, updated_at"
)

_SCHEMA_DDL = """CREATE TABLE IF NOT EXISTS dedup_keys (
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
)"""
