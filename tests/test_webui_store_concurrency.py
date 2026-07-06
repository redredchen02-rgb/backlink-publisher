"""Unit 2 — Cross-process SQLite update() RMW safety (plan 2026-06-04-004).

Two OS subprocesses call update() adding distinct keys; result documents whether
both survive or one key is lost (known limitation). In-process: sequential
update() via RLock is safe.

Unit 2 (plan 010) extensions:
- test_same_key_rmw_counter: two processes RMW the SAME counter key N=50 times
  each; measures and documents any lost-update (known limitation, NOT a hard
  failure).
- test_wal_busy_timeout_path: one process holds BEGIN EXCLUSIVE while another
  tries to write; verifies the second either succeeds (busy_timeout retry) or
  raises OperationalError, never silently corrupts state.
"""
from __future__ import annotations

__tier__ = "integration"

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap

import pytest

# Repo root so child interpreters can import both src/ (backlink_publisher)
# and repo root (webui_store, webui_app).
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _child_env(config_dir: Path | None = None) -> dict[str, str]:
    """Build child-process env: correct PYTHONPATH + PYTHONHASHSEED=0.

    config_dir, when supplied, overrides BACKLINK_PUBLISHER_CONFIG_DIR so
    children use the same tmp_path sandbox as the parent test.
    """
    env = dict(os.environ)
    src_path = str(_REPO_ROOT / "src")
    repo_path = str(_REPO_ROOT)
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in [src_path, repo_path, existing] if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONHASHSEED"] = "0"
    if config_dir is not None:
        env["BACKLINK_PUBLISHER_CONFIG_DIR"] = str(config_dir)
    return env


# ---------------------------------------------------------------------------
# Child program: increment a shared counter key N times via update() RMW.
# Uses a ready-file as a start-barrier so both processes begin at roughly the
# same instant (maximising contention).
# ---------------------------------------------------------------------------
_CHILD_SAME_KEY = textwrap.dedent("""
    import sys
    import time
    from pathlib import Path
    from webui_store.sqlite_base import WebUIDatabase
    from webui_store.schedule import ScheduleSqliteStore

    db_path   = Path(sys.argv[1])
    ready_dir = Path(sys.argv[2])
    worker_id = sys.argv[3]          # "0" or "1"
    iters     = int(sys.argv[4])
    barrier   = ready_dir / "go.flag"

    db    = WebUIDatabase(db_path)
    store = ScheduleSqliteStore(db)

    # Signal readiness, then spin until both are ready.
    (ready_dir / f"ready_{worker_id}").touch()
    deadline = time.monotonic() + 10.0
    while not barrier.exists():
        if time.monotonic() > deadline:
            raise TimeoutError("barrier never raised")
        time.sleep(0.005)

    for _ in range(iters):
        store.update(lambda d: {**d, "counter": d.get("counter", 0) + 1})
""")

# ---------------------------------------------------------------------------
# Child program: hold BEGIN EXCLUSIVE then exit; used to saturate the write
# lock so a concurrent write must wait / retry / raise.
# ---------------------------------------------------------------------------
_CHILD_HOLD_LOCK = textwrap.dedent("""
    import sys
    import sqlite3
    import time
    from pathlib import Path

    db_path   = Path(sys.argv[1])
    hold_secs = float(sys.argv[2])
    flag_path = Path(sys.argv[3])   # written once lock is held

    conn = sqlite3.connect(str(db_path), timeout=1.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 100")
    conn.execute("BEGIN EXCLUSIVE")
    # Signal that the exclusive lock is now held.
    flag_path.write_text("locked", encoding="utf-8")
    time.sleep(hold_secs)
    conn.rollback()
    conn.close()
""")

# ---------------------------------------------------------------------------
# Child program: attempt a single update() write; exits 0 on success or
# writes "LOCKED" to stdout if OperationalError("database is locked") fires.
# ---------------------------------------------------------------------------
_CHILD_TRY_WRITE = textwrap.dedent("""
    import sys
    import sqlite3
    from pathlib import Path
    from webui_store.sqlite_base import WebUIDatabase
    from webui_store.schedule import ScheduleSqliteStore

    db_path = Path(sys.argv[1])

    db    = WebUIDatabase(db_path)
    store = ScheduleSqliteStore(db)
    try:
        store.update(lambda d: {**d, "busy_probe": True})
        print("OK")
    except sqlite3.OperationalError as exc:
        if "database is locked" in str(exc).lower():
            print("LOCKED")
        else:
            raise
""")


def _write_worker(script_path: Path, db_path: Path, key: str, val: str) -> None:
    script_path.write_text(
        textwrap.dedent(f"""
            from pathlib import Path
            from webui_store.sqlite_base import WebUIDatabase
            from webui_store.schedule import ScheduleSqliteStore

            db = WebUIDatabase(Path(r'{db_path}'))
            store = ScheduleSqliteStore(db)
            store.update(lambda d: {{**d, '{key}': '{val}'}})
        """).strip(),
        encoding="utf-8",
    )


