"""ConfigDrivenAdapter — data-driven Publisher for YAML catalog platforms (U2).

A single ``Publisher`` subclass instantiated per catalog entry. The adapter
uses the validated entry dict to drive publishing behaviour — no Python
subclass per platform is needed.

Two auth archetypes:
  - ``none``: anonymous form-POST (``fetch_form`` → ``extract_hidden_fields`` →
    ``submit_form``). CSRF pre-fetch optional.
  - ``api_key_header`` / ``api_key_query``: REST API POST with a configured
    API key (Bearer header or query parameter).
"""

from __future__ import annotations

import re
import time
from typing import Any

import requests

from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher._util.http_client import http_client
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.publishing.registry import Publisher

from .base import AdapterResult
from .http_form_post import (
    attach_link_verification,
    extract_hidden_fields,
    fetch_form,
    submit_form,
)
from .link_attr_verifier import required_link_urls


def _host(url: str) -> str:
    """Best-effort host extraction for safe error messages (no body)."""
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc or "?"
    except ValueError:
        return "?"


def _resolve_jsonpath(data: Any, path: str) -> str | None:
    """Resolve a simple dot-delimited JSON path (e.g. ``$.data.url``).

    Only supports ``$`` root reference and dot-separated keys. Returns
    ``None`` when any segment is missing.
    """
    if not path.startswith("$"):
        return None
    segments = path.lstrip("$.").split(".")
    current: Any = data
    for segment in segments:
        if not segment:
            continue
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            return None
    return str(current) if current is not None else None


def _resolve_permalink(
    response: requests.Response,
    permalink_via: str,
    permalink_arg: str,
) -> str:
    """Extract the published URL from a POST response.

    Args:
        response: The HTTP response after the create POST.
        permalink_via: ``redirect`` | ``json_path`` | ``regex``.
        permalink_arg: Pattern argument (e.g. ``Location``, ``$.data.url``,
            or a regex).

    Returns:
        The resolved published URL string.

    Raises:
        ExternalServiceError: if the permalink cannot be resolved.
    """
    if permalink_via == "redirect":
        url = (response.url or "").strip()
        if url and url != str(getattr(response, "request", type("", (), {}))()):
            return url
        raise ExternalServiceError(
            f"permalink via redirect failed — no redirect from {_host(response.url)}"
        )

    if permalink_via == "json_path":
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise ExternalServiceError(
                f"permalink via json_path failed — response not JSON: {exc}"
            )
        url_or_none = _resolve_jsonpath(body, permalink_arg)
        if url_or_none:
            return url_or_none
        raise ExternalServiceError(
            f"json_path {permalink_arg!r} resolved to None in response"
        )

    if permalink_via == "regex":
        text = getattr(response, "text", "") or ""
        m = re.search(permalink_arg, text)
        if m:
            return m.group(0)
        raise ExternalServiceError(
            f"regex {permalink_arg!r} did not match response body "
            f"(len={len(text)})"
        )

    raise ExternalServiceError(
        f"unknown permalink_via: {permalink_via!r}"
    )


def _get_api_key(entry: dict[str, Any], config: Config) -> str:
    """Read the API key for this platform from config.

    Looks up ``config.api_keys.get(slug)``. The key may be configured in
    the ``[api_keys]`` TOML section.

    Raises:
        DependencyError: if no key is found (falls through the dispatch
        chain — the next adapter or the terminal "unsupported platform"
        error fires).
    """
    slug = entry["slug"]
    keys: dict[str, str] = getattr(config, "api_keys", {}) or {}
    key = keys.get(slug)
    if not key or not isinstance(key, str) or not key.strip():
        raise DependencyError(
            f"no API key configured for catalog platform {slug!r}; "
            f"set [{slug}.api_key] in config.toml"
        )
    return key.strip()


