"""Medium API v1 adapter — primary publishing path for Medium platform."""

from __future__ import annotations

import time
from typing import Any, cast

import requests

from backlink_publisher._util.errors import (
    AuthExpiredError,
    ExternalServiceError,
)
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.config.types import MEDIUM_API_BASE, MEDIUM_API_TIMEOUT
from backlink_publisher.publishing.content_negotiation import extract_publish_html
from backlink_publisher.publishing.registry import get_platform_throttle_seconds, Publisher
from backlink_publisher.publishing.session import DefaultCredentialProvider, SessionManager

from .base import AdapterResult
from .link_attr_verifier import required_link_urls, verify_link_attributes
from .retry import retry_transient_call, RETRYABLE_HTTP_STATUSES

_API_BASE = MEDIUM_API_BASE
_TIMEOUT = MEDIUM_API_TIMEOUT
_DEFAULT_MEDIUM_PUBLISH_DELAY_S: int = 30  # 30 s: shared with MEDIUM_THROTTLE_MIN/MAX timing


def _post_publish_delay_s() -> int:
    return get_platform_throttle_seconds(
        platform="medium",
        env_var="MEDIUM_PUBLISH_DELAY_S",
        default=_DEFAULT_MEDIUM_PUBLISH_DELAY_S,
    )


class _TransientHTTPError(Exception):
    """Sentinel raised when an HTTP response status warrants a retry.

    Module-private — not exported. Does not extend ExternalServiceError so it
    is not caught by the retry guard in retry_transient_call.
    """
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def _json_log(**kwargs: Any) -> str:
    import json
    return json.dumps(kwargs)


def _fetch_medium_user_id(session: requests.Session) -> str:
    """Call ``GET /me``, retrying transient errors; return ``user_id`` or raise."""
    def _do_me() -> requests.Response:
        resp = session.get(f"{_API_BASE}/me", timeout=_TIMEOUT)
        if resp.status_code in RETRYABLE_HTTP_STATUSES:
            raise _TransientHTTPError(resp.status_code)
        return resp

    try:
        me_resp = retry_transient_call(
            _do_me,
            is_retryable=lambda exc: isinstance(
                exc, (requests.Timeout, requests.ConnectionError, _TransientHTTPError)
            ),
            adapter="medium-api",
        )
    except requests.RequestException as exc:
        raise ExternalServiceError(
            f"Medium API unreachable (/me): {exc}"
        ) from None
    except _TransientHTTPError as exc:
        raise ExternalServiceError(
            f"Medium /me returned HTTP {exc.status_code} after retries"
        ) from None

    if me_resp.status_code == 401:
        raise AuthExpiredError(channel="medium", reason="Medium /me HTTP 401")
    if not me_resp.ok:
        raise ExternalServiceError(f"Medium /me returned HTTP {me_resp.status_code}")
    return str(cast("dict[str, Any]", me_resp.json())["data"]["id"])


def _create_medium_post(
    user_id: str,
    session: requests.Session,
    body: dict,
) -> requests.Response:
    """POST to ``/users/{user_id}/posts``; retry only on 429; raise on errors.

    Non-idempotent: network errors (Timeout/ConnectionError) after the request
    leaves the client are *not* retried — a silent duplicate would result.
    Only a 429 rate-limit rejection (pre-create refusal) is safe to retry.
    """
    def _do_post() -> requests.Response:
        resp = session.post(
            f"{_API_BASE}/users/{user_id}/posts",
            json=body,
            timeout=_TIMEOUT,
        )
        if resp.status_code in RETRYABLE_HTTP_STATUSES:
            raise _TransientHTTPError(resp.status_code)
        return resp

    # Local import avoids an import cycle: reliability/__init__ imports policy,
    # which imports adapters.publish — still mid-init at adapters package import.
    from ..reliability.transient_policy import mark_pre_create_429

    try:
        post_resp = retry_transient_call(
            _do_post,
            is_retryable=lambda exc: isinstance(exc, _TransientHTTPError),
            adapter="medium-api",
        )
    except requests.RequestException as exc:
        raise ExternalServiceError(
            f"Medium API unreachable (create post): {exc}"
        ) from None
    except _TransientHTTPError as exc:
        err = ExternalServiceError(
            f"Medium /posts returned HTTP {exc.status_code} after retries"
        )
        # Pre-create provenance: a 429 is returned before the post is created, so
        # a same-account fallback cannot duplicate (Plan 2026-06-15-001, Unit A2).
        mark_pre_create_429(err)
        raise err from None

    if post_resp.status_code == 401:
        raise AuthExpiredError(channel="medium", reason="Medium /posts HTTP 401")
    if post_resp.status_code == 429:
        err = ExternalServiceError("Medium API rate-limited (429)")
        mark_pre_create_429(err)
        raise err
    if not post_resp.ok:
        raise ExternalServiceError(
            f"Medium /posts returned HTTP {post_resp.status_code}: "
            f"{post_resp.text[:200]}"
        )
    return post_resp


