"""Shared exponential-backoff retry helper for adapter publish calls.

Enhanced for Stage 1 optimization (Plan 2026-05-28-001):
- Unified TransientError/PermanentError classification
- Configurable retry strategies per error type
- Enhanced backoff with jitter
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from enum import Enum
from typing import Any, Callable, TypeVar

from backlink_publisher._util.errors import (
    DependencyError,
    ExternalServiceError,
    AuthExpiredError,
)
from backlink_publisher._util.logger import opencli_logger as log
from .base import TransientError, PermanentError, classify_http_status

T = TypeVar("T")

MAX_ATTEMPTS: int = 3
BACKOFF_BASE: int = 2
JITTER_FACTOR: float = 0.15

_MAX_ATTEMPTS_CEILING = 10
_BACKOFF_BASE_CEILING = 30.0
_JITTER_CEILING = 5.0


def _get_env_backoff(key: str, default: float) -> float:
    """Read a backoff tuning parameter from the environment, falling back to ``default``."""
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return float(default)


_DEFAULT_MAX_ATTEMPTS: int = min(max(int(_get_env_backoff("BACKLINK_RETRY_MAX_ATTEMPTS", 3)), 1), _MAX_ATTEMPTS_CEILING)
_DEFAULT_BACKOFF_BASE: int = min(max(int(_get_env_backoff("BACKLINK_RETRY_BACKOFF_BASE", 2)), 1), _BACKOFF_BASE_CEILING)
_DEFAULT_JITTER: float = min(max(_get_env_backoff("BACKLINK_RETRY_JITTER", 0.15), 0.0), _JITTER_CEILING)

DEFAULT_MAX_ATTEMPTS: int = _DEFAULT_MAX_ATTEMPTS
DEFAULT_BACKOFF_BASE: int = _DEFAULT_BACKOFF_BASE
DEFAULT_JITTER: float = _DEFAULT_JITTER

# HTTP status codes that indicate a transient server-side failure worth retrying.
# Only used by call-site is_retryable predicates — not enforced here.
# NOTE: 5xx errors are NOT retried because neither Blogger API v3 nor Medium API
# document idempotency guarantees. A 5xx response could mean the resource was
# already created server-side (e.g., server timeout after POST succeeded but before
# sending response). Retrying without deduplication risks duplicate posts.
# See: https://sophiabits.com/blog/you-cant-always-retry-a-5xx
#
# INVARIANT — do NOT add 5xx (or any post-create-ambiguous status) to this set.
# Non-idempotent create POSTs (medium_api, velog_graphql, http_form_post) gate
# their retry on `_TransientHTTPError`, which is raised ONLY for statuses in this
# set. They rely on every member being a PRE-create rejection (like 429) that the
# server returns before creating anything. Adding 5xx here would silently make
# those creates retry an ambiguous failure → duplicate published posts.
RETRYABLE_HTTP_STATUSES: frozenset[int] = frozenset({429})


class ErrorClass(str, Enum):
    TRANSIENT = "transient"
    AUTH_EXPIRED = "auth_expired"
    HTTP_5XX = "http_5xx"
    SSRF_BLOCKED = "ssrf_blocked"
    # Permanent platform content rejection (spam/policy block). Value matches the
    # "content_rejected" string already emitted by the publish engine for
    # ContentRejectedError, so downstream consumers need no new vocabulary.
    CONTENT_REJECTED = "content_rejected"
    UNEXPECTED = "unexpected"


_HTTP_5XX_RE = re.compile(r"\b5[0-9]{2}\b")


def classify_exception(exc: Exception) -> ErrorClass:
    """Classify an exception to the ErrorClass taxonomy.

    Used by the publisher and event projectors to route and store failure reasons.
    """
    from backlink_publisher._util.errors import (
        AuthExpiredError,
        ContentRejectedError,
        ExternalServiceError,
    )

    if isinstance(exc, AuthExpiredError):
        return ErrorClass.AUTH_EXPIRED

    # Permanent content rejection must never collapse to TRANSIENT (retrying never
    # helps). velog raises ContentRejectedError directly; browser/CDP adapters such
    # as Write.as surface a generic ExternalServiceError whose message carries the
    # platform's block code (e.g. Write.as HTTP 201 with id="contentisblocked").
    if isinstance(exc, ContentRejectedError):
        return ErrorClass.CONTENT_REJECTED

    msg = str(exc)
    msg_low = msg.lower()
    if "ssrf_blocked" in msg or "ssrf_redirect" in msg or "ssrf_https_downgrade" in msg:
        return ErrorClass.SSRF_BLOCKED

    if (
        "contentisblocked" in msg_low
        or "content is blocked" in msg_low
        or "content blocked" in msg_low
    ):
        return ErrorClass.CONTENT_REJECTED

    if _HTTP_5XX_RE.search(msg):
        return ErrorClass.HTTP_5XX

    if isinstance(exc, ExternalServiceError):
        return ErrorClass.TRANSIENT

    return ErrorClass.UNEXPECTED


def is_transient_reason(reason: str) -> bool:
    """Return True if the content_fetch failure reason is transient and safe to retry.

    Used by content_fetch to decide whether to retry a GET request.
    """
    return reason in {"timeout", "network_error", "http_5xx"}


def _is_retryable_error(exc: Exception, consider_429_as_transient: bool = True) -> bool:
    """Default retryable predicate using the unified error hierarchy.

    - TransientError and timeout/429/5xx patterns → retry
    - PermanentError → no retry
    - Other errors → defer to caller's predicate or no retry
    """
    if isinstance(exc, TransientError):
        return True
    if isinstance(exc, PermanentError):
        return False
    msg = str(exc).lower()
    if "timeout" in msg or "connection" in msg:
        return True
    # HTTP status codes in message
    import re as _re

    status_match = _re.search(r"\b(\d{3})\b", msg)
    if status_match:
        status = int(status_match.group(1))
        if status == 429 and consider_429_as_transient:
            return True
        if status in (502, 503, 504):
            return True
    return False


def retry_transient_call(
    fn: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], bool] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_base: int = DEFAULT_BACKOFF_BASE,
    jitter: float = DEFAULT_JITTER,
    adapter: str = "",
    status_code: int | None = None,
) -> T:
    """Call fn() with exponential-backoff retry on transient failures.

    Enhanced for Stage 1 (Plan 2026-05-28-001):
    - Uses unified TransientError/PermanentError classification
    - Applies longer backoff for rate-limited errors (429)
    - Configurable via BACKLINK_RETRY_MAX_ATTEMPTS, BACKLINK_RETRY_BACKOFF_BASE,
      BACKLINK_RETRY_JITTER env vars

    fn() should be a raw API call that has NOT yet converted exceptions to
    ExternalServiceError.  ExternalServiceError and DependencyError will never
    be raised from a well-behaved fn(), but is_retryable must return False for
    them as a belt-and-suspenders guard.

    On a non-retryable exception OR after exhausting max_attempts, the last
    caught exception is re-raised with bare ``raise`` to preserve its type,
    message, and traceback exactly — required so publish_backlinks.py can route
    DependencyError (exit 3) vs ExternalServiceError (exit 4) correctly.

    Stderr format (R3a): {"level":"WARN","msg":"retrying (attempt N/M): …
    — waiting Xs","adapter":"…","status_code":N}
    No response bodies, headers, or credentials are emitted.
    """
    # Use default predicate if none provided
    if is_retryable is None:
        is_retryable = _is_retryable_error

    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (ExternalServiceError, DependencyError):
            # These must never be retried — re-raise immediately via bare raise
            # so the caller's except block sees the original type.
            raise
        except Exception as exc:
            last_exc = exc
            if not is_retryable(exc):
                raise
            if attempt == max_attempts:
                raise

            # Calculate wait time with status-specific multiplier
            base_wait = float(backoff_base**attempt)
            multiplier = STATUS_BACKOFF_MULTIPLIER.get(status_code or 0, 1.0)
            wait = base_wait * multiplier * random.uniform(1.0 - jitter, 1.0 + jitter)

            # If no explicit status_code, try to extract from exception message
            if status_code is None and last_exc:
                import re as _re

                match = _re.search(r"\b(\d{3})\b", str(last_exc))
                if match:
                    status_code = int(match.group(1))
                    multiplier = STATUS_BACKOFF_MULTIPLIER.get(status_code, 1.0)
                    wait = (
                        base_wait
                        * multiplier
                        * random.uniform(1.0 - jitter, 1.0 + jitter)
                    )

            exc_name = type(exc).__name__
            _emit_retry(attempt, max_attempts, exc_name, wait, adapter, status_code)
            time.sleep(wait)

    # Unreachable, but satisfies the type checker.
    assert last_exc is not None
    raise last_exc  # pragma: no cover


def _emit_retry(
    attempt: int,
    max_attempts: int,
    exc_name: str,
    wait: float,
    adapter: str,
    status_code: int | None = None,
) -> None:
    """Write a structured retry warning to stderr (R3a — no credentials/bodies)."""
    msg: dict[str, Any] = {
        "level": "WARN",
        "msg": f"retrying (attempt {attempt}/{max_attempts}): {exc_name} — waiting {wait:.1f}s",
        "adapter": adapter,
    }
    if status_code is not None:
        msg["status_code"] = status_code
    log.warn(**msg)
