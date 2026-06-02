"""Channel reachability probe — GO/NO-GO triage before building an adapter.

Experimental developer tool — NOT part of the publishing pipeline.
Run via: python scripts/channel_probe.py <url> [<content_url> ...]

The deterministic, HTTP-only tier of channel analysis. For a candidate
backlink channel it answers the cheap questions before any code is written:

  - Does the site serve our verifier's *bot* user-agent, or 403 it?
    (If bots are 403'd, the real `link_attr_verifier` preflight fetch can
    never reach a verdict, and search engines likely can't index it either.)
  - Is content behind a login wall (redirect to /login, password form)?
  - Is it a Cloudflare/WAF JS-challenge that only a real browser passes?

It probes each URL with three user-agents — the project's REAL preflight UA
(imported live so it never drifts), a Googlebot UA, and a desktop-browser UA —
and emits a triage verdict. The HTTP tier CANNOT see JS-rendered content or
extract outbound <a rel> link attributes; when the site is reachable-but-gated
it emits ``needs-browser-tier`` and the exact checks the browser step must run
(the `channel-probe` skill drives that step + the final dofollow verdict).

This mirrors the spike-script convention (`*_spike.py`, `*_diagnose.py`):
read-only, no config writes, JSON-or-human output, advisory.

SSRF safety (R14, funnel-brainstorm 2026-06-01): every URL — including each
redirect hop — is validated via net_safety._check_url_for_ssrf before fetch.
This guard MUST remain in place before the script is ever driven on
machine-sourced candidate lists (SERP / LLM / family-enum). Probe core lives
in backlink_publisher._util.http_probe; this script is a thin CLI wrapper.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Optional

# Hard import: probe core lives in the installed package.
# If the package is not installed, exit 1 with install instructions.
try:
    from backlink_publisher._util.http_probe import (
        BROWSER_UA,
        GOOGLEBOT_UA,
        Hit,  # noqa: F401  re-exported for test compat
        UrlResult,
        USER_AGENTS,
        _PREFLIGHT_UA,
        _SSRF_GUARD_ACTIVE,
        _probe,
        _triage,
        _validate_url_ssrf,  # noqa: F401  re-exported for test compat
        # _ssrf_check is NOT re-exported; tests must patch http_probe._ssrf_check
    )
except ImportError:
    print(
        "channel_probe.py requires the backlink_publisher package.\n"
        "Install it with: pip install -e '.[dev]'",
        file=sys.stderr,
    )
    sys.exit(1)


_VERDICT_NOTE = {
    "no-go-unreachable": (
        "NO-GO candidate: the channel does not serve our verifier and is not "
        "reachable in a way the pipeline can use. Record in "
        "docs/notes/retired-platforms/."
    ),
    "needs-browser-tier": (
        "INCONCLUSIVE over HTTP: reachable only by a JS browser and/or "
        "login-gated. Run the browser tier (see next_checks) before deciding. "
        "If bots are 403'd, search-engine indexation — and thus SEO value — is "
        "in doubt."
    ),
    "needs-canary": (
        "PLAUSIBLE: HTTP-reachable. Confirm a real dofollow backlink surface "
        "via the browser tier + a live pipeline canary before register()."
    ),
}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "urls", nargs="+", help="Homepage + optional content/post URL(s) to probe."
    )
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = ap.parse_args(argv)

    if not _SSRF_GUARD_ACTIVE:
        print(
            "WARNING: SSRF guard inactive (backlink_publisher package not installed). "
            "Use only with hand-curated, trusted URLs.",
            file=sys.stderr,
        )

    results: list[UrlResult] = []
    for url in args.urls:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        r = UrlResult(url=url)
        for ua_key, ua in USER_AGENTS.items():
            r.hits.append(_probe(url, ua_key, ua))
        results.append(r)

    verdict, signals, next_checks = _triage(results)
    payload = {
        "preflight_ua": _PREFLIGHT_UA,
        "ssrf_guard_active": _SSRF_GUARD_ACTIVE,
        "results": [asdict(r) for r in results],
        "signals": signals,
        "verdict": verdict,
        "verdict_note": _VERDICT_NOTE[verdict],
        "next_checks": next_checks,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    # Human-readable
    print(f"Channel probe — preflight UA: {_PREFLIGHT_UA}\n")
    if not _SSRF_GUARD_ACTIVE:
        print("⚠  SSRF guard inactive — use only with trusted, hand-curated URLs.\n")
    for r in results:
        print(f"  {r.url}")
        for h in r.hits:
            if h.error:
                print(f"    [{h.ua:<13}] ERROR {h.error}")
                continue
            tags = []
            if h.looks_cloudflare:
                tags.append("CF-challenge")
            if h.looks_login_wall:
                tags.append("login-wall")
            if h.redirected:
                tags.append(f"→ {h.final_url}")
            suffix = ("  " + " ".join(tags)) if tags else ""
            print(f"    [{h.ua:<13}] HTTP {h.status}  ({h.body_len}B){suffix}")
        print()
    if signals:
        print("Signals:")
        for s in signals:
            print(f"  • {s}")
        print()
    print(f"VERDICT: {verdict}")
    print(f"  {_VERDICT_NOTE[verdict]}\n")
    print("Browser-tier checks still required:")
    for c in next_checks:
        print(f"  → {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
