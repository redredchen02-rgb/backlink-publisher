"""Shared types and base functionality for publisher adapters.

Error hierarchy (Plan 2026-05-28-001):
- TransientError: temporary errors (network timeout, 429, 5xx) - safe to retry
- PermanentError: permanent errors (401, 403, 404) - no retry
- DependencyError: missing credentials/prerequisites - triggers fall-through or auth-flip
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TransientError(Exception):
    """Temporary error that can be safely retried (network timeout, 429, 5xx).

    Consolidates four previously module-private, per-adapter transient-HTTP
    sentinel exception classes duplicated across ``blogger_api.py``,
    ``medium_api.py``, ``velog_graphql.py``, and ``llm_anchor_provider.py``
    (Plan 2026-07-06-002 Unit D1). Those four call sites raised with either a
    bare HTTP status code (e.g. ``TransientError(429)``) or a status code
    plus a response-body detail string (e.g. ``TransientError(503,
    resp.text)``). This constructor accepts both shapes — exposing the
    status via ``.status_code`` for callers that build their own message at
    the catch site — while remaining a drop-in replacement for the original
    plain-message usage (``TransientError("some message")``) relied on
    elsewhere.
    """

    def __init__(self, *args: Any) -> None:
        self.status_code: int | None = None
        if args and isinstance(args[0], int) and not isinstance(args[0], bool):
            self.status_code = args[0]
            detail = args[1] if len(args) > 1 else None
            message = (
                f"HTTP {args[0]}" if detail is None else f"HTTP {args[0]}: {detail}"
            )
            super().__init__(message)
        else:
            super().__init__(*args)


class PermanentError(Exception):
    """Permanent error that should not be retried (401, 403, 404)."""

    pass


def classify_http_status(
    status_code: int,
) -> type[TransientError] | type[PermanentError] | None:
    """Classify an HTTP status code to its error type.

    Returns the appropriate exception class or None if not retryable.
    """
    if status_code == 429:
        return TransientError
    if status_code in (502, 503, 504):
        return TransientError
    if status_code in (401, 403, 404):
        return PermanentError
    if 500 <= status_code < 600:
        return TransientError
    return None


_LINK_ATTR_VERIFICATION_KEY = "link_attr_verification"


def carry_link_attr_verification(
    out: dict[str, Any], source: dict[str, Any] | None
) -> dict[str, Any]:
    """Copy the post-publish link-attribute verdict into ``out`` when present.

    ``source`` is the metadata holder — ``AdapterResult._provider_meta`` on the
    fresh path or a checkpoint item on the resume path. The verdict (R4 canary
    loop) is emitted only when ``source`` carries a non-None value, so draft mode
    and adapters that do not verify keep an unchanged output shape. Shared by both
    publish-output emitters so the two paths stay byte-identical.
    """
    if source:
        verdict = source.get(_LINK_ATTR_VERIFICATION_KEY)
        if verdict is not None:
            out[_LINK_ATTR_VERIFICATION_KEY] = verdict
    return out


def _resolve_article_urls(
    row: dict[str, Any], draft_url: str, published_url: str
) -> list[str]:
    """Return the canonical article URL list for publish outputs."""
    urls = row.get("article_urls")
    if isinstance(urls, list):
        resolved = [str(url).strip() for url in urls if str(url).strip()]
        if resolved:
            return resolved
    return [u for u in (published_url.strip(), draft_url.strip()) if u]


@dataclass
class AdapterResult:
    """Normalised result returned by every adapter."""

    status: str  # "drafted" | "published" | "failed"
    adapter: str  # e.g. "blogger-api", "medium-api", "medium-browser"
    platform: str  # "blogger" | "medium"
    draft_url: str = ""
    published_url: str = ""
    error: str | None = None
    post_publish_delay_seconds: int = (
        0  # adapter-declared throttle (plan 2026-05-18-009 R9c)
    )
    _dry_run: bool = False
    _command: str = ""
    _provider_meta: dict[str, Any] | None = None  # optional platform-specific metadata

    def to_publish_output(self, row: dict[str, Any], created_at: str) -> dict[str, Any]:
        """Convert to the JSONL output shape expected by publish_backlinks."""
        article_urls = _resolve_article_urls(row, self.draft_url, self.published_url)
        out = {
            "id": row.get("id", ""),
            "platform": self.platform,
            "status": self.status,
            "title": row.get("title", ""),
            "target_url": row.get("target_url", ""),
            "article_urls": article_urls,
            "draft_url": self.draft_url,
            "published_url": self.published_url,
            "created_at": created_at,
            "adapter": self.adapter,
            "error": self.error,
        }
        # Surface the post-publish link-attribute verdict (R4 canary loop) when an
        # adapter attached it (no-op for draft / non-verifying adapters).
        return carry_link_attr_verification(out, self._provider_meta)


class BaseAdapter:
    """Base adapter class with common HTTP handling and error patterns."""

    def _json_log(self, **kwargs: Any) -> str:
        """Create a JSON log line."""
        import json

        return json.dumps(kwargs)


# Backward compatibility - expose the classes that were previously here
__all__ = [
    "AdapterResult",
    "BaseAdapter",
    "TransientError",
    "PermanentError",
    "classify_http_status",
    "carry_link_attr_verification",
    "_resolve_article_urls",
]
