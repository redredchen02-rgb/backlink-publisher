"""HTTP reachability probe — shared core extracted from scripts/channel_probe.py.

Provides the ``probe_url()`` public function and lower-level ``_probe``/
``_triage`` internals used by both ``channel_probe.py`` (now a thin wrapper)
and ``scripts/platform_discovery.py``.

SSRF guard is **fail-closed**: import failure raises ``RuntimeError`` rather
than silently allowing unguarded requests.  ``_SSRF_GUARD_ACTIVE`` remains
as a diagnostic flag but is always True in practice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests

# SSRF guard — fail-closed: import failure is a hard error, not a silent bypass.
from backlink_publisher._util.net_safety import _check_url_for_ssrf as _ssrf_check

_SSRF_GUARD_ACTIVE = True

# Real verifier UA imported live so probes match what the pipeline's
# link_attr_verifier preflight fetch actually sends.
# P14 A5: imported from _util.constants instead of content._preflight_fetch.
try:
    from backlink_publisher._util.constants import PREFLIGHT_UA as _PREFLIGHT_UA
except ImportError:
    _PREFLIGHT_UA = "backlink-publisher/0.1 preflight-targets"

GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

USER_AGENTS = {
    "preflight-bot": _PREFLIGHT_UA,
    "googlebot": GOOGLEBOT_UA,
    "browser": BROWSER_UA,
}

_CF_MARKERS = ("just a moment", "cf-chl", "attention required", "cloudflare")
_LOGIN_MARKERS = ('type="password"', "forgot password", "sign in to", "log in to")
_TIMEOUT = 20
_MAX_REDIRECTS = 10


@dataclass
class Hit:
    ua: str
    status: int | None
    final_url: str = ""
    redirected: bool = False
    server: str = ""
    body_len: int = 0
    looks_cloudflare: bool = False
    looks_login_wall: bool = False
    error: str = ""


@dataclass
class UrlResult:
    url: str
    hits: list[Hit] = field(default_factory=list)


def _validate_url_ssrf(url: str) -> str | None:
    """Return blocked reason if URL is SSRF-dangerous, else None."""
    return _ssrf_check(url)


def _probe(url: str, ua_key: str, ua: str) -> Hit:
    blocked = _validate_url_ssrf(url)
    if blocked:
        return Hit(ua=ua_key, status=None, error=f"ssrf-blocked:{blocked}")

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": ua, "Accept": "text/html,*/*"},
            timeout=_TIMEOUT,
            allow_redirects=False,
        )
        redirect_count = 0
        while resp.is_redirect and redirect_count < _MAX_REDIRECTS:
            next_url = resp.headers.get("Location", "").strip()
            if not next_url:
                break
            if not next_url.startswith(("http://", "https://")):
                next_url = urljoin(resp.url, next_url)
            blocked = _validate_url_ssrf(next_url)
            if blocked:
                return Hit(
                    ua=ua_key,
                    status=None,
                    error=f"ssrf-redirect-blocked:{blocked}",
                )
            resp = requests.get(
                next_url,
                headers={"User-Agent": ua, "Accept": "text/html,*/*"},
                timeout=_TIMEOUT,
                allow_redirects=False,
            )
            redirect_count += 1
    except requests.RequestException as exc:
        return Hit(ua=ua_key, status=None, error=f"{type(exc).__name__}: {exc}")

    body = resp.text[:20000].lower()
    final = resp.url
    login = (
        "/login" in final
        or "/signin" in final
        or any(m in body for m in _LOGIN_MARKERS)
    )
    cf = resp.status_code == 403 and (
        "cloudflare" in resp.headers.get("Server", "").lower()
        or any(m in body for m in _CF_MARKERS)
    )
    return Hit(
        ua=ua_key,
        status=resp.status_code,
        final_url=final,
        redirected=final.rstrip("/") != url.rstrip("/"),
        server=resp.headers.get("Server", ""),
        body_len=len(resp.content),
        looks_cloudflare=cf,
        looks_login_wall=login,
    )


def _triage(results: list[UrlResult]) -> tuple[str, list[str], list[str]]:
    """Return (verdict, signals, next_checks).

    Key correctness rule (learned dogfooding bloglovin): an HTTP 200 from a
    JS/SPA site proves nothing about content availability — ``requests`` does not
    run the client-side redirect, so a login-gated shell returns 200 with a
    full HTML bundle. Therefore a login-wall signal anywhere CAPS the verdict
    at ``needs-browser-tier``; only the browser tier can confirm a real,
    public, linkable surface.
    """
    all_hits = [h for r in results for h in r.hits]
    coded = [h for h in all_hits if h.status is not None]

    def _ua_2xx(key: str) -> bool:
        return any(h.ua == key and h.status and 200 <= h.status < 300 for h in all_hits)

    def _ua_only_403(key: str) -> bool:
        ks = [h for h in all_hits if h.ua == key and h.status is not None]
        return bool(ks) and all(h.status == 403 for h in ks)

    signals: list[str] = []
    preflight_2xx = _ua_2xx("preflight-bot")
    preflight_403 = _ua_only_403("preflight-bot")
    googlebot_403 = _ua_only_403("googlebot")
    browser_2xx = _ua_2xx("browser")
    any_2xx = any(h.status and 200 <= h.status < 300 for h in coded)
    any_login = any(h.looks_login_wall for h in all_hits)
    any_cf = any(h.looks_cloudflare for h in all_hits)

    if not coded:
        signals.append("No HTTP response from any UA (DNS/connection failure).")
    if preflight_2xx:
        signals.append("Our preflight verifier UA receives 2xx (HTTP-fetchable).")
    if preflight_403:
        signals.append(
            "Our preflight verifier UA is 403'd — link_attr_verifier cannot fetch this channel."
        )
    if googlebot_403 and not preflight_403:
        signals.append(
            "Googlebot UA hard-403'd while a generic UA passes — likely Cloudflare "
            "anti-spoofing (it verifies Googlebot by IP, not UA). The REAL Googlebot "
            "may or may not be blocked; confirm via the `site:` index check, do not assume."
        )
    if any_cf:
        signals.append("Cloudflare/WAF challenge detected (403 + CF markers).")
    if any_login:
        signals.append(
            "Login wall detected — an HTTP 200 here is a gated SPA shell, NOT proof of "
            "a public content surface. Browser tier required to see real content/links."
        )

    next_checks = [
        "Render a content/post page in a REAL browser (JS-capable). Does it "
        "pass the challenge, or hit a login wall?",
        "On the rendered page, extract ALL outbound <a href> + rel. Is there a "
        "real link to the source blog / target — and is it dofollow or nofollow?",
        "Google index: `site:<domain>` — are fresh dated content pages indexed, "
        "or only stale structural pages?",
    ]

    if not coded:
        return "no-go-unreachable", signals, next_checks
    if preflight_403 and not browser_2xx:
        return "no-go-unreachable", signals, next_checks
    if any_login:
        return "needs-browser-tier", signals, next_checks
    if preflight_403 and browser_2xx:
        return "needs-browser-tier", signals, next_checks
    if any_2xx:
        return "needs-canary", signals, next_checks
    return "needs-browser-tier", signals, next_checks


def probe_url(url: str) -> dict:
    """Probe a single URL with all three UAs and return a triage verdict.

    Return shape::

        {
            "verdict": "needs-canary" | "needs-browser-tier" | "no-go-unreachable",
            "signals": list[str],
            "next_checks": list[str],
            "ssrf_guard_active": bool,
        }
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    result = UrlResult(url=url)
    for ua_key, ua in USER_AGENTS.items():
        result.hits.append(_probe(url, ua_key, ua))
    verdict, signals, next_checks = _triage([result])
    return {
        "verdict": verdict,
        "signals": signals,
        "next_checks": next_checks,
        "ssrf_guard_active": _SSRF_GUARD_ACTIVE,
    }
