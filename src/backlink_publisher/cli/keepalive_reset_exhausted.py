"""keepalive-reset-exhausted — operator reset for a single exhausted target.

Removes a URL from the keepalive retry_counts store so it can be retried on
the next keepalive-run cycle.  Canonicalizes the URL before lookup so that
trailing-slash or encoding variants still match the stored key.

Exit codes:
  0 — URL was present and has been removed (or was already absent).
  2 — argument error.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="keepalive-reset-exhausted",
        description=(
            "Remove a URL from the keepalive exhausted list so it can be "
            "retried on the next keepalive-run cycle."
        ),
    )
    parser.add_argument("target_url", help="URL to remove from the exhausted list")
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Machine-readable JSON output on stdout",
    )
    args = parser.parse_args(argv)

    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.keepalive.run_state import KeepaliveRunState

    canonical = canonicalize_url(args.target_url.strip())
    rs = KeepaliveRunState()
    data = rs.load()
    was_present = canonical in data.get("retry_counts", {})
    rs.reset_exhausted(canonical)

    if args.as_json:
        print(json.dumps(
            {"status": "ok", "target_url": canonical, "was_present": was_present},
            ensure_ascii=False,
        ))
    else:
        verdict = "removed" if was_present else "not found (already clean)"
        print(f"keepalive-reset-exhausted: {canonical} — {verdict}", file=sys.stderr)
