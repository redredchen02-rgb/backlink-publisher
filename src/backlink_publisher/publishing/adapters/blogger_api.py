"""Blogger API v3 adapter — primary publishing path for Blogger platform."""

from __future__ import annotations

import base64
import html as _html
import mimetypes
import time
from pathlib import Path
from typing import Any

from backlink_publisher.config import Config, resolve_blog_id
from backlink_publisher._util.errors import (
    AuthExpiredError,
    BannerUploadError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.publishing.content_negotiation import extract_publish_html
from backlink_publisher.publishing.registry import Publisher
from backlink_publisher.publishing.session import DefaultCredentialProvider, SessionManager
from .base import AdapterResult, BaseAdapter
from .retry import RETRYABLE_HTTP_STATUSES, retry_transient_call


_BLOGGER_API = "https://www.googleapis.com/blogger/v3"


class _TransientHTTPError(Exception):
    """Sentinel raised when an HTTP response status warrants a retry.

    Module-private — not exported. Does not extend ExternalServiceError so it
    is not caught by the retry guard in retry_transient_call.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class BloggerAPIAdapter(BaseAdapter, Publisher):
    """Publishes to Blogger via the official API v3."""

    def embed_banner(self, artifact_path: Path, alt: str) -> str | None:
        """Inline the banner as a base64 ``data:`` URI.

        Plan 2026-05-20-004 Unit 3.  Blogger has no usable public
        media-upload endpoint in 2026 — the Picasa Web Albums backdoor
        used historically is fully retired, and the Google Photos
        OAuth path requires a separate scope dance that's out of
        scope for v1.0.  The remaining universal option is the
        ``data:<mime>;base64,<...>`` URI inlined directly in the
        post HTML.  Blogger renders these in published posts (verified
        via operator smoke; behavior consistent with how Blogger has
        treated inline data URIs for over a decade).

        Tradeoff: ~33% size overhead from base64 encoding.  Acceptable
        for the banner image regime (typical ~150-300 KB encoded → 200-
        400 KB inlined).  No HTTP call, no auth, no retry surface —
        pure local computation.

        ``render_to_html`` (markdown-it-py via the dispatcher's
        ``![alt](url)`` prepend → Blogger's ``content_html`` field)
        preserves ``data:`` URIs verbatim without escape — verified by
        ``test_blogger_banner.py::TestRoundtripDataUriThroughMarkdown``.

        Raises ``BannerUploadError`` on local file-read failure; this
        is the dispatcher's strict-gate contract.  No remote failure
        modes exist on this path.
        """
        del alt  # signal to readers that alt is consumed by the dispatcher prepend

        try:
            data = artifact_path.read_bytes()
        except OSError as exc:
            raise BannerUploadError(
                f"blogger banner read failed: {artifact_path}: {exc}"
            ) from exc

        filename = artifact_path.name or "banner.png"
        guessed_mime, _ = mimetypes.guess_type(filename)
        # Default to image/png for sha-only filenames; Blogger renders
        # the data URI based on the declared mime, not content sniffing.
        mime = guessed_mime or "image/png"

        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        t0 = time.monotonic()
        platform = "blogger"
        article_id = payload.get("id", "")
        log.info(self._json_log(adapter="blogger-api", phase="start", id=article_id))

        blog_id = resolve_blog_id(config, payload.get("main_domain", ""))

        try:
            session = SessionManager(DefaultCredentialProvider()).get_session(
                "blogger", config
            )
        except (DependencyError, AuthExpiredError):
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f"Blogger authentication failed: {exc}"
            ) from exc

        log.info(self._json_log(adapter="blogger-api", phase="auth", id=article_id))

        # Plan 2026-05-18-006 Unit 5 R9: extract_publish_html selects the
        # source format per platform tier. blogger is tier (a) — accepts
        # operator-supplied content_html directly. Sanitize is delegated
        # to Google Blogger's server-side filter (locked by
        # tests/test_adapter_blogger_api_xss_contract.py). If
        # content_html is absent, falls back to rendering content_markdown.
        content_html = extract_publish_html(payload, "blogger")
        # Mixed canonical (Plan 003 R2): prepend ``<link rel=canonical>``
        # to the post body when payload carries a non-empty schema-
        # validated URL. NOTE: Blogger Posts v3 API has no post-level
        # head-meta field; body-level canonical is a cosmetic marker
        # — Google's canonical resolver requires the tag in <head>, so
        # the SEO impact here is intentional best-effort, not guaranteed.
        # Forwarder contract preserved: escape canonical URL to prevent
        # HTML attribute breakout (defense-in-depth; schema gate already
        # rejected control chars but a well-formed URL containing '"'
        # would break out of the attribute).
        canonical = payload.get("seo", {}).get("canonical_url") or None
        if canonical:
            safe_canonical = _html.escape(canonical, quote=True)
            content_html = (
                f'<link rel="canonical" href="{safe_canonical}">\n{content_html}'
            )
        body = {
            "title": payload.get("title", ""),
            "content": content_html,
            "labels": payload.get("tags", [])[:20],
        }
        is_draft = mode == "draft"
        url_api = f"{_BLOGGER_API}/blogs/{blog_id}/posts/"
        params = {"isDraft": "true"} if is_draft else {}

        def _do_post():
            resp = session.post(url_api, params=params, json=body, timeout=30)
            if resp.status_code in (401, 403):
                raise AuthExpiredError(
                    channel="blogger",
                    reason=f"Blogger HTTP {resp.status_code}",
                )
            if resp.status_code in RETRYABLE_HTTP_STATUSES:
                raise _TransientHTTPError(resp.status_code)
            if not resp.ok:
                raise ExternalServiceError(
                    f"Blogger API error HTTP {resp.status_code}: {resp.text[:200]}"
                )
            return resp.json()

        try:
            result = retry_transient_call(
                _do_post,
                is_retryable=lambda exc: isinstance(exc, _TransientHTTPError),
                adapter="blogger-api",
            )
        except _TransientHTTPError as exc:
            raise ExternalServiceError(
                f"Blogger API rate-limited (HTTP {exc.status_code})"
            ) from exc
        except (AuthExpiredError, ExternalServiceError):
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f"Blogger publish failed ({type(exc).__name__}): {exc}"
            ) from exc

        url = result.get("url", "")
        elapsed = int((time.monotonic() - t0) * 1000)
        log.info(
            self._json_log(adapter="blogger-api", phase="done", id=article_id, elapsed_ms=elapsed)
        )

        if mode == "draft":
            return AdapterResult(
                status="drafted",
                adapter="blogger-api",
                platform=platform,
                draft_url=url,
            )
        return AdapterResult(
            status="published",
            adapter="blogger-api",
            platform=platform,
            published_url=url,
        )