class MediumAPIAdapter(Publisher):
    """Publishes to Medium via the official API v1 (Integration Token auth).

    Raises DependencyError if no token configured — dispatcher falls through
    to the browser fallback adapter.
    Raises ExternalServiceError for auth failures or rate-limits — no fallthrough.
    """

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        session = SessionManager(DefaultCredentialProvider()).get_session("medium", config)

        t0 = time.monotonic()
        article_id = payload.get("id", "")
        log.info(_json_log(adapter="medium-api", phase="start", id=article_id))

        user_id = _fetch_medium_user_id(session)
        log.info(_json_log(adapter="medium-api", phase="lookup", id=article_id))

        tags = payload.get("tags", [])[:5]
        # Plan 2026-05-18-006 Unit 5 R9: extract_publish_html selects the
        # source format per platform tier. medium is **platform-tier (b)**
        # per the most-restrictive-tier rollup (MediumAPI alone is tier (a)
        # but the dispatcher falls back to MediumBrave/MediumBrowser whose
        # WYSIWYG paste sanitize is lossy). v1 conservative: helper renders
        # content_markdown for medium even when content_html is present —
        # validate-time gate (Unit 6) rejects content_html-only rows for
        # medium before they reach this code path.
        content_html = extract_publish_html(payload, "medium")
        canonical_url = payload.get("seo", {}).get("canonical_url") or None

        publish_status = "public" if mode == "publish" else "draft"
        body: dict[str, Any] = {
            "title": payload.get("title", ""),
            "contentFormat": "html",
            "content": content_html,
            "tags": tags,
            "publishStatus": publish_status,
        }
        if canonical_url:
            body["canonicalUrl"] = canonical_url

        post_resp = _create_medium_post(user_id, session, body)

        data = post_resp.json().get("data", {})
        url = data.get("url", "")
        elapsed = int((time.monotonic() - t0) * 1000)
        log.info(
            _json_log(adapter="medium-api", phase="done", id=article_id, elapsed_ms=elapsed)
        )

        if mode == "publish":
            meta: dict[str, Any] = {}
            if url:
                attr_check = verify_link_attributes(
                    url, target_urls=required_link_urls(payload)
                )
                meta["link_attr_verification"] = attr_check
                ratio = attr_check.get("blank_ratio", 1.0)
                total = attr_check.get("total_anchors", 0)
                if attr_check.get("verification") == "ok" and total > 0 and ratio < 0.5:
                    log.warning(
                        _json_log(
                            adapter="medium-api",
                            phase="attr-warn",
                            id=article_id,
                            msg=(
                                f"Medium stripped target attributes: "
                                f"{attr_check['blank_anchors']}/{total} anchors "
                                "retain target=_blank"
                            ),
                        )
                    )
            return AdapterResult(
                status="published",
                adapter="medium-api",
                platform="medium",
                published_url=url,
                post_publish_delay_seconds=_post_publish_delay_s(),
                _provider_meta=meta if meta else None,
            )
        return AdapterResult(
            status="drafted",
            adapter="medium-api",
            platform="medium",
            draft_url=url,
            post_publish_delay_seconds=_post_publish_delay_s(),
        )