def test_cross_process_update_documents_behavior(tmp_path, monkeypatch):
    """Two OS processes each update() with distinct key; documents whether both survive.

    This test PASSES regardless of outcome (both keys survive or one is lost).
    A lost-update result documents the known cross-process RMW limitation of
    update() — the RLock only protects within a single process.
    """
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.schedule import ScheduleSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    db_path = tmp_path / "webui.db"
    # Initialize the store (creates tables)
    init_db = WebUIDatabase(db_path)
    ScheduleSqliteStore(init_db).save({})  # ensure table exists

    import os
    repo_root = Path(__file__).parent.parent
    env = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "BACKLINK_PUBLISHER_CONFIG_DIR": str(tmp_path),
        "PYTHONPATH": str(repo_root / "src") + os.pathsep + str(repo_root),
    }

    w0 = tmp_path / "worker_0.py"
    w1 = tmp_path / "worker_1.py"
    _write_worker(w0, db_path, "key_0", "val_0")
    _write_worker(w1, db_path, "key_1", "val_1")

    p0 = subprocess.Popen([sys.executable, str(w0)], env=env)
    p1 = subprocess.Popen([sys.executable, str(w1)], env=env)
    rc0, rc1 = p0.wait(), p1.wait()
    assert rc0 == 0, f"worker_0 exited {rc0}"
    assert rc1 == 0, f"worker_1 exited {rc1}"

    result = ScheduleSqliteStore(WebUIDatabase(db_path)).load()
    # Document behavior: both keys may or may not survive (known limitation).
    # This assertion is intentionally loose: the test passes either way.
    keys_present = {k for k in ("key_0", "key_1") if k in result}
    # At least one key must survive (complete data loss would be a crash)
    assert len(keys_present) >= 1, f"Expected at least 1 key, got: {result}"
    # Comment: if only 1 key survives, that documents the cross-process lost-update
    # limitation of update() — RLock only guards same-process access.


def test_in_process_sequential_update_no_deadlock(tmp_path, monkeypatch):
    """In-process: two sequential update() calls via RLock → both keys present."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.schedule import ScheduleSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    db = WebUIDatabase(tmp_path / "webui.db")
    store = ScheduleSqliteStore(db)

    store.update(lambda d: {**d, "key_a": "val_a"})
    store.update(lambda d: {**d, "key_b": "val_b"})

    result = store.load()
    assert result["key_a"] == "val_a"
    assert result["key_b"] == "val_b"


def test_two_instances_sequential_update_both_survive(tmp_path, monkeypatch):
    """Two in-process instances of same store, sequential update → non-conflicting rows."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.schedule import ScheduleSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    db_path = tmp_path / "webui.db"
    s1 = ScheduleSqliteStore(WebUIDatabase(db_path))
    s2 = ScheduleSqliteStore(WebUIDatabase(db_path))

    s1.update(lambda d: {**d, "from_s1": "x"})
    s2.update(lambda d: {**d, "from_s2": "y"})

    result = s1.load()
    assert result["from_s1"] == "x"
    assert result["from_s2"] == "y"


# ---------------------------------------------------------------------------
# Plan 010 Unit 2 — Test 1: same-key RMW counter with two OS processes
# ---------------------------------------------------------------------------

def test_same_key_rmw_counter(tmp_path, monkeypatch):
    """Two OS processes each RMW-increment the SAME 'counter' key N=50 times.

    Expected maximum: 100 (if every increment survives).
    Because update() uses a threading.RLock — which only serialises within a
    single process — cross-process RMW races the load→compute→save cycle.
    SQLite WAL mode allows one writer at a time, but the READ in update() and
    the WRITE are two separate transactions: another process can read the same
    old value between our read and our write, producing a lost update.

    This test PASSES regardless of the counter value.  If counter < 100 it
    documents the measured loss amount.  The assertion only guards against a
    complete crash (counter == 0 or missing key) or an impossible result
    (counter > 100).
    """
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.schedule import ScheduleSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    db_path = tmp_path / "webui.db"
    # Initialise table and set counter = 0.
    ScheduleSqliteStore(WebUIDatabase(db_path)).save({"counter": 0})

    iters = 50
    ready_dir = tmp_path / "barrier"
    ready_dir.mkdir()

    env = _child_env(config_dir=tmp_path)

    p0 = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SAME_KEY,
         str(db_path), str(ready_dir), "0", str(iters)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p1 = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SAME_KEY,
         str(db_path), str(ready_dir), "1", str(iters)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for both workers to signal readiness, then raise the barrier.
    import time
    deadline = time.monotonic() + 15.0
    while True:
        if (ready_dir / "ready_0").exists() and (ready_dir / "ready_1").exists():
            break
        if time.monotonic() > deadline:
            p0.kill(); p1.kill()
            raise TimeoutError("workers never signalled ready")
        time.sleep(0.01)
    (ready_dir / "go.flag").touch()

    out0, err0 = p0.communicate(timeout=30)
    out1, err1 = p1.communicate(timeout=30)

    assert p0.returncode == 0, (
        f"worker-0 exited {p0.returncode}\nstdout: {out0}\nstderr: {err0}"
    )
    assert p1.returncode == 0, (
        f"worker-1 exited {p1.returncode}\nstdout: {out1}\nstderr: {err1}"
    )

    result = ScheduleSqliteStore(WebUIDatabase(db_path)).load()
    counter = result.get("counter", None)

    # Sanity guards: key must exist, value must be in [1, 100].
    assert counter is not None, f"'counter' key missing from store: {result}"
    assert 1 <= counter <= 100, (
        f"counter={counter} is outside expected range [1, 100]: {result}"
    )

    # Document the measured loss without failing the test.
    expected = iters * 2  # 100
    lost = expected - counter
    if lost > 0:
        # Known limitation: RLock does NOT guard across OS-process boundaries.
        # The cross-process race window is: load(conn1) … load(conn2) … save(conn1)
        # … save(conn2) — conn2's save overwrites conn1's result.
        print(
            f"\n[same_key_rmw] counter={counter}/{expected}  "
            f"lost_updates={lost}  "
            f"(known cross-process RMW limitation — RLock is intra-process only)"
        )
    else:
        # All increments survived — WAL busy_timeout + sqlite serialisation
        # happened to prevent every race (non-deterministic; do not rely on it).
        print(f"\n[same_key_rmw] counter={counter}/{expected}  lost_updates=0  (no loss this run)")


