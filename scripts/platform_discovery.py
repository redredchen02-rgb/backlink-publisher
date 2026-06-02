"""platform-discovery — SERP → HTTP probe → browser-UA rel scan → candidate JSONL.

Discovers new dofollow-capable platforms by:
  1. Fetching search results from DuckDuckGo HTML (no API key required)
  2. Probing each candidate URL with the HTTP-tier probe (via http_probe.probe_url)
  3. Fetching one public post page with a browser UA and scoring dofollow rate

stdout = one JSONL line per candidate.
stderr = progress summary.
exit 0 always — advisory, read-only.

SSRF guard: **fail-closed** (Track B). Machine-sourced URLs from SERP must be
SSRF-guarded. If the guard cannot be imported, this script exits non-zero.

Usage:
  python scripts/platform_discovery.py --queries queries.toml
  python scripts/platform_discovery.py --candidate-urls urls.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests

# Track B fail-closed: SSRF guard must be available.
try:
    from backlink_publisher._util.net_safety import _check_url_for_ssrf as _check_url_for_ssrf
except ImportError:
    print(
        "platform_discovery.py requires the backlink_publisher package with SSRF guard.\n"
        "Install it with: pip install -e '.[dev]'\n"
        "SSRF guard is mandatory for machine-sourced URL discovery (Track B fail-closed).",
        file=sys.stderr,
    )
    sys.exit(1)

# Probe core: hard import — must be installed.
try:
    from backlink_publisher._util.http_probe import probe_url, BROWSER_UA
    from backlink_publisher.publishing.registry import registered_platforms, dofollow_status
    import backlink_publisher.publishing.adapters  # noqa: F401  populate registry
except ImportError as exc:
    print(
        f"platform_discovery.py requires the backlink_publisher package.\n"
        f"Install it with: pip install -e '.[dev]'\n"
        f"Import error: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Regex constants (copied from link_attr_verifier.py — import chain not stdlib-only) ──
_A_TAG_RE = re.compile(r"<a\s[^>]*>", re.IGNORECASE)
_REL_VALUE_RE = re.compile(r'\brel\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_HREF_VALUE_RE = re.compile(
    r'\bhref\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.IGNORECASE
)
_NOFOLLOW_TOKENS = frozenset({"nofollow", "ugc", "sponsored"})

_SERP_RATE_LIMIT_S = 2.0
_TIMEOUT = 15
_DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"


def _sleep(seconds: float) -> None:
    """Monkeypatchable sleep seam."""
    if seconds > 0:
        time.sleep(seconds)


def _is_registered(url: str) -> bool:
    """True if the URL's hostname matches any registered platform."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    platforms = registered_platforms()
    # Simple heuristic: check if hostname suffix matches any platform's known domain.
    # We don't have a hostname→platform map, so we check the URL itself against
    # known platform domains via dofollow_status lookups. For discovery, we skip
    # URLs whose netloc appears in the set of registered platform names.
    for platform in platforms:
        if platform in host or host.endswith(f".{platform}.com") or host == f"{platform}.com":
            return True
    return False


def _ssrf_check_url(url: str) -> Optional[str]:
    """Return block reason if SSRF-dangerous, else None."""
    return _check_url_for_ssrf(url)