class ConfigDrivenAdapter(Publisher):
    """Data-driven Publisher for YAML catalog-defined platforms.

    One instance per catalog entry.  The ``publish()`` behaviour is
    determined entirely by the validated entry dict — no subclass needed.
    """

    def __init__(self, entry: dict[str, Any]) -> None:
        self._entry = entry

    # ── Publisher protocol ────────────────────────────────────────────────

    def publish(
        self,
        payload: dict[str, Any],
        mode: str,
        config: Config,
    ) -> AdapterResult:
        entry = self._entry
        slug = entry["slug"]
        t0 = time.monotonic()
        article_id = payload.get("id", "")

        log.info(
            "config_adapter_publish_start",
            platform=slug,
            id=article_id,
            auth_type=entry["auth_type"],
        )

        # 1. Compose the body.
        content_md = (
            payload.get("content_markdown")
            or payload.get("content_md")
            or ""
        )
        if not content_md.strip():
            raise ExternalServiceError(
                f"catalog platform {slug!r}: payload has no content_markdown"
            )
        title = (payload.get("title") or "").strip()
        body = f"# {title}\n\n{content_md}" if title else content_md

        # 2. Publish based on auth type.
        auth_type = entry["auth_type"]
        if auth_type == "none":
            published_url = self._publish_form_post(body, entry, slug)
        else:
            published_url = self._publish_api_post(
                body, entry, slug, config
            )

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "config_adapter_publish_done",
            platform=slug,
            id=article_id,
            url=published_url,
            elapsed_ms=elapsed_ms,
        )

        if mode == "draft":
            return AdapterResult(
                status="drafted",
                adapter=f"{slug}-config-driven",
                platform=slug,
                draft_url=published_url,
                post_publish_delay_seconds=int(entry.get("min_delay_s", 0)),
            )
        meta = attach_link_verification(
            published_url, target_urls=required_link_urls(payload)
        )
        return AdapterResult(
            status="published",
            adapter=f"{slug}-config-driven",
            platform=slug,
            published_url=published_url,
            post_publish_delay_seconds=int(entry.get("min_delay_s", 0)),
            _provider_meta=meta,
        )

    # ── Auth paths ────────────────────────────────────────────────────────

    def _publish_form_post(
        self,
        body: str,
        entry: dict[str, Any],
        slug: str,
    ) -> str:
        """Publish via anonymous form POST."""
        endpoint: str = entry["endpoint"]

        # Optional CSRF prefetch.
        csrf_form_url: str | None = None
        csrf_data: dict[str, str] = {}
        if entry.get("csrf_prefetch"):
            csrf_form_url = entry.get("csrf_form_url") or endpoint
            form_resp = fetch_form(csrf_form_url)
            hidden_names = entry.get("csrf_field_names") or []
            if hidden_names:
                csrf_data = extract_hidden_fields(
                    form_resp.text, hidden_names
                )
                missing = [n for n in hidden_names if n not in csrf_data]
                if missing:
                    raise ExternalServiceError(
                        f"catalog platform {slug!r}: CSRF prefetch "
                        f"missing hidden fields: {', '.join(missing)}"
                    )

        # Dwell-time gate (anti-spam: wait before submit).
        min_delay = entry.get("min_delay_s", 0.0)
        if min_delay > 0:
            time.sleep(min_delay)

        # Submit the form.
        content_field: str = entry.get("content_field", "body")
        post_data: dict[str, str] = {content_field: body, **csrf_data}
        submit_resp = submit_form(endpoint, post_data)

        return _resolve_permalink(
            submit_resp,
            entry["permalink_via"],
            entry["permalink_arg"],
        )

    def _publish_api_post(
        self,
        body: str,
        entry: dict[str, Any],
        slug: str,
        config: Config,
    ) -> str:
        """Publish via REST API POST with API key."""
        endpoint: str = entry["endpoint"]
        auth_type: str = entry["auth_type"]
        api_key = _get_api_key(entry, config)
        content_field: str = entry.get("content_field", "body")

        # Build the request.
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 backlink-publisher"
            ),
        }
        if auth_type == "api_key_header":
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "api_key_query":
            # Prefer X-Api-Key header to avoid exposing the key in URLs and
            # server access logs. The query-param fallback is intentionally
            # removed: keys in URLs appear in proxy logs and Referer headers.
            headers["X-Api-Key"] = api_key

        body_dict: dict[str, Any] = {content_field: body}
        # Optionally include the title.
        # The payload title is already in the body string; some API
        # endpoints prefer a separate ``title`` field.
        title = body.split("\n")[0].lstrip("# ").strip()
        if title:
            body_dict["title"] = title

        url = endpoint

        # Honour min_delay_s.
        min_delay = entry.get("min_delay_s", 0.0)
        if min_delay > 0:
            time.sleep(min_delay)

        try:
            resp = http_client.post(
                url,
                json=body_dict,
                headers=headers,
                timeout=30.0,
                raise_for_status=False,
                allow_private=True,
            )
        except ExternalServiceError:
            # SSRF block / connection failure already a domain error — keep its
            # message (e.g. the SSRF block_reason) rather than masking it.
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f"API POST to {_host(endpoint)} failed "
                f"({type(exc).__name__})"
            ) from exc

        if resp.status_code in (401, 403):
            raise ExternalServiceError(
                f"API POST to {_host(endpoint)} returned "
                f"HTTP {resp.status_code} (check API key)"
            )
        if not (200 <= resp.status_code < 400):
            raise ExternalServiceError(
                f"API POST to {_host(endpoint)} returned "
                f"HTTP {resp.status_code}"
            )

        return _resolve_permalink(
            resp, entry["permalink_via"], entry["permalink_arg"]
        )
