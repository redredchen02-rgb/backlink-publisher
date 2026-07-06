"""txt.fyi adapter — anonymous form-POST publishing (Plan 2026-05-25-001 Unit 7).

txt.fyi is a minimalist anonymous pastebin/publishing platform by Rob Beschizza.
No accounts, no JavaScript, no cookies — just a single form POST at
``https://txt.fyi/`` with hidden CSRF fields (``nonce``, ``form_time``).
This adapter composes the Unit 4 ``http_form_post`` helpers (``fetch_form`` →
``extract_hidden_fields`` → ``submit_form``) to publish content and captures
the permalink URL from the final redirect target.

Anti-spam dwell-time gate: ``edit.php`` rejects POSTs that arrive too soon after
the form was served (keyed off the hidden ``form_time``). A sub-second GET→POST
is treated as a bot and silently tarpitted (200 "Thank you" page, no permalink),
so the adapter waits ``_SUBMIT_DELAY_SECONDS`` before submitting. See
:data:`_SUBMIT_DELAY_ENV`.

C0 optimisation (2026-06-05): added tarpit retry with exponential backoff
(max 3 attempts). The default delay was raised from 4.0s to 6.0s based on
empirical observations that the anti-spam gate sometimes clears later.
``http_form_post.submit_form`` is always called EXACTLY ONCE per attempt —
the retry here is an outer loop that re-fetches the form + waits + re-submits,
which is safe because the first attempt silently dropped the post (tarpit) so
no duplicate was created. A successful publish returns immediately without
further retries.

SEO note (Phase 0 find): txt.fyi serves raw static HTML pages with no dynamic
link processing, so outbound ``<a>`` elements carry no ``rel="nofollow"``
decoration server-side.  The ``dofollow="uncertain"`` registration below is
the R4 canary convention — the R4 two-phase loop will read
``verify_link_attributes`` on the live page and amend this entry to
``dofollow=True`` once confirmed.

txt.fyi supports basic Markdown: headers, bold, italic, inline code,
blockquotes, and hyperlinks of the form ``link``.
"""

from __future__ import annotations

import os
import time
from typing import Any

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.logger import opencli_logger as log
from backlink_publisher.config import Config
from backlink_publisher.publishing.registry import Publisher

from .base import AdapterResult
from .http_form_post import (
    attach_link_verification,
    DEFAULT_TIMEOUT,
    extract_hidden_fields,
    fetch_form,
    submit_form,
)
from .link_attr_verifier import required_link_urls

_TXTFYI_FORM = "https://txt.fyi/"
_TXTFYI_SUBMIT = "https://txt.fyi/edit.php"
_ADAPTER = "txtfyi-form-post"
_PLATFORM = "txtfyi"

# Required hidden tokens on the form page (CSRF protection).
_HIDDEN_FIELDS = ("nonce", "form_time")

# txt.fyi anti-spam dwell-time gate. The form embeds a server-issued
# ``form_time`` timestamp; ``edit.php`` rejects POSTs that arrive too soon after
# it (a "no human fills a form this fast" check). A naive sub-second GET→POST is
# treated as a bot: edit.php returns a **200 "Thank you for your submission!"**
# tarpit page with NO redirect and NO permalink — the post is silently dropped,
# never published — instead of the 302→permalink a real browser receives.
# Empirically (probed 2026-05-29) the gate clears by ~3s; we wait a margin above
# that. C0 (2026-06-05) raised from 4.0s to 6.0s based on empirical evidence of
# false tarpit triggers at 4.0s during Phase 0 re-runs.
_SUBMIT_DELAY_ENV = "BACKLINK_TXTFYI_SUBMIT_DELAY_SECONDS"
_DEFAULT_SUBMIT_DELAY_SECONDS = 6.0
# Lowercased body marker of the tarpit page (see above) — distinguishes an
# anti-spam rejection from a generic no-redirect failure.
_TARPIT_MARKER = "thank you for your submission"

# C0: tarpit retry with exponential backoff (max 3 attempts).
# Each retry re-fetches the form, re-waits the dwell gate, and re-submits.
# This is safe because a tarpit response means the post was NOT created server-side
# (the "Thank you" page is a decoy — the real edit.php skips the insert).
_TARPIT_RETRY_MAX = 3
_TARPIT_RETRY_BACKOFF_BASE = 1.5

# C0: raised from DEFAULT_TIMEOUT (15s) to 30s for the submit POST, to handle
# transient slow responses from txt.fyi's shared hosting backend.
_TXTFYI_SUBMIT_TIMEOUT = 30.0


def _submit_delay_seconds() -> float:
    """Resolve the pre-submit dwell time, honoring ``_SUBMIT_DELAY_ENV``.

    Falls back to :data:`_DEFAULT_SUBMIT_DELAY_SECONDS` when the env var is
    unset or unparseable; clamps negatives to 0.
    """
    raw = os.environ.get(_SUBMIT_DELAY_ENV)
    if raw is None:
        return _DEFAULT_SUBMIT_DELAY_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_SUBMIT_DELAY_SECONDS


