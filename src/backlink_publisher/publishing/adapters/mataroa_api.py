"""Mataroa adapter — publishes Markdown posts via the Mataroa REST API.

Plan 2026-06-01-007 Unit 2 (Wave 1 dofollow channels). Implements the R9
extension recipe on the devto token-REST archetype.

DOFOLLOW NOTICE:

    A 2026-06-01 third-party live probe (``verify_link_attributes`` on real
    public posts) found outbound external links carry no rel (= dofollow) and
    ``site:mataroa.blog`` returns fresh indexed content. The adapter ships
    ``dofollow="uncertain"`` pending an OUR-pipeline canary confirming our own
    placed link renders dofollow on our own published post (the
    hashnode/substack/hatena discipline). The platform currently tolerates
    marketing posts, so it could tighten — confirm before amending to ``True``.

Design choices (mirrors ``hackmd_api.py`` / ``devto_api.py``):

  - **Bearer auth** — Mataroa uses ``Authorization: Bearer <token>``.
    Centralised in ``_required_headers``.
  - **title + body** — the API body is ``{title, body}`` (Markdown); Mataroa
    derives the slug from the title server-side.
  - **published_url** — taken from the API response ``url``; the per-user
    subdomain shape (``<user>.mataroa.blog/blog/<slug>/``) cannot be composed
    offline without the username, so a missing ``url`` is a hard error.
  - **R9** — never log the token or the Authorization header.
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config, load_mataroa_token
from backlink_publisher.http import post as http_post
from backlink_publisher.publishing.content_negotiation import extract_publish_html
from backlink_publisher.publishing.registry import get_platform_throttle_seconds, Publisher

from .base import AdapterResult
from .retry import retry_transient_call, RETRYABLE_HTTP_STATUSES

MATAROA_POSTS_API = "https://mataroa.blog/api/posts/"
_HTTP_TIMEOUT_S = 30
_DEFAULT_POST_PUBLISH_DELAY_S: int = 15


def _post_publish_delay_s() -> int:
    return get_platform_throttle_seconds(
        platform="mataroa",
        env_var="MATAROA_PUBLISH_DELAY_S",
        default=_DEFAULT_POST_PUBLISH_DELAY_S,
    )
    from backlink_publisher.config import load_config
    toml_val = load_config().platform_throttle.get("mataroa")
    if toml_val is not None:
        return int(toml_val)
    return _DEFAULT_POST_PUBLISH_DELAY_S


def _required_headers(token: str) -> dict[str, str]:
    """Mataroa's required headers — Bearer token."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _require_secure_mode(path: Any) -> None:
    """R10: refuse a group/world-readable token file (mirrors telegraph/livejournal)."""
    if path.exists():
        from backlink_publisher._util.permissions import check_0600
        check_0600(path, label="Mataroa token file")


def _load_token(config: Config) -> str:
    """Return the API token, raising DependencyError when not configured."""
    tp = config.token_path("mataroa")
    _require_secure_mode(tp)
    data = load_mataroa_token(tp)
    token: str = cast(str, (data or {}).get("token", "")).strip()
    if not token:
        raise DependencyError(
            "Mataroa API token not configured. "
            f'Write {{"token": "<token>"}} to {tp} '
            "(chmod 600). Enable at mataroa.blog → account settings → API."
        )
    return token


def _build_post_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the Mataroa ``POST /api/posts/`` request body ({title, body})."""
    title = payload.get("title", "Untitled")
    body = (
        payload.get("content_markdown")
        or extract_publish_html(payload, "mataroa")
        or ""
    )
    return {"title": title, "body": body}


class MataroaAPIAdapter(Publisher):
    """Publishes Markdown posts to Mataroa via the REST API.

    dofollow="uncertain" pending an OUR-pipeline canary — see module docstring.
    """

    @classmethod
    def available(cls, config: Config) -> bool:
        """Return True when mataroa-token.json exists with a non-empty token."""
        data = load_mataroa_token(config.token_path("mataroa"))
        if not data:
            return False
        return bool((data.get("token") or "").strip())

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        t0 = time.monotonic()
        article_id = payload.get("id", "")
        log.info(json.dumps(dict(adapter="mataroa", phase="start", id=article_id)))

        token = _load_token(config)
        post_payload = _build_post_payload(payload)

        if mode == "draft":
            log.info(json.dumps(dict(
                adapter="mataroa", phase="draft-skip", id=article_id,
            )))
            return AdapterResult(
                status="drafted",
                adapter="mataroa",
                platform="mataroa",
                draft_url="https://mataroa.blog/",
                post_publish_delay_seconds=_post_publish_delay_s(),
            )

        def execute() -> Any:
            resp = http_post(
                MATAROA_POSTS_API,
                headers=_required_headers(token),
                json=post_payload,
                timeout=_HTTP_TIMEOUT_S,
            )
            if resp.status_code == 401:
                raise ExternalServiceError(
                    "Mataroa API token rejected (HTTP 401) — re-enable at "
                    "mataroa.blog → account settings → API and re-save to "
                    "mataroa-token.json"
                )
            if resp.status_code not in (200, 201):
                raise ExternalServiceError(
                    f"Mataroa API returned HTTP {resp.status_code}: {resp.text[:200]}"
                )
            try:
                body = resp.json()
            except ValueError as exc:
                raise ExternalServiceError(
                    f"Mataroa returned non-JSON response: {exc}"
                )
            if not body.get("ok", False):
                raise ExternalServiceError(
                    f"Mataroa rejected post: {str(body)[:200]}"
                )
            published_url = (body.get("url") or "").strip()
            if not published_url:
                raise ExternalServiceError(
                    "Mataroa createPost returned no url — check API response shape"
                )
            return published_url

        try:
            published_url = retry_transient_call(
                execute,
                is_retryable=lambda exc: (
                    isinstance(exc, ExternalServiceError)
                    and any(
                        f"HTTP {code}" in str(exc)
                        for code in RETRYABLE_HTTP_STATUSES
                    )
                ),
                adapter="mataroa",
            )
        except (DependencyError, ExternalServiceError):
            raise
        # debt: mataroa-api-publish-boilerplate-accepted
        except Exception as exc:
            raise ExternalServiceError(
                f"Mataroa publish failed ({type(exc).__name__}): {exc}"
            ) from exc

        elapsed = int((time.monotonic() - t0) * 1000)
        log.info(json.dumps(dict(
            adapter="mataroa", phase="done", id=article_id, elapsed_ms=elapsed,
        )))
        return AdapterResult(
            status="published",
            adapter="mataroa",
            platform="mataroa",
            published_url=published_url,
            post_publish_delay_seconds=_post_publish_delay_s(),
        )
