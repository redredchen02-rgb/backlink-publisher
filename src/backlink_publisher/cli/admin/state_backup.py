"""Backup and restore state files for backlink-publisher.

Usage::

    backup-state                    # create timestamped backup
    restore-state --list            # list available backups
    restore-state <backup_name>     # restore from a specific backup
    restore-state <backup_name> --yes  # restore without prompt
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from backlink_publisher.config.loader import _resolve_config_dir

# Files to include in backup (relative to config dir)
_STATE_FILES: list[str] = [
    "events.db",
    "webui.db",
    "publish-history.json",
    "optimization_state.json",
    "channel-status.json",
    "canary-health.json",
    "debt_registry.toml",
]


def _config_dir() -> Path:
    return _resolve_config_dir()


def _backup_dir() -> Path:
    return _config_dir() / "backups"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _find_backups() -> list[Path]:
    bdir = _backup_dir()
    if not bdir.exists():
        return []
    return sorted(
        [p for p in bdir.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )


def _backup_db(src: Path, dst: Path) -> None:
    """Consistent SQLite backup using backup API."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()


def _backup_file(src: Path, dst: Path) -> None:
    """Copy a regular file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _is_sqlite(path: Path) -> bool:
    return path.suffix == ".db"


def backup_main() -> None:
    """Create a timestamped backup of all state files."""
    cfg_dir = _config_dir()
    if not cfg_dir.exists():
        print("Config directory does not exist yet. Nothing to back up.",
              file=sys.stderr)
        sys.exit(0)

    ts = _timestamp()
    backup_path = _backup_dir() / f"backup_{ts}"
    backup_path.mkdir(parents=True, exist_ok=True)

    backed_up: list[str] = []
    missing: list[str] = []

    for rel in _STATE_FILES:
        src = cfg_dir / rel
        dst = backup_path / rel
        if not src.exists():
            missing.append(rel)
            continue
        if _is_sqlite(src):
            _backup_db(src, dst)
        else:
            _backup_file(src, dst)
        backed_up.append(rel)

    # Write metadata
    meta = {
        "timestamp": ts,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "files_backed_up": backed_up,
        "files_missing": missing,
    }
    (backup_path / "backup_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Backup created: {backup_path}", file=sys.stderr)
    if backed_up:
        print(f"  Files backed up: {len(backed_up)}", file=sys.stderr)
    if missing:
        print(f"  Files not found (skipped): {len(missing)}", file=sys.stderr)
    sys.exit(0)


def restore_main() -> None:
    """Restore state from a backup."""
    parser = argparse.ArgumentParser(
        prog="restore-state",
        description="Restore backlink-publisher state from a backup.",
    )
    parser.add_argument(
        "backup", nargs="?",
        help="Backup name/timestamp to restore from (use --list to see available)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available backups",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    if args.list:
        backups = _find_backups()
        if not backups:
            print("No backups found.", file=sys.stderr)
            sys.exit(0)
        print(f"Available backups ({len(backups)}):", file=sys.stderr)
        for bp in backups:
            meta_file = bp / "backup_meta.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                n_files = len(meta.get("files_backed_up", []))
                print(f"  {bp.name}  ({n_files} files, {meta.get('created_utc', '?')})",
                      file=sys.stderr)
            else:
                print(f"  {bp.name}", file=sys.stderr)
        sys.exit(0)

    if not args.backup:
        parser.print_help()
        sys.exit(1)

    # Find the backup
    backups = _find_backups()
    target: Path | None = None
    for bp in backups:
        if bp.name == args.backup or bp.name == f"backup_{args.backup}":
            target = bp
            break

    if target is None:
        print(f"Backup {args.backup!r} not found. Use --list to see available backups.",
              file=sys.stderr)
        sys.exit(1)

    # Validate backup integrity
    meta_file = target / "backup_meta.json"
    if not meta_file.exists():
        print(f"Backup {target.name} is missing backup_meta.json — may be corrupted.",
              file=sys.stderr)
        print("Refusing to restore.", file=sys.stderr)
        sys.exit(1)

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    backed_up_files = meta.get("files_backed_up", [])

    # Confirm
    cfg_dir = _config_dir()
    print(f"Restoring from backup: {target.name}", file=sys.stderr)
    print(f"  Will restore {len(backed_up_files)} file(s) to {cfg_dir}",
          file=sys.stderr)
    for rel in backed_up_files:
        print(f"    {rel}", file=sys.stderr)

    if not args.yes:
        try:
            resp = input("Continue with restore? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            resp = "n"
        if resp != "y":
            print("Restore cancelled.", file=sys.stderr)
            sys.exit(0)

    # Pre-restore snapshot
    pre_snapshot = _backup_dir() / f"pre_restore_{_timestamp()}"
    pre_snapshot.mkdir(parents=True, exist_ok=True)
    for rel in backed_up_files:
        src = cfg_dir / rel
        if src.exists():
            if _is_sqlite(src):
                _backup_db(src, pre_snapshot / rel)
            else:
                _backup_file(src, pre_snapshot / rel)

    # Restore
    restored = 0
    for rel in backed_up_files:
        src = target / rel
        dst = cfg_dir / rel
        if not src.exists():
            print(f"  WARNING: {rel} missing in backup, skipping", file=sys.stderr)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if _is_sqlite(src):
            _backup_db(src, dst)
        else:
            shutil.copy2(src, dst)
        restored += 1

    print(f"Restored {restored} file(s) from {target.name}", file=sys.stderr)
    print(f"Pre-restore snapshot saved to {pre_snapshot}", file=sys.stderr)
    print("You may need to restart the WebUI for changes to take effect.",
          file=sys.stderr)
    sys.exit(0)