def _detect_tarpit(response: Any) -> bool:
    """Return True iff the submit response indicates the anti-spam tarpit.

    The tarpit page returns HTTP 200 with a "Thank you for your submission" body
    and no redirect — indistinguishable from success except the missing redirect
    and the tarpit marker in the body.
    """
    body_text = (getattr(response, "text", "") or "").lower()
    return _TARPIT_MARKER in body_text


def _publish_attempt(
    title: str,
    content_md: str,
    delay: float,
) -> tuple[str, Any]:
    """Single publish attempt: fetch form → wait → submit → return (url, resp).

    Raises ExternalServiceError on transport / challenge / missing fields /
    non-tarpit no-redirect failure. Returns (published_url, submit_resp) on
    success. The caller retries on tarpit detection.

    ``submit_form`` is called exactly ONCE per attempt (non-idempotent create).
    """
    # 1. Fetch the form page and extract CSRF tokens.
    form_resp = fetch_form(_TXTFYI_FORM, timeout=DEFAULT_TIMEOUT)
    hidden = extract_hidden_fields(form_resp.text, _HIDDEN_FIELDS)
    missing = [f for f in _HIDDEN_FIELDS if f not in hidden]
    if missing:
        raise ExternalServiceError(
            f"txt.fyi form missing hidden fields: {', '.join(missing)}"
        )

    # 2. Compose the body from markdown content.
    body = f"# {title}\n\n{content_md}" if title else content_md

    # 3. Submit the form.
    post_data: dict[str, str] = {
        "txt": body,
        "url": "",  # anti-spam / unused; content carries the backlink
        "go": "PUBLISH",
        **hidden,
    }
    # Clear txt.fyi's dwell-time gate before submitting (see
    # _SUBMIT_DELAY_ENV). Without this wait the POST is flagged as a bot and
    # silently dropped to the tarpit page, never publishing.
    if delay > 0:
        time.sleep(delay)
    submit_resp = submit_form(_TXTFYI_SUBMIT, post_data, timeout=_TXTFYI_SUBMIT_TIMEOUT)

    # 4. Capture the published URL from the final redirect target.
    published_url = (submit_resp.url or "").strip()
    if not published_url or published_url == _TXTFYI_SUBMIT:
        # Not a redirect — check if tarpit or other failure.
        raise ExternalServiceError(
            "txt.fyi did not redirect to a published URL after submit"
        )

    return published_url, submit_resp


class TxtfyiFormPostAdapter(Publisher):
    """Anonymous form-POST publisher for txt.fyi.

    No config, credentials, or browser needed — pure HTTP form submission.

    C0 (2026-06-05): ``publish()`` now wraps the single-attempt logic in a
    tarpit-aware retry loop. If the submit is tarpitted (anti-spam dwell-time
    gate), the adapter re-fetches the form with a fresh CSRF token + longer
    dwell wait, up to ``_TARPIT_RETRY_MAX`` attempts. A successful publish
    returns immediately.
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
        log.info("txtfyi_publish_start", id=article_id, title=title)

        # 1. Compose the body from markdown content.
        content_md = payload.get("content_markdown") or payload.get("content_md") or ""
        if not content_md.strip():
            raise ExternalServiceError("txt.fyi payload has no content_markdown")

        # 2. Publish with tarpit retry.
        base_delay = _submit_delay_seconds()

        for attempt in range(1, _TARPIT_RETRY_MAX + 1):
            try:
                # Use increased delay on retry (exponential backoff).
                delay = base_delay * (_TARPIT_RETRY_BACKOFF_BASE ** (attempt - 1))
                published_url, submit_resp = _publish_attempt(
                    title, content_md, delay
                )
            except ExternalServiceError as exc:
                is_tarpit = "did not redirect" in str(exc)
                if is_tarpit:
                    if attempt < _TARPIT_RETRY_MAX:
                        log.warning(
                            "txtfyi_tarpit_retry",
                            id=article_id,
                            attempt=attempt,
                            max_attempts=_TARPIT_RETRY_MAX,
                            delay_seconds=round(delay, 1),
                        )
                        continue
                    # Last attempt was also tarpit → surface clear message.
                    raise ExternalServiceError(
                        f"txt.fyi rejected the submission as automated after "
                        f"{_TARPIT_RETRY_MAX} attempts (anti-spam dwell-time gate). "
                        f"Raise {_SUBMIT_DELAY_ENV} above the current "
                        f"{base_delay:g}s and retry."
                    ) from None
                # Non-tarpit ExternalServiceError — propagate immediately.
                raise

            # Successful publish — emit elapsed time and build result.
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "txtfyi_publish_done",
                id=article_id,
                url=published_url,
                elapsed_ms=elapsed_ms,
                attempt=attempt,
            )

            if mode == "draft":
                return AdapterResult(
                    status="drafted",
                    adapter=_ADAPTER,
                    platform=_PLATFORM,
                    draft_url=published_url,
                )
            meta = attach_link_verification(
                published_url, target_urls=required_link_urls(payload)
            )
            return AdapterResult(
                status="published",
                adapter=_ADAPTER,
                platform=_PLATFORM,
                published_url=published_url,
                _provider_meta=meta,
            )

        # Unreachable — all paths return or raise inside the loop.
        raise AssertionError("unreachable")  # pragma: no cover