def _fetch_duckduckgo(query: str, max_results: int) -> list[str]:
    """Fetch candidate URLs from DuckDuckGo HTML interface.

    Returns up to max_results unique candidate URLs. Returns [] on failure.
    """
    try:
        resp = requests.get(
            _DUCKDUCKGO_URL,
            params={"q": query},
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "text/html,*/*",
            },
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"WARNING: DuckDuckGo fetch failed for query {query!r}: {exc}", file=sys.stderr)
        print(
            "Tip: use --candidate-urls <file> as fallback if DuckDuckGo is unavailable.",
            file=sys.stderr,
        )
        return []

    # Extract result URLs from DuckDuckGo HTML result anchors.
    # DuckDuckGo HTML results use class="result__url" or href containing the URL.
    # We use a conservative regex to extract href values from result anchors.
    html = resp.text
    if not html.strip():
        print(
            f"WARNING: DuckDuckGo returned empty response for query {query!r}. "
            "Use --candidate-urls fallback if this persists.",
            file=sys.stderr,
        )
        return []

    # Extract URLs from result__url spans (text content) and result links.
    urls: list[str] = []
    # Pattern: <a class="result__url" href="...">
    url_pattern = re.compile(
        r'<a[^>]+class=["\'][^"\']*result__url[^"\']*["\'][^>]*href=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    for m in url_pattern.finditer(html):
        u = m.group(1).strip()
        if u.startswith(("http://", "https://")) and u not in urls:
            urls.append(u)
        if len(urls) >= max_results:
            break

    # Fallback: extract from uddg= redirect URLs in DuckDuckGo's result links.
    if not urls:
        uddg_pattern = re.compile(r'href=["\']//duckduckgo\.com/l/\?uddg=([^&"\']+)', re.IGNORECASE)
        from urllib.parse import unquote
        for m in uddg_pattern.finditer(html):
            u = unquote(m.group(1)).strip()
            if u.startswith(("http://", "https://")) and u not in urls:
                urls.append(u)
            if len(urls) >= max_results:
                break

    if not urls:
        print(
            f"WARNING: No candidate URLs extracted for query {query!r}. "
            "DuckDuckGo response format may have changed. "
            "Use --candidate-urls <file> as fallback.",
            file=sys.stderr,
        )

    return urls[:max_results]


def _extract_cross_domain_anchors(html: str, page_url: str) -> tuple[int, int]:
    """Return (dofollow_count, cross_domain_count) from page HTML.

    Excludes same-domain links. Counts cross-domain <a> tags with and without
    nofollow/ugc/sponsored rel tokens.
    """
    try:
        page_host = urlparse(page_url).hostname or ""
    except Exception:
        page_host = ""

    dofollow = 0
    total_cross = 0

    for tag in _A_TAG_RE.findall(html):
        # Extract href
        href_m = _HREF_VALUE_RE.search(tag)
        if not href_m:
            continue
        href = (href_m.group(1) or href_m.group(2) or href_m.group(3) or "").strip()
        if not href.startswith(("http://", "https://")):
            continue

        try:
            link_host = urlparse(href).hostname or ""
        except Exception:
            continue

        # Skip same-domain
        if link_host == page_host or not link_host:
            continue

        total_cross += 1

        # Parse rel tokens
        rel_m = _REL_VALUE_RE.search(tag)
        rel_tokens = set(rel_m.group(1).lower().split()) if rel_m else set()
        if not rel_tokens.intersection(_NOFOLLOW_TOKENS):
            dofollow += 1

    return dofollow, total_cross


def _score_candidate(url: str, min_sample_size: int) -> dict:
    """B4: fetch one public post page with browser UA and score dofollow rate."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": BROWSER_UA, "Accept": "text/html,*/*"},
            timeout=_TIMEOUT,
            allow_redirects=True,
        )
        bot_accessible = 200 <= resp.status_code < 300
        if not bot_accessible:
            return {"bot_accessible": False, "dofollow_rate": 0.0, "sample_size": 0,
                    "verdict": "needs-manual", "reason": f"http_{resp.status_code}"}

        dofollow, total = _extract_cross_domain_anchors(resp.text, url)
        if total < min_sample_size:
            return {"bot_accessible": True, "dofollow_rate": 0.0, "sample_size": total,
                    "verdict": "needs-manual", "reason": "insufficient_sample"}

        rate = dofollow / total
        if rate >= 0.8:
            verdict = "go"
        elif rate < 0.2:
            verdict = "no-go"
        else:
            verdict = "needs-manual"

        return {
            "bot_accessible": True,
            "dofollow_rate": round(rate, 3),
            "sample_size": total,
            "verdict": verdict,
            "reason": None,
        }

    except requests.RequestException as exc:
        return {"bot_accessible": False, "dofollow_rate": 0.0, "sample_size": 0,
                "verdict": "needs-manual", "reason": f"fetch_error:{type(exc).__name__}"}


def _probe_candidate(url: str, min_sample_size: int, platform_type: Optional[str]) -> Optional[dict]:
    """B3 + B4: probe a single candidate URL. Returns JSONL record or None to skip."""
    # Registered platform dedup
    if _is_registered(url):
        print(f"  skip (already registered): {url}", file=sys.stderr)
        return None

    # SSRF guard (fail-closed — guard always active in Track B)
    blocked = _ssrf_check_url(url)
    if blocked:
        print(f"  skip (ssrf-blocked:{blocked}): {url}", file=sys.stderr)
        return None

    # HTTP probe
    probe_result = probe_url(url)
    verdict_probe = probe_result["verdict"]

    probe_at = datetime.now(timezone.utc).isoformat()

    if verdict_probe == "no-go-unreachable":
        return None  # skip silently

    if verdict_probe == "needs-browser-tier":
        return {
            "url": url,
            "platform_type": platform_type,
            "bot_accessible": False,
            "dofollow_rate": None,
            "sample_size": 0,
            "verdict": "needs-manual",
            "reason": "needs-browser-tier",
            "probe_at": probe_at,
        }

    # needs-canary → B4
    scored = _score_candidate(url, min_sample_size)
    return {
        "url": url,
        "platform_type": platform_type,
        "bot_accessible": scored.get("bot_accessible", False),
        "dofollow_rate": scored.get("dofollow_rate"),
        "sample_size": scored.get("sample_size", 0),
        "verdict": scored["verdict"],
        "reason": scored.get("reason"),
        "probe_at": probe_at,
    }


def _load_queries_toml(path: str) -> list[tuple[str, Optional[str]]]:
    """Parse a TOML file with [[queries]] array. Returns [(query, platform_type), ...]."""
    import tomllib
    with open(path, "rb") as f:
        data = tomllib.load(f)
    queries = data.get("queries", [])
    result = []
    for q in queries:
        query_str = q.get("query", "").strip()
        platform_type = q.get("platform_type", None)
        if query_str:
            result.append((query_str, platform_type))
    return result


def _load_candidate_urls(path: str) -> list[tuple[str, Optional[str]]]:
    """Read candidate URLs from a plain-text file (one URL per line)."""
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            u = line.strip()
            if u and not u.startswith("#"):
                urls.append((u, None))
    return urls


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="platform-discovery",
        description=(
            "Discover dofollow-capable backlink platforms via SERP probing. "
            "stdout = JSONL candidates; stderr = progress; exit 0 always."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--queries",
        metavar="TOML_FILE",
        help="TOML file with [[queries]] array (each has 'query' + optional 'platform_type').",
    )
    source.add_argument(
        "--candidate-urls",
        metavar="URL_FILE",
        help="Plain-text file with one URL per line. Skips SERP, enters probe directly.",
    )
    parser.add_argument(
        "--max-per-query",
        type=int,
        default=20,
        metavar="N",
        help="Max candidate URLs per SERP query (default: 20).",
    )
    parser.add_argument(
        "--min-sample-size",
        type=int,
        default=5,
        metavar="N",
        help="Min cross-domain anchors required for dofollow_rate scoring (default: 5).",
    )
    parser.add_argument(
        "--log-level",
        default="WARN",
        metavar="LEVEL",
        help="Log verbosity (unused; reserved for future use).",
    )
    args = parser.parse_args(argv)

    # Collect candidates
    if args.candidate_urls:
        candidates = _load_candidate_urls(args.candidate_urls)
        print(f"Loaded {len(candidates)} candidate URLs from {args.candidate_urls}", file=sys.stderr)
    else:
        queries = _load_queries_toml(args.queries)
        print(f"Running {len(queries)} SERP queries...", file=sys.stderr)
        seen_urls: set[str] = set()
        candidates: list[tuple[str, Optional[str]]] = []
        for i, (query, platform_type) in enumerate(queries):
            if i > 0:
                _sleep(_SERP_RATE_LIMIT_S)
            print(f"  query [{i+1}/{len(queries)}]: {query!r}", file=sys.stderr)
            urls = _fetch_duckduckgo(query, args.max_per_query)
            for u in urls:
                if u not in seen_urls:
                    seen_urls.add(u)
                    candidates.append((u, platform_type))
        print(f"  {len(candidates)} unique candidates from SERP", file=sys.stderr)

    # Probe candidates
    results: list[dict] = []
    counts = {"go": 0, "no-go": 0, "needs-manual": 0, "skipped": 0}

    for i, (url, platform_type) in enumerate(candidates):
        print(f"  probing [{i+1}/{len(candidates)}]: {url}", file=sys.stderr)
        record = _probe_candidate(url, args.min_sample_size, platform_type)
        if record is None:
            counts["skipped"] += 1
            continue
        verdict = record.get("verdict", "needs-manual")
        counts[verdict] = counts.get(verdict, 0) + 1
        if record.get("reason") is None:
            del record["reason"]
        print(json.dumps(record))
        results.append(record)

    # RECON summary
    print(
        f"\nDiscovery complete: {len(results)} candidates probed "
        f"({counts['go']} go, {counts['no-go']} no-go, "
        f"{counts['needs-manual']} needs-manual, {counts['skipped']} skipped)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
