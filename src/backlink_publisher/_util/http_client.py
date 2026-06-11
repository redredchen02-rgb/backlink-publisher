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
import time
from typing import Any

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
        self._max_retries = max_retries
        self._retry_delay = retry_delay

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

    def _check_ssrf(self, url: str) -> None:
        """Raise ``ExternalServiceError`` if the URL is blocked by SSRF rules."""
        blocked = _check_url_for_ssrf(url)
        if blocked:
            raise ExternalServiceError(
                f"SSRF check blocked request to {url!r} (block_reason={blocked})"
            )

    def _do_request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        self._check_ssrf(url)
        kwargs.setdefault("timeout", self._timeout)

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    wait = self._retry_delay * (attempt + 1)
                    time.sleep(wait)
        raise ExternalServiceError(
            f"HTTP {method.upper()} {url!r} failed after "
            f"{self._max_retries + 1} attempt(s): {last_exc}"
        ) from last_exc

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Perform a GET request with SSRF and retry protection."""
        return self._do_request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        """Perform a POST request with SSRF and retry protection."""
        return self._do_request("POST", url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        """Perform a HEAD request with SSRF and retry protection."""
        return self._do_request("HEAD", url, **kwargs)

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
    return _local.client


# Module-level default instance for convenience imports
# Note: This is NOT thread-safe. Use get_thread_local_client() for thread safety.
http_client = HttpClient()
