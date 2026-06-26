"""Image-gen adapter — Plan 2026-05-20-001 Unit 2.

Supports two provider protocols:

  * ``provider="openai"`` (default) — POSTs to ``<base_url>/images/generations``
    with the OpenAI body shape (``model``, ``prompt``, ``size``, ``n``,
    ``response_format``).  Auth: ``Authorization: Bearer <api_key>``.

  * ``provider="frw"`` — submits a task via ``POST <base_url>/api/frwapi/v1/tasks``
    then polls ``GET <base_url>/api/frwapi/v1/tasks/{taskId}`` until complete.
    Auth: ``X-Api-Key: <api_key>`` header.

Returns a ``BannerArtifact`` containing the raw image bytes after
MIME sniffing and a 5 MB size cap.

Error taxonomy (both providers):
  * ``401`` → ``RuntimeError`` naming ``frw-login`` (fail-loud, NOT retryable).
  * ``429`` / ``5xx`` / ``Timeout`` / ``ConnectionError`` → wrapped in
    ``_ImageGenTransient`` and retried via ``retry_transient_call``.
  * Other ``4xx`` → ``ExternalServiceError`` (fail-loud, not retryable).
  * Response missing result / unrecognized magic bytes → ``RuntimeError``.
  * Response over 5 MB → ``ExternalServiceError``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from typing import Any, cast

from requests.exceptions import ConnectionError as ReqConnError
from requests.exceptions import Timeout as ReqTimeout

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher.http import get as http_get
from backlink_publisher.http import post as http_post
from backlink_publisher.publishing.adapters.retry import retry_transient_call

from .types import BannerArtifact

_log = logging.getLogger(__name__)

#: Hard cap on the downloaded banner size.  Provider could theoretically
#: return a multi-GB image which would OOM the process; reject above
#: this boundary.  Matches the magnitude of OG / blog cover use cases.
_MAX_RESPONSE_BYTES: int = 5 * 1024 * 1024


class _ImageGenTransient(Exception):
    """Marker exception — 429 / 5xx / Timeout / ConnectionError. Retryable."""


def _is_retryable(exc: Exception) -> bool:
    """Predicate for ``retry_transient_call`` — only our marker class."""
    return isinstance(exc, _ImageGenTransient)


class ImageGenAdapter:
    """Generates a banner from a text prompt.

    Construction is cheap and side-effect-free; ``generate()`` is the
    only network-touching method.  Instances are stateless and safe
    to share across threads.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        banner_size: str,
        api_key: str,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        provider: str = "openai",
        frw_template_id: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.banner_size = banner_size
        self._api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.provider = provider
        self.frw_template_id = frw_template_id

    def generate(self, prompt: str) -> BannerArtifact:
        """Generate a banner for ``prompt`` and return its artifact."""
        if self.provider == "frw":
            return self._generate_frw(prompt)
        return self._generate_openai(prompt)

    def _generate_openai(self, prompt: str) -> BannerArtifact:
        """OpenAI-compatible ``/images/generations`` path."""
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        url = f"{self.base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "size": self.banner_size,
            "n": 1,
            "response_format": "url",
        }

        def _do_post() -> dict[str, Any]:
            try:
                resp = http_post(url, headers=headers, json=body, timeout=self.timeout_s)
            except (ReqTimeout, ReqConnError) as exc:
                raise _ImageGenTransient(str(exc)) from exc

            if resp.status_code == 401:
                raise RuntimeError(
                    "image-gen 401: api_key rejected by gateway. "
                    "Rotate via `frw-login` and rerun."
                )
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise _ImageGenTransient(f"HTTP {resp.status_code}")
            if 400 <= resp.status_code < 500:
                raise ExternalServiceError(f"image-gen {resp.status_code}: {resp.text[:200]}")
            try:
                return cast("dict[str, Any]", resp.json())
            except ValueError as exc:
                raise ExternalServiceError(f"image-gen response not JSON: {exc}") from exc

        try:
            data = retry_transient_call(
                _do_post, is_retryable=_is_retryable, max_attempts=self.max_retries, adapter="image-gen"
            )
        except _ImageGenTransient as exc:
            raise ExternalServiceError(f"image-gen exhausted retries: {exc}") from exc

        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            raise RuntimeError(f"image-gen response missing 'data' or empty: {str(data)[:200]}")
        first = items[0]
        if not isinstance(first, dict):
            raise RuntimeError(f"image-gen response data[0] not an object: {first!r}")

        b64 = first.get("b64_json")
        src_url = first.get("url")
        if b64:
            raw = base64.b64decode(b64)
            source_url: str | None = None
        elif isinstance(src_url, str) and src_url:
            raw = _download_with_cap(src_url)
            source_url = src_url
        else:
            raise RuntimeError(
                f"image-gen response data[0] has neither 'url' nor 'b64_json': {first!r}"
            )

        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ExternalServiceError(
                f"image-gen banner exceeds 5MB cap ({len(raw)} > {_MAX_RESPONSE_BYTES} bytes); "
                "refusing to persist."
            )
        return BannerArtifact(data=raw, mime=_sniff_mime(raw), source_url=source_url, prompt_sha=prompt_sha)

    def _generate_frw(self, prompt: str) -> BannerArtifact:
        """FRW native submit+poll path (``/api/frwapi/v1/tasks``)."""
        if not self.frw_template_id:
            raise RuntimeError(
                "image-gen FRW provider requires frw_template_id in config. "
                "List templates: GET /api/frwapi/v1/templates"
            )
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        headers = {"X-Api-Key": self._api_key, "Content-Type": "application/json"}

        w, h = self.banner_size.split("x") if "x" in self.banner_size else ("1200", "630")
        body: dict[str, Any] = {
            "templateId": self.frw_template_id,
            "clientUserId": "backlink-publisher",
            "parameters": {
                "prompt": prompt,
                "width": w,
                "height": h,
            },
        }

        def _do_submit() -> str:
            try:
                resp = http_post(
                    f"{self.base_url}/api/frwapi/v1/tasks",
                    headers=headers,
                    json=body,
                    timeout=self.timeout_s,
                )
            except (ReqTimeout, ReqConnError) as exc:
                raise _ImageGenTransient(str(exc)) from exc

            if resp.status_code == 401:
                raise RuntimeError(
                    "image-gen FRW 401: api_key rejected. Rotate via `frw-login` and rerun."
                )
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise _ImageGenTransient(f"HTTP {resp.status_code}")
            if 400 <= resp.status_code < 500:
                raise ExternalServiceError(f"image-gen FRW {resp.status_code}: {resp.text[:200]}")
            try:
                payload = resp.json()
            except ValueError as exc:
                raise ExternalServiceError(f"image-gen FRW response not JSON: {exc}") from exc
            task_id = (payload.get("data") or {}).get("taskId") or (payload.get("data") or {}).get("id")
            if not task_id:
                raise ExternalServiceError(f"image-gen FRW submit returned no taskId: {payload}")
            return str(task_id)

        try:
            task_id = retry_transient_call(
                _do_submit, is_retryable=_is_retryable, max_attempts=self.max_retries, adapter="image-gen-frw"
            )
        except _ImageGenTransient as exc:
            raise ExternalServiceError(f"image-gen FRW submit exhausted retries: {exc}") from exc

        # Poll until completed or failed
        poll_headers = {"X-Api-Key": self._api_key}
        deadline = time.time() + self.timeout_s
        result_url: str | None = None
        while time.time() < deadline:
            time.sleep(6)
            try:
                resp = http_get(
                    f"{self.base_url}/api/frwapi/v1/tasks/{task_id}",
                    headers=poll_headers,
                    timeout=15,
                )
            except (ReqTimeout, ReqConnError):
                continue
            if resp.status_code != 200:
                continue
            try:
                poll_data = resp.json().get("data") or {}
            except ValueError:
                continue
            status = poll_data.get("status")
            if status == "completed":
                results = poll_data.get("results") or []
                if results and isinstance(results[0], dict):
                    result_url = results[0].get("url") or results[0].get("imageUrl")
                elif isinstance(results, list) and results:
                    result_url = str(results[0])
                break
            if status in ("failed", "error"):
                raise ExternalServiceError(
                    f"image-gen FRW task failed: {poll_data.get('errorMessage', status)}"
                )

        if not result_url:
            raise ExternalServiceError(
                f"image-gen FRW task {task_id} did not complete within {self.timeout_s}s"
            )

        raw = _download_with_cap(result_url)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ExternalServiceError(
                f"image-gen FRW banner exceeds 5MB cap ({len(raw)} bytes)"
            )
        return BannerArtifact(data=raw, mime=_sniff_mime(raw), source_url=result_url, prompt_sha=prompt_sha)


