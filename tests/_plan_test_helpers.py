"""Shared test helpers for plan-backlinks test files.

Extracted from ``test_plan_backlinks.py`` so split test files don't duplicate
the helper code. Import:

    from _plan_test_helpers import _stderr_without_warnings, _run_plan
"""
from __future__ import annotations

import json
from io import StringIO
import sys
from typing import Any

from backlink_publisher.cli.plan_backlinks import main


_BANNER_PREFIXES = (
    "[plan-backlinks] effective config:",
    "[validate-backlinks] effective config:",
    "[publish-backlinks] effective config:",
    "[report-anchors] effective config:",
    "  config:",
    "  env:",
    "  platforms:",
    "  sha:",
)


def _stderr_without_warnings(stderr: str) -> str:
    """Strip benign WARN + RECON + config-banner log lines so tests can
    assert on real errors only.

    RECON is the always-on Silent-Drop Tripwire reconciliation event emitted
    at end-of-run regardless of --log-level. WARN lines are anchor-keyword
    fallback notices and similar advisory signals. The config banner
    (Round-3 #7) is operator-orientation noise emitted at the start of
    each CLI invocation."""
    lines = [
        line for line in stderr.splitlines()
        if line
        and '"level": "WARN"' not in line
        and '"level": "RECON"' not in line
        and not any(line.startswith(p) for p in _BANNER_PREFIXES)
    ]
    return "\n".join(lines)


def _run_plan(
    input_data: str,
    argv: list[str] | None = None,
) -> tuple[str, str, int]:
    """Run plan-backlinks with given stdin data. Returns (stdout, stderr, exit_code)."""
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdin = StringIO(input_data)
        out = StringIO()
        err = StringIO()
        sys.stdout = out
        sys.stderr = err
        try:
            main(argv or [])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return out.getvalue(), err.getvalue(), code
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def _make_seed(
    target_url: str = "https://example.com/article",
    main_domain: str = "https://example.com",
    language: str = "en",
    platform: str = "medium",
    url_mode: str = "A",
    publish_mode: str = "draft",
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal seed dict with sensible defaults."""
    seed: dict[str, Any] = {
        "target_url": target_url,
        "main_domain": main_domain,
        "language": language,
        "platform": platform,
        "url_mode": url_mode,
        "publish_mode": publish_mode,
    }
    seed.update(extra)
    return seed
