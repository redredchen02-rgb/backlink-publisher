#!/usr/bin/env python3
"""One-time backfill: mark checkpoint items with empty published_url as unverified.

Before the B1 fix (_do_verify returning False for empty URLs), publishes that
returned an empty published_url + draft_url were recorded as verified=True in
the checkpoint file. This script finds those stale records and sets verified=False
so --resume re-emits them with the correct _unverified suffix.

Usage:
    python scripts/backfill_empty_url_checkpoints.py            # dry-run (default)
    python scripts/backfill_empty_url_checkpoints.py --apply    # write changes
    python scripts/backfill_empty_url_checkpoints.py --dir /custom/cache/path

Exit codes:
    0 — success (no stale records, or --apply completed)
    1 — error reading/writing checkpoint files
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path


def _default_cache_dir() -> Path:
    override = os.environ.get("BACKLINK_PUBLISHER_CACHE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "backlink-publisher"
    return Path.home() / ".cache" / "backlink-publisher"


def _checkpoint_dir(cache_dir: Path) -> Path:
    return cache_dir / "checkpoints"


def _is_stale(item: dict) -> bool:
    """True when an item was recorded as verified but has no URL to back that up."""
    if item.get("status") != "done":
        return False
    if not item.get("verified", False):
        return False
    url = item.get("published_url") or ""
    return not url.strip()


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".bp-backfill-")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def run(cache_dir: Path, apply: bool) -> int:
    ckpt_dir = _checkpoint_dir(cache_dir)
    if not ckpt_dir.exists():
        print(f"No checkpoint directory found at {ckpt_dir}. Nothing to do.")
        return 0

    json_files = sorted(ckpt_dir.glob("*.json"))
    if not json_files:
        print("No checkpoint files found. Nothing to do.")
        return 0

    total_stale = 0
    errors = 0

    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"ERROR reading {path.name}: {exc}", file=sys.stderr)
            errors += 1
            continue

        stale_items = [i for i in data.get("items", []) if _is_stale(i)]
        if not stale_items:
            continue

        total_stale += len(stale_items)
        for item in stale_items:
            marker = "[DRY-RUN]" if not apply else "[FIXED]"
            print(
                f"{marker} {path.name} | id={item.get('id', '?')} | "
                f"platform={item.get('platform', '?')} | "
                f"completed_at={item.get('completed_at', '?')} | "
                f"published_url={item.get('published_url')!r}"
            )

        if apply:
            for item in stale_items:
                item["verified"] = False
            try:
                _atomic_write_json(path, data)
            except Exception as exc:
                print(f"ERROR writing {path.name}: {exc}", file=sys.stderr)
                errors += 1

    if total_stale == 0:
        print("No stale records found.")
    else:
        action = "would fix" if not apply else "fixed"
        print(f"\nTotal: {action} {total_stale} stale record(s) across {len(json_files)} file(s).")
        if not apply:
            print("Re-run with --apply to write changes.")

    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill empty-URL checkpoint items: set verified=False."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes. Default is dry-run (list only).",
    )
    parser.add_argument(
        "--dir",
        metavar="PATH",
        help="Override cache directory (default: ~/.cache/backlink-publisher).",
    )
    args = parser.parse_args()

    cache_dir = Path(args.dir) if args.dir else _default_cache_dir()
    sys.exit(run(cache_dir, apply=args.apply))


if __name__ == "__main__":
    main()
