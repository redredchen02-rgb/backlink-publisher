"""Grep gate: prevent new raw ``requests.*`` call sites outside the allowlist.

Why this exists
---------------
The unified client ``backlink_publisher._util.http_client.http_client`` enforces
SSRF protection (``_util/net_safety._check_url_for_ssrf`` — incl. cloud-metadata
169.254/16 blocking), a default timeout, retry, and a connection pool. Any module
that calls ``requests.get/post/put/patch/delete`` directly bypasses all of that.

A 2026-06-15 audit found ``webui_app/helpers/url_meta.py::_fetch_page`` fetching
operator-supplied preview URLs with ``requests.get(url, verify=False)`` and no
SSRF check — a real server-side-request-forgery vector on the WebUI preview path
(see ``docs/plans/2026-06-15-002-analysis-comprehensive-optimization-plan.md``
P1-1). That call site was migrated to ``http_client``; this test freezes the
win by failing on any *new* raw call site that isn't explicitly allowlisted here
with a written justification.

Allowlist policy
----------------
A raw ``requests.*`` call is allowlisted only when it has a concrete structural
reason the unified client cannot serve it — e.g. streaming with redirect
suppression, a localhost control plane, or a transport shim. "Convenience" or
"not yet migrated" is NOT a valid reason. Each entry carries the reason inline
so the diff that adds/removes one is self-reviewing.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

# Raw requests.* call sites that are intentionally NOT routed through http_client.
# Each value is the written justification. Edit this map ONLY when adding a new
# structurally-justified exception or removing a migrated one.
#
# Format: "relative/path.py:<lineno>" -> "reason"
ALLOWLIST: dict[str, str] = {
    # --- LLM proxy paths: stream=True + allow_redirects=False semantics that
    #     http_client's raise_for_status/retry contract would break. These guard
    #     operator API keys against redirect exfiltration; the bespoke redirect
    #     handling is the load-bearing behaviour, not a convenience.
    "src/backlink_publisher/llm/http_guard.py:103": (
        "LLM outbound guard: needs stream=True + allow_redirects=False to refuse "
        "redirects before any body is read; http_client follows redirects and "
        "raises on non-2xx, both incompatible with the redirect-rejection gate."
    ),
    # Note: chrome_backend.py uses self._requests (a Chrome DevTools session
    # object), NOT the top-level requests module, so the gate's regex never
    # matches it — no allowlist entry needed.
    # --- http_probe / http_client themselves: they ARE the SSRF-safe layer.
    #     (http_probe migrated to a module-level requests.Session — its former
    #     raw requests.get sites at :82/:102 no longer exist, entries removed.)
    # --- Form-POST publish path: structurally cannot use the shared http_client,
    #     because that client retries POSTs (would duplicate a non-idempotent live
    #     backlink) and retries 503 (which IS the anti-bot challenge signal this
    #     path must observe). SSRF — the one thing http_client would add — is
    #     enforced inline via _guard_ssrf(). Not a migration backlog item.
    "src/backlink_publisher/publishing/adapters/http_form_post.py:124": (
        "Form-GET whose 503/403 status IS the anti-bot challenge signal "
        "(detect_challenge). http_client's urllib3 Retry has 503 in its "
        "status_forcelist, so it would retry then mask the 503 as an opaque "
        "error — the challenge would never be observed. SSRF is enforced inline "
        "via _guard_ssrf(); raw requests is required for challenge visibility."
    ),
    "src/backlink_publisher/publishing/adapters/http_form_post.py:189": (
        "Create-exactly-once form POST (non-idempotent; a retry risks a "
        "DUPLICATE live backlink — P2 fix). http_client retries POSTs on "
        "429/5xx + connection errors, which would violate that contract. SSRF "
        "is enforced inline via _guard_ssrf(); raw requests is required to keep "
        "the single-attempt + 503-challenge semantics."
    ),
    # --- LLM diagnostics _safe_get_json: stream=True + allow_redirects=False
    #     redirect-rejection gate, same structural rationale as http_guard.py:103.
    #     The redirect-bearing header would leak the api_key; http_client follows
    #     redirects and cannot provide the streaming content-type + size gate.
    "webui_app/api/llm_diagnostics_api.py:63": (
        "LLM diagnostics GET probe: needs stream=True + allow_redirects=False "
        "for redirect-rejection (Bearer exfiltration guard) and content-type/size "
        "checks before buffering; http_client follows redirects and buffers first."
    ),
}

# Regex matches a raw requests.<verb>( call site. ``self._requests`` (Chrome
# DevTools session) is intentionally NOT matched — it's a different object.
_RAW_CALL_RE = re.compile(r"\brequests\.(get|post|put|patch|delete)\s*\(")

# Scan these roots only — never tests/ (tests legitimately mock requests).
_SCAN_ROOTS = ("src", "webui_app", "webui_store")


def _find_raw_call_sites() -> list[tuple[str, int]]:
    """Return [(relative_path, lineno)] for every raw requests.* call site."""
    sites: list[tuple[str, int]] = []
    for root in _SCAN_ROOTS:
        for py in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(REPO_ROOT).as_posix()  # stable across OSes
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                # Skip commented-out lines and self._requests (DevTools session).
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "_requests." in line:
                    continue
                if _RAW_CALL_RE.search(line):
                    sites.append((rel, i))
    return sites


def test_no_new_raw_requests_call_sites() -> None:
    """Every raw requests.* call must be in ALLOWLIST with a written reason.

    Adding a raw call site without allowlisting it fails this test — that is
    the point. To migrate an existing site to http_client, delete its ALLOWLIST
    entry in the same PR; the test then enforces that the migration stuck.
    """
    sites = _find_raw_call_sites()
    key_of = lambda p, ln: f"{p}:{ln}"  # noqa: E731
    found = {key_of(p, ln) for p, ln in sites}

    # 1. No site outside the allowlist.
    unlisted = sorted(found - set(ALLOWLIST))
    assert not unlisted, (
        "New raw requests.* call site(s) found that are not in the allowlist.\n"
        "Raw calls bypass SSRF protection, timeout, and retry enforced by "
        "backlink_publisher._util.http_client. Either migrate the call to "
        "http_client, or add it to ALLOWLIST in this test with a written "
        "structural reason.\nUnlisted sites:\n  " + "\n  ".join(unlisted)
    )

    # 2. No stale allowlist entries (a migrated site whose entry lingers).
    stale = sorted(set(ALLOWLIST) - found)
    assert not stale, (
        "ALLOWLIST contains entries with no matching raw call site — the call "
        "was probably migrated to http_client (good!) but the allowlist entry "
        "wasn't removed in the same PR. Delete these entries:\n  "
        + "\n  ".join(stale)
    )

    # 3. Every reason is non-trivial (>=40 chars) — forces a real justification.
    shallow = {k: v for k, v in ALLOWLIST.items() if len(v.strip()) < 40}
    assert not shallow, (
        "ALLOWLIST reason(s) too short (<40 chars) — each exception must "
        "explain the structural reason http_client cannot serve it:\n  "
        + "\n  ".join(f"{k}: {v!r}" for k, v in shallow.items())
    )


def test_allowlist_paths_resolve() -> None:
    """Every allowlisted path must point at a real file (catches typos)."""
    for key in ALLOWLIST:
        path_part = key.rsplit(":", 1)[0]
        assert (REPO_ROOT / path_part).exists(), (
            f"ALLOWLIST entry {key!r}: file {path_part!r} does not exist."
        )


if __name__ == "__main__":
    # Manual diagnostic: print current sites + allowlist status.
    sites = _find_raw_call_sites()
    print(f"Found {len(sites)} raw requests.* call sites:", file=sys.stderr)
    for p, ln in sorted(sites):
        status = "allowlisted" if f"{p}:{ln}" in ALLOWLIST else "UNLISTED"
        print(f"  {p}:{ln}  [{status}]", file=sys.stderr)
    sys.exit(0)