def _download_with_cap(src_url: str) -> bytes:
    """Follow-up GET on ``data[].url`` mode.

    Reuses the adapter-level ``Authorization`` header is intentionally
    NOT used here — provider CDNs are typically unauthenticated and
    sending the api_key would leak it to a third-party host.  If a
    gateway later requires auth on its CDN, we'd add a per-instance
    flag rather than enabling it globally.
    """
    try:
        resp = http_get(src_url, timeout=30, stream=False)
    except (ReqTimeout, ReqConnError) as exc:
        # Treat as fail-loud at this layer — retry_transient_call has
        # already wrapped the outer POST; a CDN miss is a different
        # failure mode (operator-actionable: provider returned a dead
        # URL) and should not silently retry.
        raise ExternalServiceError(
            f"image-gen source_url GET failed: {exc}"
        ) from exc

    if resp.status_code != 200:
        raise ExternalServiceError(
            f"image-gen source_url unreachable: HTTP {resp.status_code}"
        )

    content = resp.content
    if len(content) > _MAX_RESPONSE_BYTES:
        raise ExternalServiceError(
            f"image-gen banner exceeds 5MB cap on CDN download "
            f"({len(content)} > {_MAX_RESPONSE_BYTES} bytes)"
        )
    return cast("bytes", content)


_MIME_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    # WebP wraps in RIFF/WEBP — the layout is ``RIFF<len4>WEBP...``
    # so we check the first 4 bytes AND bytes 8-11.
    (b"RIFF", "image/webp"),  # confirmed below
)


def _sniff_mime(data: bytes) -> str:
    """Return MIME type by inspecting magic bytes.

    Trusts the file's bytes over any provider-reported Content-Type
    header (which has been observed lying — provider returns
    ``application/octet-stream`` for PNGs).  Unknown formats raise
    ``RuntimeError`` so an HTML 404 page can't disguise itself as
    an image.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise RuntimeError(
        f"image-gen response: unrecognized image format "
        f"(first 16 bytes: {data[:16]!r})"
    )
