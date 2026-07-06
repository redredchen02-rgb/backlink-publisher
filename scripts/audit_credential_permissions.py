#!/usr/bin/env python3
"""Audit credential file permissions in the backlink-publisher config directory.

Scans for token/state/cookie/credential JSON files and reports any that are
not mode 0600. Use ``--fix`` to automatically chmod them.

Usage:
    python scripts/audit_credential_permissions.py          # report only
    python scripts/audit_credential_permissions.py --fix    # report + fix
    python scripts/audit_credential_permissions.py --dir /custom/path

Exit codes:
    0 — all files are 0600 (or --fix succeeded)
    1 — non-0600 files found (report mode) or fix failed
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


# File patterns considered credential-bearing (path convention in AGENTS.md)
_CREDENTIAL_SUFFIXES = (
    "-storage-state.json",
    "-token.json",
    "-cookies.json",
    "-credentials.json",
)

_CREDENTIAL_NAMES = (
    "credentials.json",
    "channel-status.json",
    "canary-health.json",
)


def _config_dir() -> Path:
    env = os.environ.get("BACKLINK_PUBLISHER_CONFIG_DIR")
    if env:
        return Path(env)
    return Path.home() / ".config" / "backlink-publisher"


def _is_credential_file(path: Path) -> bool:
    name = path.name
    if name in _CREDENTIAL_NAMES:
        return True
    return any(name.endswith(suffix) for suffix in _CREDENTIAL_SUFFIXES)


def _file_mode(path: Path) -> int:
    """Return the file permission bits (lower 9 bits)."""
    return stat.S_IMODE(path.stat().st_mode) & 0o777


def audit(config_dir: Path, *, fix: bool = False) -> list[tuple[Path, int]]:
    """Scan config_dir for credential files with non-0600 permissions.

    Returns a list of (path, current_mode) tuples for offending files.
    When ``fix=True``, also chmod them to 0600.
    """
    violations: list[tuple[Path, int]] = []

    if not config_dir.exists():
        print(f"Config directory does not exist: {config_dir}", file=sys.stderr)
        return violations

    for entry in sorted(config_dir.rglob("*.json")):
        if not _is_credential_file(entry):
            continue
        if not entry.is_file():
            continue
        mode = _file_mode(entry)
        if mode != 0o600:
            violations.append((entry, mode))
            if fix:
                try:
                    entry.chmod(0o600)
                    print(f"  FIXED  {entry}  {oct(mode)} → 0o600")
                except OSError as exc:
                    print(f"  FAIL   {entry}  chmod failed: {exc}", file=sys.stderr)

    return violations


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit credential file permissions in backlink-publisher config dir."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help=f"Config directory (default: $BACKLINK_PUBLISHER_CONFIG_DIR or {_config_dir()})",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically chmod non-0600 files to 0600",
    )
    args = parser.parse_args()

    config_dir = args.dir if args.dir else _config_dir()
    print(f"Scanning: {config_dir}")

    violations = audit(config_dir, fix=args.fix)

    if not violations:
        print("✅ All credential files are 0600.")
        sys.exit(0)

    if args.fix:
        # Re-check after fix
        remaining = audit(config_dir, fix=False)
        if remaining:
            print(f"\n❌ {len(remaining)} file(s) could not be fixed.", file=sys.stderr)
            sys.exit(1)
        print(f"\n✅ Fixed {len(violations)} file(s).")
        sys.exit(0)

    # Report mode
    print(f"\n⚠️  {len(violations)} credential file(s) with non-0600 permissions:")
    for path, mode in violations:
        print(f"  {oct(mode)}  {path}")
    print(f"\nRun with --fix to automatically chmod to 0600.")
    sys.exit(1)


if __name__ == "__main__":
    main()