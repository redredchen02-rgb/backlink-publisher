"""URL reachability checker with retry logic for the backlink pipeline."""

from __future__ import annotations

import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.request import Request, urlopen

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.logger import opencli_logger
from backlink_publisher._util.net_safety import _check_url_for_ssrf
from backlink_publisher._util.url import (
    canonicalize_url,
    normalize_url_for_fetch,
    safe_urlparse,
)

import os as _os

_DEFAULT_REQUEST_TIMEOUT = 10
_DEFAULT_MAX_CONCURRENT = 10
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_DELAY_BASE_S = 1

ACCEPTABLE_CODES = {200, 301, 302}


def _request_timeout() -> int:
    try:
        return int(_os.environ.get("BACKLINK_LINKCHECK_REQUEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT))
    except (ValueError, TypeError):
        return _DEFAULT_REQUEST_TIMEOUT


def _max_concurrent() -> int:
    try:
        return int(_os.environ.get("BACKLINK_LINKCHECK_MAX_CONCURRENT", _DEFAULT_MAX_CONCURRENT))
    except (ValueError, TypeError):
        return _DEFAULT_MAX_CONCURRENT


def _max_retries() -> int:
    try:
        return int(_os.environ.get("BACKLINK_LINKCHECK_MAX_RETRIES", _DEFAULT_MAX_RETRIES))
    except (ValueError, TypeError):
        return _DEFAULT_MAX_RETRIES


def _retry_delay_base_s() -> int:
    try:
        return int(_os.environ.get("BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S", _DEFAULT_RETRY_DELAY_BASE_S))
    except (ValueError, TypeError):
        return _DEFAULT_RETRY_DELAY_BASE_S


def _ssl_context() -> ssl.SSLContext:
    from backlink_publisher._util.ssl_ctx import get_ssl_context
    return get_ssl_context()


def _check_url_once(url: str) -> tuple[bool, str | None]:
    """Single attempt to check a URL. Returns (reachable, error_message)."""
    parsed = safe_urlparse(url)
    if parsed is None or not parsed.scheme or not parsed.netloc:
        return False, f"invalid URL: {url}"

    ssrf_reason = _check_url_for_ssrf(url)
    if ssrf_reason is not None:
        return False, f"SSRF blocked: {ssrf_reason}"

    # Defend the request-line ASCII encoder against legitimately non-ASCII
    # URLs (Velog Korean @username, CJK url_slug). See Plan 2026-05-21-005.
    fetch_url = normalize_url_for_fetch(url)

    # Try HEAD first
    try:
        req = Request(fetch_url, method="HEAD")
        req.add_header("User-Agent", "backlink-publisher/0.1 linkcheck")
        resp = urlopen(req, timeout=_request_timeout(), context=_ssl_context())
        code = resp.getcode()
        if code in ACCEPTABLE_CODES:
            return True, None
    except Exception:
        pass

    # Fallback to GET
    try:
        req = Request(fetch_url, method="GET")
        req.add_header("User-Agent", "backlink-publisher/0.1 linkcheck")
        resp = urlopen(req, timeout=_request_timeout(), context=_ssl_context())
        code = resp.getcode()
        if code in ACCEPTABLE_CODES:
            return True, None
        return False, f"HTTP {code}"
    except Exception as exc:
        return False, str(exc)


def _check_url_with_retry(url: str) -> tuple[str, bool, str | None]:
    """Check a URL with retry logic. Returns (url, reachable, error_message)."""
    # Indirect lookup via the legacy ``backlink_publisher.linkcheck`` module
    # so ``patch("backlink_publisher.linkcheck._check_url_once", ...)`` in
    # tests intercepts. The Unit 6 split moved ``_check_url_once`` from
    # ``linkcheck.py`` (where the patch worked module-internally) into
    # ``linkcheck/http.py`` (where a captured reference in
    # ``linkcheck/__init__.py`` no longer routes through the patched
    # attribute). Same shim pattern as Unit 5 ``config/writer.py``.
    from backlink_publisher import linkcheck as _legacy
    last_error = "unknown error"
    for attempt in range(_max_retries() + 1):
        reachable, error = _legacy._check_url_once(url)
        if reachable:
            return url, True, None
        last_error = error or "unknown error"
        if attempt < _max_retries():
            opencli_logger.debug(
                f"Retry {attempt + 1}/{_max_retries()} for {url}: {last_error}"
            )
            time.sleep(_retry_delay_base_s() * (attempt + 1))

    return url, False, last_error


def check_url(url: str) -> tuple[bool, str | None]:
    """Check a single URL with retry; return ``(reachable, error_message)``.

    Additive public wrapper around :func:`_check_url_with_retry`. Unlike
    :func:`check_urls_strict`, this never raises — callers (e.g. the publish-
    time per-row reachability gate in plan 2026-05-14-001 Unit 5) get a
    tuple and decide their own continue/abort policy.
    """
    _, reachable, error = _check_url_with_retry(url)
    return reachable, error


def _dedup_key(url: object) -> str:
    """Canonical dedup key for ``url`` (utm params, default ports, trailing
    slash, fragment collapsed — see :func:`canonicalize_url`).

    Declared ``-> str`` for the happy path but defensively accepts ``object``
    and passes non-canonicalizable input through unchanged, so a malformed
    string (``http://[invalid`` — ``urlsplit`` raises ``ValueError``) or a
    non-str *scalar* (``int``/``bool`` — caller contract violation) gets its
    own key and flows through ``_check_url_with_retry`` rather than crashing
    the whole batch. Unhashable inputs (``list``/``dict``) remain out of
    contract (``urls: list[str]``) and would raise at the dict-key step, same
    as the prior ``dict.fromkeys`` dedup — they are not supported here.
    """
    if not isinstance(url, str):
        return url  # type: ignore[return-value]  # fail-soft passthrough
    try:
        return canonicalize_url(url)
    except ValueError:
        return url


def check_urls(urls: list[str]) -> dict[str, tuple[bool, str | None]]:
    """Check reachability of multiple URLs concurrently with retries.

    Returns a dict mapping URL -> (reachable, error_message).
    """
    results: dict[str, tuple[bool, str | None]] = {}
    if not urls:
        return results

    # Build mapping: canonical URL -> list of original URLs that map to it
    canonical_to_originals: dict[str, list[str]] = {}
    for u in urls:
        c = _dedup_key(u)
        canonical_to_originals.setdefault(c, []).append(u)

    distinct_canonical = list(canonical_to_originals.keys())

    if not distinct_canonical:
        return results

    if len(distinct_canonical) == 1:
        c = distinct_canonical[0]
        rep = canonical_to_originals[c][0]
        _, reachable, error = _check_url_with_retry(rep)
        for orig in canonical_to_originals[c]:
            results[orig] = (reachable, error)
        return results

    with ThreadPoolExecutor(max_workers=min(_max_concurrent(), len(distinct_canonical))) as pool:
        futures: dict[Any, str] = {}  # future -> canonical
        for c in distinct_canonical:
            rep = canonical_to_originals[c][0]
            fut = pool.submit(_check_url_with_retry, rep)
            futures[fut] = c
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                _, reachable, error = fut.result()
            except Exception as e:  # noqa: BLE001
                # _check_url_with_retry shouldn't raise, but treat any escape
                # as unreachable for this canonical rather than dropping it.
                reachable, error = False, str(e)
            # Populate results for all originals mapping to this canonical
            for orig in canonical_to_originals[c]:
                results[orig] = (reachable, error)
    return results


def check_urls_strict(urls: list[str]) -> None:
    """Check reachability and raise on any unreachable URL.

    Skips obviously invalid URLs (non-HTTP) without failing.
    """
    if not urls:
        return
    # Filter out non-http URLs for checking
    http_urls = [u for u in urls if u.startswith("http://") or u.startswith("https://")]
    if not http_urls:
        return

    results = check_urls(http_urls)
    failures = [(url, err) for url, (ok, err) in results.items() if not ok]
    if failures:
        url, err = failures[0]
        raise ExternalServiceError(f"unreachable URL: {url}" + (f" ({err})" if err else ""))
