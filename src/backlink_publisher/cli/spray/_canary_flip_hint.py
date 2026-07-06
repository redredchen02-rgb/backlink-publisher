"""canary-seed flip-hint formatter — Plan 2026-06-05-011 Unit 1.

Pure functions that turn a canary verdict into a stderr-only human-readable summary
plus a guided edit checklist for the operator's *manual* ``dofollow=`` flip. No I/O,
no source mutation (A5). All platform-derived text is rendered source/terminal safe.

The formatter only sees the verdict receipt fields (``platform``, ``verdict``,
``post_url``, ``rel_tokens``) — it cannot reconstruct the full ``register(...)`` line
(adapter class, ``**<PLATFORM>_MANIFEST`` splat, ``visibility=`` …), so it emits the
``dofollow=`` value to set plus a checklist of changes, naming other kwargs as
"leave unchanged". It is a guided checklist, not a literal full-line paste.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse, urlunparse

# Populate the adapter registry so registered_platforms() has data.
import backlink_publisher.publishing.adapters  # noqa: F401
from backlink_publisher.publishing.registry import registered_platforms

# ANSI CSI escapes + C0/C1 control chars (incl. ESC, NUL, DEL, and the single-byte
# CSI introducer \x9b that some terminals honour like ESC-[).
_CONTROL_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_VERDICT_LABEL = {"dofollow": "DOFOLLOW", "nofollow": "NOFOLLOW", "ambiguous": "AMBIGUOUS"}


def _safe(text: object) -> str:
    """Strip ANSI escapes + C0/C1 control chars + line separators from platform text.

    Prevents terminal spoofing / fake-line injection in the stderr the operator
    reads and copies from. Covers ESC-CSI, C0/DEL, C1 (incl. \\x9b), \\n/\\r, and
    the Unicode line/paragraph separators U+2028/U+2029 (NEL \\x85 is in the C1 range).
    """
    flat = _CONTROL_RE.sub("", str(text))
    for _sep in ("\n", "\r", "\u2028", "\u2029"):
        flat = flat.replace(_sep, " ")
    return flat


def _normalize_url(url: str) -> str:
    """Keep scheme+host+path only — drop userinfo, query, params, and fragment.

    Stops credentials/session tokens in draft/preview URLs from leaking into stderr.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if ":" in host:  # IPv6 literal — re-wrap the brackets that .hostname drops
            host = f"[{host}]"
        if parsed.port:  # .port raises ValueError on a malformed authority
            host = f"{host}:{parsed.port}"
        return _safe(urlunparse((parsed.scheme, host, parsed.path, "", "", "")))
    except ValueError:
        return ""  # fail closed — never leak the raw (possibly credential-bearing) URL


def _lit(value: str) -> str:
    """Render a string as a source-safe Python literal (quotes/escapes neutralized)."""
    return json.dumps(_safe(value))


def _summary_line(platform: str, verdict: str, post_url: str, rel_tokens: list[str] | None) -> str:
    label = _VERDICT_LABEL.get(verdict, _safe(verdict).upper())
    rel = ", ".join(_safe(t) for t in (rel_tokens or [])) or "(none)"
    url = _normalize_url(post_url) or "(no post url)"
    return f"  {_safe(platform)} → {label}   (rel: {rel}; post: {url})"


def format_canary_hint(
    platform: str,
    verdict: str,
    post_url: str,
    rel_tokens: list[str] | None,
    *,
    reason: str | None = None,
    date: str | None = None,
) -> str:
    """Return the stderr summary + guided edit checklist for one canary verdict."""
    lines = [_summary_line(platform, verdict, post_url, rel_tokens)]

    if verdict == "ambiguous":
        if reason:
            lines.append(
                f"    reason: {_safe(reason)} — stays dofollow=\"uncertain\"; no edit."
            )
        return "\n".join(lines)

    if platform not in registered_platforms():
        lines.append(
            f"    WARNING: unknown platform {_lit(platform)} not in the registry — "
            "no edit checklist offered."
        )
        return "\n".join(lines)

    pj = _lit(platform)
    lines.append(f"    EDIT register({pj}, …) in publishing/adapters/__init__.py:")
    if verdict == "dofollow":
        stamp = f" {_safe(date)}" if date else ""
        lines += [
            "      - set   dofollow=True",
            f"      - delete kwarg   rationale=_R[{pj}]",
            "      - delete kwarg   referral_value=...",
            f"      - delete the   _R[{pj}]   entry in adapters/_nofollow_rationales.py",
            f"      - update inline comment ->   # OUR canary{stamp}: dofollow confirmed",
            "      - leave all other kwargs unchanged "
            "(adapter class, **<PLATFORM>_MANIFEST, visibility=, ...)",
            f"      - add a regression test asserting dofollow_status({pj}) is True",
            "    WARNING single canary - re-run to confirm before editing "
            "(a false dofollow misroutes real dispatch volume).",
        ]
    elif verdict == "nofollow":
        lines += [
            "      - set   dofollow=False",
            "      - leave rationale= / referral_value= as-is (still required while not True).",
        ]
    return "\n".join(lines)
