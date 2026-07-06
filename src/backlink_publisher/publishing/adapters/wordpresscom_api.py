from __future__ import annotations

import json
import time
from typing import Any

from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config, load_wordpresscom_token
from backlink_publisher.http import post as http_post
from backlink_publisher.publishing.content_negotiation import extract_publish_html
from backlink_publisher.publishing.registry import Publisher, get_platform_throttle_seconds

from .base import AdapterResult
from .retry import retry_transient_call, RETRYABLE_HTTP_STATUSES

WPCOM_API_BASE = "https://public-api.wordpress.com/rest/v1.1"
_HTTP_TIMEOUT_S = 30
_DEFAULT_POST_PUBLISH_DELAY_S: int = 15


def _post_publish_delay_s() -> int:
    return get_platform_throttle_seconds(
        platform="wordpresscom",
        env_var="WORDPRESSCOM_PUBLISH_DELAY_S",
        default=_DEFAULT_POST_PUBLISH_DELAY_S,
    )
    from backlink_publisher.config import load_config
    toml_val = load_config().platform_throttle.get("wordpresscom")
    if toml_val is not None:
        return int(toml_val)
    return _DEFAULT_POST_PUBLISH_DELAY_S


class WordpresscomAPIAdapter(Publisher):
    post_publish_delay_seconds: int = _DEFAULT_POST_PUBLISH_DELAY_S

    @classmethod
    def available(cls, config: Config) -> bool:
        data = load_wordpresscom_token(config.token_path("wordpresscom"))
        if not data:
            return False
        return bool((data.get("token") or "").strip() and (data.get("site") or "").strip())

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        t0 = time.monotonic()
        article_id = payload.get("id", "")
        log.info(json.dumps(dict(adapter="wordpresscom", phase="start", id=article_id)))

        tp = config.token_path("wordpresscom")
        token_data = load_wordpresscom_token(tp)
        if not token_data:
            raise DependencyError(
                "WordPress.com token not configured. "
                f'Write {{"token": "<access_token>", "site": "<site>"}} '
                f"to {tp} (chmod 600). "
                "Get a token via WP.com OAuth2 flow."
            )
        access_token = (token_data.get("token") or "").strip()
        site = (token_data.get("site") or "").strip()
        if not access_token or not site:
            raise DependencyError(
                "WordPress.com token file missing 'token' or 'site' field"
            )

        title = payload.get("title", "Untitled")
        content = (
            payload.get("content_markdown")
            or extract_publish_html(payload, "wordpresscom")
            or ""
        )

        body: dict[str, Any] = {
            "title": title,
            "content": content,
            "status": "publish",
        }

        if mode == "draft":
            body["status"] = "draft"

        api_url = f"{WPCOM_API_BASE}/sites/{site}/posts/new"
        headers = {"Authorization": f"Bearer {access_token}"}

        def execute() -> Any:
            resp = http_post(
                api_url,
                headers=headers,
                json=body,
                timeout=_HTTP_TIMEOUT_S,
            )
            if resp.status_code == 401:
                raise ExternalServiceError(
                    "WordPress.com token rejected (HTTP 401) — "
                    "regenerate and re-save to wordpresscom-token.json"
                )
            if resp.status_code == 403:
                raise ExternalServiceError(
                    "WordPress.com access forbidden (HTTP 403) — "
                    "check scope/permissions of the token"
                )
            if resp.status_code not in (200, 201):
                raise ExternalServiceError(
                    f"WordPress.com API returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )
            try:
                body_resp = resp.json()
            except ValueError as exc:
                raise ExternalServiceError(
                    f"WordPress.com returned non-JSON response: {exc}"
                )
            post_url = body_resp.get("URL", "")
            if not post_url:
                raise ExternalServiceError(
                    "WordPress.com createPost returned no URL"
                )
            return post_url

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
                adapter="wordpresscom",
            )
        except (DependencyError, ExternalServiceError):
            raise
        # debt: wordpresscom-api-publish-boilerplate-accepted
        except Exception as exc:
            raise ExternalServiceError(
                f"WordPress.com publish failed ({type(exc).__name__}): {exc}"
            ) from exc

        elapsed = int((time.monotonic() - t0) * 1000)
        log.info(json.dumps(dict(
            adapter="wordpresscom", phase="done", id=article_id, elapsed_ms=elapsed,
        )))
        return AdapterResult(
            status="drafted" if mode == "draft" else "published",
            adapter="wordpresscom",
            platform="wordpresscom",
            published_url=published_url,
            post_publish_delay_seconds=_post_publish_delay_s(),
        )
