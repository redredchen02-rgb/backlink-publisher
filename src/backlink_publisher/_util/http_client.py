"""Unified HTTP client with SSRF protection, retry, and timeout.

Usage::

    from backlink_publisher._util.http_client import http_client

    resp = http_client.get("https://api.example.com/data")
    resp = http_client.post("https://api.example.com/submit", json={"key": "val"})
    resp = http_client.head("https://example.com")
"""

from __future__ import annotations

import os
import threading
from typing import Any, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.net_safety import _check_url_for_ssrf

_DEFAULT_TIMEOUT = int(os.environ.get("BACKLINK_LINKCHECK_REQUEST_TIMEOUT", "10"))
_DEFAULT_MAX_RETRIES = int(os.environ.get("BACKLINK_LINKCHECK_MAX_RETRIES", "2"))
_DEFAULT_RETRY_DELAY = 1.0
_USER_AGENT = "backlink-publisher/0.3 (+https://github.com/dexvn/backlink-publisher)"

# Thread-local storage for HttpClient instances
_local = threading.local()
_lock = threading.Lock()


class HttpClient:
    """SSRF-safe, retry-capable HTTP client wrapping ``requests.Session``."""

    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_RETRY_DELAY,
        pool_connections: int = 10,
        pool_maxsize: int = 10,
    ) -> None:
        self._timeout = timeout

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset({"GET", "POST", "HEAD"}),
        )
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy,
        )

        self._session = requests.Session()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.headers.update({"User-Agent": _USER_AGENT})

    def _check_ssrf(self, url: str, allow_private: bool = False) -> None:
        """Raise ``ExternalServiceError`` if the URL is blocked by SSRF rules.

        ``allow_private=True`` permits RFC1918/loopback targets (operator
        self-hosted endpoints, local gateways) while STILL blocking
        cloud-metadata and other dangerous ranges.
        """
        blocked = _check_url_for_ssrf(url, allow_private=allow_private)
        if blocked:
            raise ExternalServiceError(
                f"SSRF check blocked request to {url!r} (block_reason={blocked})"
            )

    def _do_request(
        self,
        method: str,
        url: str,
        raise_for_status: bool = True,
        allow_private: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        self._check_ssrf(url, allow_private=allow_private)
        kwargs.setdefault("timeout", self._timeout)

        # Retry is handled by urllib3.Retry configured on the adapter — no
        # manual loop needed (previously caused up to 9x redundant requests).
        try:
            resp = self._session.request(method, url, **kwargs)
            if raise_for_status:
                resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise ExternalServiceError(
                f"HTTP {method.upper()} {url!r} failed: {exc}"
            ) from exc

    def get(
        self,
        url: str,
        raise_for_status: bool = True,
        allow_private: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        """Perform a GET request with SSRF and retry protection.

        Pass ``raise_for_status=False`` to receive the response without raising
        on non-2xx status — for callers that map status codes to their own
        domain errors (e.g. an adapter translating 401 to a re-auth message).
        Pass ``allow_private=True`` to permit RFC1918/loopback targets (operator
        self-hosted endpoints, local gateways) while still blocking
        cloud-metadata ranges. SSRF check, timeout, retry, and connection-error
        wrapping still apply.
        """
        return self._do_request(
            "GET", url, raise_for_status=raise_for_status, allow_private=allow_private, **kwargs
        )

    def post(
        self,
        url: str,
        raise_for_status: bool = True,
        allow_private: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        """Perform a POST request with SSRF and retry protection.

        See :meth:`get` for the ``raise_for_status`` and ``allow_private`` opt-outs.
        """
        return self._do_request(
            "POST", url, raise_for_status=raise_for_status, allow_private=allow_private, **kwargs
        )

    def head(
        self,
        url: str,
        raise_for_status: bool = True,
        allow_private: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        """Perform a HEAD request with SSRF and retry protection."""
        return self._do_request(
            "HEAD", url, raise_for_status=raise_for_status, allow_private=allow_private, **kwargs
        )

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self._session.close()


def get_thread_local_client() -> HttpClient:
    """Get or create a thread-local HttpClient instance."""
    if not hasattr(_local, "client"):
        with _lock:
            if not hasattr(_local, "client"):
                _local.client = HttpClient()
    return cast("HttpClient", _local.client)


# Module-level default instance for convenience imports
# Note: This is NOT thread-safe. Use get_thread_local_client() for thread safety.
http_client = HttpClient()
