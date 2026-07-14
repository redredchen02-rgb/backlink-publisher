"""Gate test: no orphan .py files in src/backlink_publisher/."""
__tier__ = "unit"

import os
import subprocess
import sys

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
    "cli/verify_backlinks.py",
    "config/parsers/click_track.py",
    "events/history_importer.py",
    "idempotency/_constants.py",
    "idempotency/_dedup_connection.py",
    "idempotency/_dedup_digest.py",
    "idempotency/_dedup_query.py",
    "idempotency/_schema.py",
    "publishing/_verify_adapters.py",
    "publishing/adapters/medium_auth.py",    # imported by webui_app/medium_login.py (outside src/ scan)
    "publishing/adapters/medium_liveness.py",
    "publishing/adapters/velog/auth.py",
    "publishing/adapters/velog/utils.py",
    # New opt-in modules (2026-06-05 optimization gaps)
    "_util/http_client.py",
    "_util/structlog_config.py",
    # U8 CLI shims (2026-06-26) — backward-compat re-exports from subdirs
    "cli/keepalive_run.py",
    "cli/keepalive_status.py",
    "cli/report_anchors.py",
    "cli/spray_backlinks/_gates.py",
    # U8 CLI shim (2026-07-07) — orphaned once cli/reporting/weights.py's
    # only remaining internal caller was repointed at the real
    # cli.reporting.show_optimization_state location (see the same PR's
    # mypy fix: the shim's static content is invisible to mypy's
    # attr-defined check, since the sys.modules aliasing only resolves at
    # runtime). Kept for the pyproject-adjacent/external legacy import path.
    "cli/show_optimization_state.py",
    # CLI boilerplate + formatting — imported dynamically
    "cli/_shared.py",
    "_util/cli_format.py",
    # sys.modules alias shim — referenced only via mock.patch dotted strings
    # in tests/test_dedup_enforce_gate.py, which the static scanner can't see.
    "cli/admin/_resume.py",
}


def test_no_orphan_code():
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True, text=True, cwd=os.path.dirname(SCRIPT),
    )
    orphans = [l.replace("\\", "/") for l in result.stdout.splitlines() if l.strip()]
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