# ---------------------------------------------------------------------------
# Plan 010 Unit 2 — Test 2: WAL busy_timeout path
# ---------------------------------------------------------------------------

def test_wal_busy_timeout_path(tmp_path, monkeypatch):
    """BEGIN EXCLUSIVE held by one process; concurrent write must not corrupt state.

    Scenario:
    1. Process A opens a raw sqlite3 connection and executes BEGIN EXCLUSIVE,
       holding it for 0.3 s then rolling back cleanly.
    2. Process B calls store.update() while A holds the lock.

    Process B is expected to either:
      (a) succeed — SQLite busy_timeout=5000 ms is long enough for A to release, OR
      (b) raise sqlite3.OperationalError("database is locked") if retries exhaust.

    What must NOT happen: silent corruption (partial write, wrong value).

    The test PASSES in both outcome (a) and (b).  The assertion only checks
    that the final counter value is consistent: if B succeeded, the row exists
    with busy_probe=True; if B reported LOCKED, the row is absent/unchanged but
    the db file is not corrupt (load() returns a valid dict).
    """
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from webui_store.schedule import ScheduleSqliteStore
    from webui_store.sqlite_base import WebUIDatabase

    db_path = tmp_path / "webui.db"
    # Initialise table.
    ScheduleSqliteStore(WebUIDatabase(db_path)).save({})

    env = _child_env(config_dir=tmp_path)
    lock_flag = tmp_path / "lock.flag"

    # --- Process A: hold BEGIN EXCLUSIVE for 0.3 s ---
    p_lock = subprocess.Popen(
        [sys.executable, "-c", _CHILD_HOLD_LOCK,
         str(db_path), "0.3", str(lock_flag)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait until the lock is confirmed held.
    import time
    deadline = time.monotonic() + 10.0
    while not lock_flag.exists():
        if time.monotonic() > deadline:
            p_lock.kill()
            raise TimeoutError("lock holder never wrote flag")
        time.sleep(0.01)

    # --- Process B: attempt update() while A holds the exclusive lock ---
    p_write = subprocess.Popen(
        [sys.executable, "-c", _CHILD_TRY_WRITE, str(db_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    out_w, err_w = p_write.communicate(timeout=15)
    out_l, err_l = p_lock.communicate(timeout=10)

    # Process A must exit cleanly (rollback, not crash).
    assert p_lock.returncode == 0, (
        f"lock-holder crashed: rc={p_lock.returncode}\nstdout: {out_l}\nstderr: {err_l}"
    )

    # Process B must exit with rc=0; it printed "OK" or "LOCKED".
    assert p_write.returncode == 0, (
        f"writer crashed: rc={p_write.returncode}\nstdout: {out_w}\nstderr: {err_w}"
    )

    outcome = out_w.strip()
    assert outcome in ("OK", "LOCKED"), (
        f"unexpected writer output: {out_w!r}\nstderr: {err_w}"
    )

    # Regardless of outcome, the DB must be readable and consistent.
    final = ScheduleSqliteStore(WebUIDatabase(db_path)).load()
    assert isinstance(final, dict), f"load() returned non-dict after busy test: {final!r}"

    if outcome == "OK":
        assert final.get("busy_probe") is True, (
            f"writer reported OK but 'busy_probe' not in store: {final}"
        )
        print("\n[busy_timeout] writer succeeded — busy_timeout retry absorbed the wait")
    else:
        # LOCKED: busy_timeout exhausted; value absent but no corruption.
        print(
            "\n[busy_timeout] writer raised OperationalError('database is locked') — "
            "busy_timeout did NOT retry enough; row is absent but db is intact"
        )
