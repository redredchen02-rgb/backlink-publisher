from __future__ import annotations

import json
import re
import time
from typing import Any

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.http_client import http_client
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.publishing.content_negotiation import extract_publish_html
from backlink_publisher.publishing.registry import get_platform_throttle_seconds, Publisher

from .base import AdapterResult
from .retry import retry_transient_call, RETRYABLE_HTTP_STATUSES

RENTRY_BASE = "https://rentry.co"
_HTTP_TIMEOUT_S = 30
_DEFAULT_POST_PUBLISH_DELAY_S: int = 10


def _post_publish_delay_s() -> int:
    return get_platform_throttle_seconds(
        platform="rentry",
        env_var="RENTRY_PUBLISH_DELAY_S",
        default=_DEFAULT_POST_PUBLISH_DELAY_S,
    )
    from backlink_publisher.config import load_config
    toml_val = load_config().platform_throttle.get("rentry")
    if toml_val is not None:
        return int(toml_val)
    return _DEFAULT_POST_PUBLISH_DELAY_S


class RentryAPIAdapter(Publisher):
    """Publishes to Rentry.co via anonymous HTTP POST (``/api/new``).

    Rentry is a Markdown pastebin that requires no authentication. A new
    paste is created via ``POST /api/new`` with form-encoded data::

        csrfmiddlewaretoken = <token>
        text = <content>

    The CSRF token is scraped from the homepage first. The paste is
    created as an "edit-by-url" document — anyone with the edit URL can
    modify it. The adapter stores the edit URL for reference but returns
    the public read-only URL as the ``published_url``.

    Rentry does not modify outbound links so registered with
    ``dofollow=True``. Note: Rentry has low DA (~55) and is suitable as
    a quick syndication target, not a primary SEO channel.
    """

    post_publish_delay_seconds: int = _DEFAULT_POST_PUBLISH_DELAY_S

    @classmethod
    def available(cls, config: Config) -> bool:
        return True  # no auth required

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        t0 = time.monotonic()
        article_id = payload.get("id", "")
        log.info(json.dumps(dict(adapter="rentry", phase="start", id=article_id)))

        title = payload.get("title", "Untitled")
        body = payload.get("content_markdown") or extract_publish_html(payload, "rentry") or ""
        content = f"# {title}\n\n{body}"

        # Step 1: fetch the homepage for a CSRF token. This GET is
        # idempotent, so it is safe to retry on transient (429) errors.
        def _fetch_csrf() -> Any:
            home_resp = http_client.get(
                RENTRY_BASE,
                timeout=_HTTP_TIMEOUT_S,
                raise_for_status=False,
            )
            if home_resp.status_code != 200:
                raise ExternalServiceError(
                    f"Rentry homepage returned HTTP {home_resp.status_code}"
                )
            match = re.search(
                r'name="csrfmiddlewaretoken"\s+value="([^"]+)"',
                home_resp.text,
            )
            if not match:
                raise ExternalServiceError(
                    "Could not extract CSRF token from Rentry homepage"
                )
            return match.group(1), home_resp.cookies.get_dict()

        try:
            csrf_token, cookies = retry_transient_call(
                _fetch_csrf,
                is_retryable=lambda exc: (
                    isinstance(exc, ExternalServiceError)
                    and any(
                        f"HTTP {code}" in str(exc)
                        for code in RETRYABLE_HTTP_STATUSES
                    )
                ),
                adapter="rentry",
            )

            # Step 2: create the paste — exactly ONCE. Paste creation has no
            # idempotency key, so retrying it on a transient 429 would create
            # a DUPLICATE paste. The non-idempotent POST is deliberately
            # outside retry_transient_call (P2 fix).
            form_data = {
                "csrfmiddlewaretoken": csrf_token,
                "text": content,
            }
            post_headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": RENTRY_BASE,
            }
            post_resp = http_client.post(
                f"{RENTRY_BASE}/api/new",
                headers=post_headers,
                cookies=cookies,
                data=form_data,
                timeout=_HTTP_TIMEOUT_S,
                raise_for_status=False,
            )
            if post_resp.status_code not in (200, 201):
                raise ExternalServiceError(
                    f"Rentry API returned HTTP {post_resp.status_code}: "
                    f"{post_resp.text[:200]}"
                )
            try:
                result = post_resp.json()
            except ValueError as exc:
                raise ExternalServiceError(
                    f"Rentry returned non-JSON response: {exc}"
                )
            # Rentry's /api/new success status is the HTTP code as a string
            # ("200") in the current API; older responses used "created".
            # Accept both. Errors carry status "error"/"400"/etc.
            status = str(result.get("status", ""))
            if status not in ("created", "200"):
                msg = (
                    result.get("errors")
                    or result.get("message")
                    or result.get("content")
                    or post_resp.text[:200]
                )
                raise ExternalServiceError(f"Rentry API error: {msg}")
            edit_code = result.get("edit_code", "")
            # Current API returns the full public URL directly in ``url``
            # (plus ``url_short``). Legacy responses used ``url_id``/``id``;
            # fall back to those and construct from the base URL.
            published_url = result.get("url")
            if not published_url:
                url_id = (
                    result.get("url_short")
                    or result.get("url_id")
                    or result.get("id")
                    or edit_code
                )
                if not url_id:
                    raise ExternalServiceError("Rentry create returned no ID")
                published_url = f"{RENTRY_BASE}/{url_id}"
        except (ExternalServiceError):
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f"Rentry publish failed ({type(exc).__name__}): {exc}"
            ) from exc

        elapsed = int((time.monotonic() - t0) * 1000)
        log.info(json.dumps(dict(
            adapter="rentry", phase="done", id=article_id, elapsed_ms=elapsed,
        )))
        return AdapterResult(
            status="published",
            adapter="rentry",
            platform="rentry",
            published_url=published_url,
            post_publish_delay_seconds=_post_publish_delay_s(),
            # Rentry returns the edit_code only at creation; it is the sole
            # credential that can later edit/delete the paste, so stash it for
            # canary-seed cleanup. (carry_link_attr_verification ignores it.)
            _provider_meta={"edit_code": edit_code} if edit_code else None,
        )
