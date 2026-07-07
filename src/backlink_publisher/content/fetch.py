"""URL content-fetch gate for the backlink pipeline.

Verifies that a URL returns HTTP 200 and parses out a non-empty ``<title>`` or
``og:title`` element before the URL is allowed into a published backlink
article. Catches the failure class generalised by PR #19 / plan
``docs/plans/2026-05-14-007-feat-url-content-fetch-gate-plan.md``: synthesized
or stale URLs that look reachable to the HEAD-only ``linkcheck.check_url`` but
serve a 4xx, soft empty body, CAPTCHA interstitial, or Cloudflare challenge
page on full GET.

Sibling to ``linkcheck`` (reachability only) and ``work_scraper`` (deeper
scrape with SSRF defence). Not a replacement for either — this module is
deliberately the smallest "real GET + title check" surface and stays
process-scope in-memory only.

Public surface
--------------
- :func:`verify_url_has_content` — single URL check with retry, returns
  ``(ok, reason, title)``.
- :func:`verify_urls_batch` — concurrent batch (default 5 workers) with
  in-run cache; same return shape per URL.
- :func:`reset_cache` — test hook; clears the process-scope memoization.

Cache semantics: results (success AND failure) are cached for the lifetime of
the importing process. A 404'd URL does not get re-fetched within the same
plan-backlinks invocation. Operators must either restart the process or call
:func:`reset_cache` (tests) to invalidate.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import as_completed, ThreadPoolExecutor
from functools import lru_cache
import os
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from backlink_publisher._util.logger import opencli_logger
from backlink_publisher._util.net_safety import (
    _check_url_for_ssrf,
    _make_ssrf_opener,
    _SSRF_OPENER,
)
from backlink_publisher._util.url import normalize_url_for_fetch

from ._disk_cache import disk_cache_clear, disk_cache_get, disk_cache_set
from ._fetch_helpers import _cache_key, _is_transient, _is_valid_http_url
from ._fetch_settings import (
    _body_too_small_bytes,
    _fetch_timeout,
    _head_scan_bytes,
    _max_body_bytes,  # noqa: F401 — re-exported for test imports
    _max_retries,
    BODY_TOO_SMALL_BYTES,  # noqa: F401
    FETCH_TIMEOUT,  # noqa: F401 — re-exported for test imports
    HEAD_SCAN_BYTES,  # noqa: F401
    MAX_BODY_BYTES,  # noqa: F401
    MAX_RETRIES,  # noqa: F401
)
from ._html_utils import extract_title, read_html_head_window
from ._soft404 import is_soft_404_title as _is_soft_404_title

# Stats counters + stateless predicates were extracted to sibling modules for
# monolith-budget headroom (2026-06-01). ``_STATS`` is imported by reference
# and mutated in place here; ``reset_stats`` / ``stats_snapshot`` are
# re-exported so ``content.fetch.<name>`` stays the stable public surface.
from ._stats import _record_reason, _STATS, reset_stats, stats_snapshot  # noqa: F401

#: User-Agent identifies this fetcher distinctly from ``linkcheck``'s probe so
#: target sites can rate-limit / allowlist the two independently.
USER_AGENT: str = "backlink-publisher/0.1 content-fetch"

#: TLS context (environment-gated insecure verification).
from backlink_publisher._util.ssl_ctx import get_ssl_context

_SSL_CTX: ssl.SSLContext = get_ssl_context()


# SSRF defence lives in backlink_publisher._util.net_safety.
# _check_url_for_ssrf and _SSRF_OPENER are imported above.


CheckResult = tuple[bool, str | None, str | None]
#: ``(ok, reason, title)``. ``reason`` is ``None`` on success and one of the
#: stable strings documented in the module docstring otherwise. ``title`` is
#: the extracted text on success (stripped, non-empty) or ``None`` on failure.

#: Cache entry: (result, monotonic timestamp at write). The timestamp lets
#: callers opt into TTL-based expiry without changing the result tuple shape
#: existing callers rely on.
_CacheEntry = tuple[CheckResult, float]
_CACHE: OrderedDict[str, _CacheEntry] = OrderedDict()

#: Canonical "unreachable / unexpected failure" verdict used as a fail-closed
#: fallback in the batch path.
_NETWORK_ERROR: CheckResult = (False, "network_error", None)

#: Thread lock guarding the ``_CACHE`` dict structure and ``_evict_lru``.
#: It protects dict integrity only — the network fetch runs OUTSIDE the lock,
#: so two threads missing the same key may both fetch (last write wins). This
#: is intentional: holding the lock across a blocking GET would serialize all
#: fetches. ``_STATS`` counters are advisory and updated outside the lock.
_CACHE_LOCK = threading.Lock()

#: Maximum cache entries (LRU eviction). Prevents unbounded growth in
#: long-running processes like the WebUI daemon. Set via
#: ``BACKLINK_FETCH_CACHE_MAX_ENTRIES`` (default 256).
_MAX_CACHE_ENTRIES: int = 256


def _touch_cache(key: str) -> None:
    """Move key to end (most-recently-used) for true LRU eviction."""
    _CACHE.move_to_end(key)


def _evict_lru() -> None:
    """Evict least-recently-used cache entries when size limit is exceeded."""
    while len(_CACHE) > _MAX_CACHE_ENTRIES:
        _CACHE.popitem(last=False)


# Initialize max cache entries from environment (allows tuning without code change)
try:
    _MAX_CACHE_ENTRIES = int(os.environ.get("BACKLINK_FETCH_CACHE_MAX_ENTRIES", "256"))
except (ValueError, TypeError):
    pass  # Keep default if env var is malformed

#: Process-wide default TTL for cache entries (seconds). ``None`` means "never
#: expire" (CLI default — process is short-lived). Webui startup sets this to
#: ``BACKLINK_GATE_CACHE_TTL_SECONDS`` (default 900) so a long-running daemon
#: re-fetches stale results.
_DEFAULT_MAX_AGE_S: float | None = None

def reset_cache() -> None:
    """Clear the in-run cache and disk cache. Tests call this between scenarios."""
    _CACHE.clear()
    try:
        disk_cache_clear()
    except Exception:
        pass


def set_default_max_age(seconds: float | None) -> None:
    """Set the process-wide TTL for cache entries.

    Passing ``None`` disables expiry (CLI default). Webui startup wires this
    to ``BACKLINK_GATE_CACHE_TTL_SECONDS`` (default 900s = 15 min) so a daemon
    that has been running for hours doesn't serve stale gate results.
    Idempotent — multiple calls just replace the value.
    """
    global _DEFAULT_MAX_AGE_S
    _DEFAULT_MAX_AGE_S = seconds






@lru_cache(maxsize=128)
def _classify_http_code(code: int) -> str:
    """Map a non-200 HTTP status code to its canonical reason string.

    5xx collapses to the bucket ``http_5xx`` (retry-eligible transient class);
    every other non-200 code (4xx, 1xx/3xx that surfaced as an error, edge
    codes like 418) keeps its exact ``http_<code>`` label. Shared by both the
    ``HTTPError`` path and the non-200 ``getcode()`` path in :func:`_check_once`
    so the two stay in lockstep.
    """
    if 500 <= code < 600:
        return "http_5xx"
    return f"http_{code}"


def _check_once(
    url: str,
    timeout_seconds: float | None = None,
    max_redirects: int | None = None,
) -> CheckResult:
    """Single GET attempt. Returns the canonical CheckResult; never raises.

    ``timeout_seconds`` overrides :data:`FETCH_TIMEOUT` when set; ``None`` =
    default. ``max_redirects`` builds a fresh SSRF opener with a custom
    redirect cap; ``None`` = reuse the shared :data:`_SSRF_OPENER`
    (default 10 redirects).

    SSRF defence lives in ``backlink_publisher._util.net_safety``:

    1. :func:`_check_url_for_ssrf` resolves the URL's host and rejects
       any address in ``_BLOCKED_NETWORKS`` (RFC1918, loopback,
       link-local, cloud-metadata, CGNAT, multicast, IPv6 tunnel).
    2. :data:`_SSRF_OPENER` installs a custom redirect handler that
       re-checks each 30x target and refuses HTTPS→HTTP downgrade.
    """
    blocked = _check_url_for_ssrf(url)
    if blocked is not None:
        # Map the precise reason ladder to a stable taxonomy:
        # - 'invalid_host' / 'invalid_ip' → invalid_url
        # - 'dns_failure' → network_error (operator may be offline; retry)
        # - 'blocked_ip:<net>' → ssrf_blocked (no retry; structural)
        if blocked in {"invalid_host", "invalid_ip"}:
            return False, "invalid_url", None
        if blocked == "dns_failure":
            return False, "network_error", None
        return False, "ssrf_blocked", None

    req = Request(normalize_url_for_fetch(url), method="GET")
    req.add_header("User-Agent", USER_AGENT)
    opener = _make_ssrf_opener(max_redirects) if max_redirects is not None else _SSRF_OPENER
    effective_timeout = timeout_seconds if timeout_seconds is not None else _fetch_timeout()
    try:
        resp = opener.open(req, timeout=effective_timeout)
    except HTTPError as exc:
        return False, _classify_http_code(exc.code), None
    except TimeoutError:
        return False, "timeout", None
    except URLError as exc:
        reason_obj = getattr(exc, "reason", None)
        # Our custom redirect handler raises URLError with reason strings
        # like "ssrf_redirect:blocked_ip:10.0.0.0/8" or
        # "ssrf_https_downgrade". Surface those as their own category so
        # operators don't confuse them with network failures.
        if isinstance(reason_obj, str) and reason_obj.startswith("ssrf_"):
            return False, "ssrf_blocked", None
        if isinstance(reason_obj, socket.timeout):
            return False, "timeout", None
        return False, "network_error", None
    except (OSError, ValueError):
        # Network-level errors (connection refused, DNS failure, etc.)
        return False, "network_error", None
    except Exception as exc:
        opencli_logger.warning(
            f"content_fetch: unexpected error for {url}: {type(exc).__name__} {exc}"
        )
        return False, "network_error", None

    code = resp.getcode()
    if code != 200:
        return False, _classify_http_code(code), None

    try:
        body = read_html_head_window(resp, _head_scan_bytes())
    except Exception:
        return False, "network_error", None
    finally:
        try:
            resp.close()
        except Exception:
            pass

    title = extract_title(body)
    if not title:
        has_head_close = b"</head>" in body.lower()
        if not has_head_close and len(body) < _body_too_small_bytes():
            return False, "body_too_small", None
        return False, "http_200_no_title", None
    if _is_soft_404_title(title):
        # Page returned HTTP 200 but its title advertises a 404 state.
        # Distinct reason so operators can filter soft-404s separately
        # from hard 404s / empty-title pages.
        return False, "soft_404_title", None
    return True, None, title


def verify_url_has_content(
    url: str,
    max_age_seconds: float | None = None,
    timeout_seconds: float | None = None,
    max_redirects: int | None = None,
) -> CheckResult:
    """Verify ``url`` returns HTTP 200 and a parseable non-empty title.

    Cached: subsequent calls with the same URL return the cached result
    (positive or negative) without re-fetching, *subject to TTL*. Use
    :func:`reset_cache` to invalidate during tests.

    ``max_age_seconds`` (call-site override) > :data:`_DEFAULT_MAX_AGE_S`
    (process-wide, set by :func:`set_default_max_age`) > ``None`` (never
    expire). When a cached entry is older than the effective TTL, the entry
    is treated as a miss and re-fetched. ``max_age_seconds=0`` forces a
    fresh fetch every call.

    Stats: every call updates :data:`_STATS` (cache hits / misses /
    fetches / latency / reason_counts). Inspect via :func:`stats_snapshot`.

    Returns
    -------
    (ok, reason, title)
        ``ok`` is ``True`` only when HTTP status is 200, the body parses, and
        either ``<meta property="og:title">`` or ``<title>`` resolves to a
        non-empty stripped string. ``reason`` carries the failure category
        on ``ok=False`` and is ``None`` on success. ``title`` is the
        extracted string on success and ``None`` otherwise.
    """
    # Normalize URL for cache key to collapse equivalent representations.
    canonical_url = _cache_key(url)
    effective_ttl = max_age_seconds if max_age_seconds is not None else _DEFAULT_MAX_AGE_S

    # Fast path: check cache under lock to avoid duplicate fetches.
    with _CACHE_LOCK:
        cached = _CACHE.get(canonical_url)
        if cached is not None:
            result, written_at = cached
            if effective_ttl is None or (time.monotonic() - written_at) < effective_ttl:
                _STATS["cache_hits"] += 1
                _touch_cache(canonical_url)
                return result
            # Expired — fall through to refetch (will overwrite under lock later).

    _STATS["cache_misses"] += 1

    if not _is_valid_http_url(url):
        result = (False, "invalid_url", None)
        with _CACHE_LOCK:
            _CACHE[canonical_url] = (result, time.monotonic())
            _evict_lru()
        _record_reason("invalid_url", ok=False)
        return result

    # L2: disk cache (cross-process persistence, TTL 1h default).
    # Bypassed when explicit TTL is set — in-memory cache is authoritative then.
    if effective_ttl is None:
        _disk_hit = disk_cache_get(url)
        if _disk_hit is not None:
            _STATS["cache_hits"] += 1
            with _CACHE_LOCK:
                _CACHE[canonical_url] = (_disk_hit, time.monotonic())
                _touch_cache(canonical_url)
                _evict_lru()
            return _disk_hit

    started = time.monotonic()
    last_result: CheckResult = (False, "network_error", None)
    for attempt in range(_max_retries() + 1):
        ok, reason, title = _check_once(url, timeout_seconds, max_redirects)
        if ok:
            last_result = (True, None, title)
            break
        last_result = (False, reason, None)
        if reason is None or not _is_transient(reason):
            break
        if attempt < _max_retries():
            opencli_logger.debug(
                f"content_fetch retry {attempt + 1}/{_max_retries()} for {url}: {reason}"
            )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    _STATS["fetches"] += 1
    _STATS["total_latency_ms"] += elapsed_ms
    _record_reason(last_result[1], ok=last_result[0])
    with _CACHE_LOCK:
        _CACHE[canonical_url] = (last_result, time.monotonic())
        _evict_lru()
    # Persist successful fetches to disk for cross-process reuse.
    if last_result[0] and effective_ttl is None:
        disk_cache_set(url, last_result)
    return last_result


def verify_urls_batch(
    urls: list[str], max_workers: int = 5,
) -> dict[str, CheckResult]:
    """Verify a batch of URLs concurrently and return a per-URL result dict.

    Deduplicates the input, consults the cache, submits cache-miss URLs to a
    bounded ``ThreadPoolExecutor``, and merges the results. Each call to
    :func:`verify_url_has_content` inside the workers updates the shared cache,
    so a subsequent batch (or single-URL call) seeing the same URL hits the
    cached result.

    Parameters
    ----------
    urls : list[str]
        Candidate URLs. Order is not preserved in the dict; callers map
        results back to their positions via the URL keys.
    max_workers : int, default 5
        Concurrency cap. The default matches ``linkcheck.check_urls`` and is
        gentle enough that batches of 6–10 URLs overlap without overwhelming
        target sites.

    Returns
    -------
    dict[str, CheckResult]
        One entry per distinct URL. Caller-side duplicates collapse to a
        single entry.
    """
    if not urls:
        return {}

    # Build mapping: canonical URL -> list of original URLs that map to it
    canonical_to_originals: dict[str, list[str]] = {}
    for u in urls:
        c = _cache_key(u)
        canonical_to_originals.setdefault(c, []).append(u)

    distinct_canonical = list(canonical_to_originals.keys())

    # Determine cache misses (respect TTL)
    now = time.monotonic()
    def _fresh(entry: _CacheEntry) -> bool:
        if _DEFAULT_MAX_AGE_S is None:
            return True
        return (now - entry[1]) < _DEFAULT_MAX_AGE_S

    # Snapshot fresh cache hits and collect misses atomically under the lock.
    # We capture the hit *value* now rather than re-reading _CACHE after the
    # fetch phase: a large batch (more distinct URLs than _MAX_CACHE_ENTRIES)
    # would otherwise let _evict_lru drop an early result before we read it,
    # turning a genuine success into a spurious "network_error".
    results_by_canonical: dict[str, CheckResult] = {}
    misses_canonical: list[str] = []
    with _CACHE_LOCK:
        for c in distinct_canonical:
            entry = _CACHE.get(c)
            if entry is not None and _fresh(entry):
                results_by_canonical[c] = entry[0]
            else:
                misses_canonical.append(c)

    if misses_canonical:
        workers = min(max_workers, max(1, len(misses_canonical)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for c in misses_canonical:
                # Pick any original URL that maps to this canonical to preserve logging context
                representative_url = canonical_to_originals[c][0]
                fut = pool.submit(verify_url_has_content, representative_url)
                futures[fut] = c
            for fut in as_completed(futures):
                c = futures[fut]
                try:
                    # verify_url_has_content caches internally; we keep the
                    # returned value too so eviction can't lose it before the
                    # result dict is built.
                    results_by_canonical[c] = fut.result()
                except Exception:
                    results_by_canonical[c] = _NETWORK_ERROR
                    # Cache the failure so a repeat call doesn't re-raise.
                    with _CACHE_LOCK:
                        _CACHE.setdefault(c, (_NETWORK_ERROR, time.monotonic()))

    # Build result dict for every original URL from the captured values.
    result: dict[str, CheckResult] = {}
    for c, originals in canonical_to_originals.items():
        res = results_by_canonical.get(c, _NETWORK_ERROR)
        for orig in originals:
            result[orig] = res
    return result
