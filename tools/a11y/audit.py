#!/usr/bin/env python3
"""Accessibility audit for changed WebUI routes — axe-core via Playwright.

No-build harness (honours the repo's "no Node/bundler" rule):
  * vendored ``tools/a11y/vendor/axe.min.js`` is injected into a headless
    Chromium (already installed for Playwright)
  * the Flask app is booted in-process and served on an ephemeral port
  * each target route is audited with the real DOM + CSS (so colour-contrast,
    a "serious" check, is evaluated against computed styles)

Gate: any violation whose ``impact`` is ``serious`` or ``critical`` fails the
run (exit 1). A page that cannot be audited at all also fails (exit 1).

Not wired into CI (needs browser binaries) — run via ``make test-a11y``,
mirroring the existing opt-in ``real_browser`` smoke targets.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

# tools/a11y/audit.py -> backlink-publisher/
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

AXE_PATH = Path(__file__).resolve().parent / "vendor" / "axe.min.js"

# Routes that render the UI files changed in this branch. Keep in sync with the
# changed templates/CSS — this is the "changed routes" the audit loop targets.
TARGET_ROUTES = [
    ("/ce:command-center", "command_center.html"),
    ("/ce:health", "health.html"),
    ("/ce:keep-alive", "keep_alive.html"),
    ("/survival-dashboard", "survival_dashboard.html"),
    ("/settings", "settings.html (+ settings.css)"),
]

# WCAG impact levels that fail the gate. Default = moderate+ — the changed
# routes are clean at this bar, so it locks that in and catches regressions.
# Relax with A11Y_FAIL_IMPACTS="serious,critical", or tighten by adding "minor".
# Levels below the gate are still reported, just not failed on.
FAIL_IMPACTS = {
    s.strip()
    for s in os.environ.get("A11Y_FAIL_IMPACTS", "moderate,serious,critical").split(",")
    if s.strip()
}
_GATE_LABEL = "/".join(sorted(FAIL_IMPACTS)) or "(nothing)"


def _make_app():
    from webui_app import create_app

    app = create_app()
    app.config["CSRF_ENABLED"] = False  # GET-only audit; matches test harness
    app.config["TESTING"] = True
    return app


def _serve(app):
    """Serve the app on an ephemeral loopback port in a daemon thread."""
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_port


def _audit(base_url):
    """Return a list of per-route findings: {route, label, violations|error}."""
    from playwright.sync_api import sync_playwright

    findings = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for route, label in TARGET_ROUTES:
            page = browser.new_page()
            try:
                page.goto(base_url + route, wait_until="load", timeout=30000)
                page.wait_for_timeout(800)  # let initial client-side render settle
                page.add_script_tag(path=str(AXE_PATH))
                result = page.evaluate(
                    "() => axe.run(document, {resultTypes: ['violations']})"
                )
                findings.append(
                    {"route": route, "label": label, "violations": result["violations"]}
                )
            except Exception as exc:  # audit failure must not be silently "clean"
                findings.append({"route": route, "label": label, "error": repr(exc)})
            finally:
                page.close()
        browser.close()
    return findings


def _report(findings):
    """Print a human-readable report; return (n_gated_violations, n_errors)."""
    n_gated = 0
    n_errors = 0
    for f in findings:
        route = f["route"]
        if "error" in f:
            n_errors += 1
            print(f"\n=== {route}  [AUDIT ERROR] ===")
            print(f"  ! {f['error']}")
            continue

        gated = [v for v in f["violations"] if v.get("impact") in FAIL_IMPACTS]
        minor = [v for v in f["violations"] if v.get("impact") not in FAIL_IMPACTS]
        status = "PASS" if not gated else f"FAIL ({len(gated)} gated)"
        print(f"\n=== {route}  [{status}]  ({f['label']}) ===")

        for v in gated:
            nodes = v.get("nodes", [])
            n_gated += len(nodes)
            print(f"  ✗ [{v['impact']}] {v['id']}: {v['help']}")
            print(f"     {v['helpUrl']}")
            for node in nodes[:8]:
                print(f"       @ {node.get('target')}")
                summary = (node.get("failureSummary") or "").replace("\n", " ")
                if summary:
                    print(f"         {summary[:240]}")
            if len(nodes) > 8:
                print(f"       … +{len(nodes) - 8} more node(s)")

        if minor:
            tags = ", ".join(sorted({f"{v['id']}({v['impact']})" for v in minor}))
            print(f"  · {len(minor)} below gate (report only): {tags}")
    return n_gated, n_errors


def main():
    os.environ.setdefault(
        "BACKLINK_PUBLISHER_CONFIG_DIR", tempfile.mkdtemp(prefix="a11y-cfg-")
    )
    os.environ.setdefault("BACKLINK_NO_FETCH_VERIFY", "1")
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    if not AXE_PATH.exists():
        print(f"FATAL: vendored axe-core missing at {AXE_PATH}", file=sys.stderr)
        return 2

    server, port = _serve(_make_app())
    try:
        findings = _audit(f"http://127.0.0.1:{port}")
    finally:
        server.shutdown()

    n_gated, n_errors = _report(findings)
    print("\n" + "=" * 64)
    if n_gated == 0 and n_errors == 0:
        print(f"a11y audit: PASS — 0 [{_GATE_LABEL}] violations on changed routes")
        return 0
    parts = []
    if n_gated:
        parts.append(f"{n_gated} [{_GATE_LABEL}] node(s)")
    if n_errors:
        parts.append(f"{n_errors} route(s) failed to audit")
    print(f"a11y audit: FAIL — " + "; ".join(parts))
    return 1


if __name__ == "__main__":
    sys.exit(main())
