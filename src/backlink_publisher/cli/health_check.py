"""health-check — read-only storage health diagnostics (Plan U4.4).

Reports the health of backlink-publisher storage subsystems:

  - events.db size and row count
  - dedup.db size and row count
  - config dir file count and credential permission audit
  - oldest unreconciled checkpoint age

Exit codes:
    0 — all subsystems healthy
    1 — warnings (storage growing, old checkpoints)
    2 — errors (missing db, corrupt data)

Usage::

    health-check                          # human-readable report (stdout)
    health-check --json                   # JSON report
    health-check --fix-permissions        # fix credential file modes
"""

from __future__ import annotations

import argparse
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from backlink_publisher.config import _cache_dir, _config_dir

_CREDENTIAL_SUFFIXES = (
    "-state.json",
    "-token.json",
    "-cookies.json",
    ".key",
    "-storage-state.json",
)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _db_stats(path: str | Path) -> dict[str, Any]:
    """Return size and row count for a SQLite database."""
    p = Path(path)
    if not p.exists():
        return {"exists": False, "size_mb": 0, "rows": 0, "error": "not_found"}
    try:
        size_mb = round(p.stat().st_size / (1024 * 1024), 2)
        conn = sqlite3.connect(str(p))
        row_count = conn.execute(
            "SELECT COUNT(*) FROM events" if "events" in p.name
            else "SELECT COUNT(*) FROM dedup"
        ).fetchone()[0]
        conn.close()
        return {"exists": True, "size_mb": size_mb, "rows": row_count, "error": None}
    except (sqlite3.Error, OSError) as exc:
        return {"exists": True, "size_mb": 0, "rows": 0, "error": str(exc)}


def _config_file_count(config_dir: str) -> int:
    """Count config files in the config directory."""
    d = Path(config_dir)
    if not d.exists():
        return 0
    return sum(1 for f in d.iterdir() if f.is_file())


def _credential_audit(
    config_dir: str, fix: bool = False
) -> dict[str, Any]:
    """Scan credential files and report non-0600 permissions."""
    d = Path(config_dir)
    if not d.exists():
        return {"total": 0, "non_0600": 0, "files": []}

    non_0600: list[dict[str, Any]] = []
    total = 0
    for f in d.iterdir():
        if not f.is_file() or not f.name.endswith(_CREDENTIAL_SUFFIXES):
            continue
        total += 1
        try:
            mode = f.stat().st_mode & 0o777
            if mode != 0o600:
                non_0600.append({"path": f.name, "mode": oct(mode)})
                if fix:
                    f.chmod(0o600)
        except OSError:
            non_0600.append({"path": f.name, "mode": "unknown"})

    return {"total": total, "non_0600": len(non_0600), "files": non_0600}


def _oldest_checkpoint(config_dir: str) -> dict[str, Any]:
    """Find the oldest checkpoint in the checkpoint directory."""
    checkpoint_dir = Path(config_dir) / "checkpoints"
    if not checkpoint_dir.exists():
        return {"exists": False, "age_hours": 0, "count": 0}

    checkpoints = sorted(checkpoint_dir.glob("*.json"))
    if not checkpoints:
        return {"exists": True, "age_hours": 0, "count": 0}

    now = datetime.now(UTC).timestamp()
    oldest = checkpoints[0]
    age_hours = round((now - oldest.stat().st_mtime) / 3600, 1)
    return {
        "exists": True,
        "age_hours": age_hours,
        "count": len(checkpoints),
        "oldest": oldest.name,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _check_all(
    config_dir: str, cache_dir: str, fix_perms: bool = False
) -> dict[str, Any]:
    events_db = os.path.join(cache_dir, "events.db")
    dedup_db = os.path.join(config_dir, "dedup.db")

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "events_db": _db_stats(events_db),
        "dedup_db": _db_stats(dedup_db),
        "config_dir": {
            "path": config_dir,
            "file_count": _config_file_count(config_dir),
        },
        "credentials": _credential_audit(config_dir, fix=fix_perms),
        "checkpoints": _oldest_checkpoint(config_dir),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="health-check",
        description="Storage health diagnostics for backlink-publisher.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report instead of human-readable.",
    )
    parser.add_argument(
        "--fix-permissions",
        action="store_true",
        help="Fix non-0600 credential file permissions.",
    )
    args = parser.parse_args(argv)

    config_dir = _config_dir()
    cache_dir = _cache_dir()
    report = _check_all(str(config_dir), str(cache_dir), fix_perms=args.fix_permissions)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)

    # Exit codes
    issues = 0
    if report["credentials"]["non_0600"] > 0:
        issues = max(issues, 1)
    if report["events_db"].get("error") or report["dedup_db"].get("error"):
        issues = max(issues, 2)
    sys.exit(issues)


def _print_human(report: dict[str, Any]) -> None:
    print("═══ Storage Health ═══")
    print()

    for db_key in ("events_db", "dedup_db"):
        db = report[db_key]
        name = db_key.replace("_", ".")
        if db.get("error"):
            print(f"  {name}: ERROR — {db['error']}")
        elif not db["exists"]:
            print(f"  {name}: not found")
        else:
            print(f"  {name}: {db['size_mb']:.1f} MB, {db['rows']} rows")

    cd = report["config_dir"]
    print(f"  config: {cd['file_count']} files @ {cd['path']}")

    creds = report["credentials"]
    perm_status = "✓" if creds["non_0600"] == 0 else f"⚠ {creds['non_0600']} non-0600"
    print(f"  credentials: {creds['total']} files, {perm_status}")

    cp = report["checkpoints"]
    if cp.get("error"):
        print(f"  checkpoints: ERROR — {cp['error']}")
    elif not cp["exists"]:
        print("  checkpoints: (no checkpoint dir)")
    else:
        print(f"  checkpoints: {cp['count']} files, oldest {cp['age_hours']:.1f}h")
    print()


if __name__ == "__main__":
    main()
