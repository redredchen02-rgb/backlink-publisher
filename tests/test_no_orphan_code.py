"""Gate test: no orphan .py files in src/backlink_publisher/."""
__tier__ = "unit"

import sys
import os
import subprocess

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "scan_orphan_code.py")

# Known orphan files that are intentionally kept.
# __main__.py files are python -m entry points (not regular imports).
# The remaining files are true orphans — consider removing them.
ALLOWLIST: set[str] = {
    # __main__.py — python -m entry points
    "cli/plan_backlinks/__main__.py",
    "cli/publish_backlinks/__main__.py",
    "cli/spray_backlinks/__main__.py",
    # True orphans — not imported by any code path
    "_util/http_session.py",
    "cli/verify_backlinks.py",
    "config/parsers/click_track.py",
    "events/history_importer.py",
    "idempotency/_constants.py",
    "idempotency/_dedup_connection.py",
    "idempotency/_dedup_digest.py",
    "idempotency/_dedup_query.py",
    "idempotency/_schema.py",
    "publishing/_verify_adapters.py",
    "publishing/adapters/medium_liveness.py",
    "publishing/adapters/velog/auth.py",
    "publishing/adapters/velog/utils.py",
}


def test_no_orphan_code():
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True, text=True, cwd=os.path.dirname(SCRIPT),
    )
    orphans = [l for l in result.stdout.splitlines() if l.strip()]
    if not orphans:
        return

    unlisted = [o for o in orphans if o not in ALLOWLIST]
    if unlisted:
        msg = (
            f"Found {len(unlisted)} orphan file(s) not in ALLOWLIST:\n"
            + "\n".join(f"  {u}" for u in unlisted)
            + "\n\n"
            + "If these are intentionally kept, add them to ALLOWLIST in this test. "
            + "Otherwise, remove them or wire them into an import chain.\n"
            + f"Also {len(orphans) - len(unlisted)} known orphan(s) in ALLOWLIST remain."
        )
        assert False, msg
