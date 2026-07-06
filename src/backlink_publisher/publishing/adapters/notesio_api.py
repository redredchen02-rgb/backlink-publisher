"""notes.io adapter — anonymous AJAX publishing (Plan 2026-06-05-015).

notes.io migrated from a server-rendered form-POST (→ redirect) to a client-side
AJAX flow.  Live contract as of 2026-06-05 diagnostic:
  POST https://notes.io/short.php  application/x-www-form-urlencoded
  field: txt=<content>             (no token field)
  response: 200 + HTML fragment injected into #sonuc — first href is the permalink.

dofollow confirmed 12/0 on 3rd-party posts (2026-06-01 discovery run);
OUR-pipeline canary pending — registered dofollow="uncertain".
"""

from __future__ import annotations

import re
import time
from typing import Any

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.publishing.registry import Publisher, get_platform_throttle_seconds

from .base import AdapterResult
from .http_form_post import attach_link_verification, submit_form
from .link_attr_verifier import required_link_urls

_NOTESIO_ENDPOINT = "https://notes.io/short.php"
_PERMALINK_RE = re.compile(r'href="(https://notes\.io/[^"]+)"')
_ADAPTER = "notesio-form-post"
_PLATFORM = "notesio"
_DEFAULT_POST_PUBLISH_DELAY_S: int = 10


def _post_publish_delay_s() -> int:
    return get_platform_throttle_seconds(
        platform="notesio",
        env_var="NOTESIO_PUBLISH_DELAY_S",
        default=_DEFAULT_POST_PUBLISH_DELAY_S,
    )
    from backlink_publisher.config import load_config
    toml_val = load_config().platform_throttle.get("notesio")
    if toml_val is not None:
        return int(toml_val)
    return _DEFAULT_POST_PUBLISH_DELAY_S


class NotesioFormPostAdapter(Publisher):
    """Anonymous form-POST publisher for notes.io.

    No config, credentials, or browser needed — direct HTTP form submission
    with no CSRF preflight required.
    """

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        t0 = time.monotonic()
        article_id = payload.get("id", "")
        title = (payload.get("title") or "").strip()
        log.info("notesio_publish_start", id=article_id, title=title)

        content_md = payload.get("content_markdown") or payload.get("content_md") or ""
        if not content_md.strip():
            raise ExternalServiceError("notes.io payload has no content_markdown")

        body = f"# {title}\n\n{content_md}" if title else content_md

        post_data: dict[str, str] = {"txt": body}
        submit_resp = submit_form(_NOTESIO_ENDPOINT, post_data)

        html = submit_resp.text or ""
        m = _PERMALINK_RE.search(html)
        if not m:
            raise ExternalServiceError(
                f"notes.io /short.php returned no permalink: {html[:200]!r}"
            )
        published_url = m.group(1)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "notesio_publish_done",
            id=article_id,
            url=published_url,
            elapsed_ms=elapsed_ms,
        )

        if mode == "draft":
            return AdapterResult(
                status="drafted",
                adapter=_ADAPTER,
                platform=_PLATFORM,
                draft_url=published_url,
                post_publish_delay_seconds=_post_publish_delay_s(),
            )
        meta = attach_link_verification(published_url, target_urls=required_link_urls(payload))
        return AdapterResult(
            status="published",
            adapter=_ADAPTER,
            platform=_PLATFORM,
            published_url=published_url,
            post_publish_delay_seconds=_post_publish_delay_s(),
            _provider_meta=meta,
        )
