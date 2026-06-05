"""canary-seed — publish a test post to a dofollow=uncertain platform and verify rel.

For each of the 13 ``dofollow="uncertain"`` platforms in the registry, this
tool publishes a minimal hardcoded test post (no LLM, no plan-backlinks
subprocess), waits for the post to index, then calls ``inspect_target_anchor``
to check whether the target backlink is dofollow / nofollow / ambiguous.

stdout = one JSONL line with the verdict. When the adapter exposes a per-post
deletion secret (e.g. rentry's ``edit_code``, returned once at creation and
never recoverable afterward), it is surfaced as ``delete_credential`` so the
canary post can be cleaned up later instead of becoming an un-deletable orphan.
stderr = a RECON summary plus a human-readable verdict summary and a guided edit
checklist (Plan 2026-06-05-011) telling the operator exactly how to flip the
``dofollow=`` flag (and, on ``dofollow``, which kwargs/``_R`` entry to remove).
exit 0 always — advisory diagnostic, NOT a gate.

Operator acts on the verdict by manually editing the ``dofollow=`` flag in
``src/backlink_publisher/publishing/adapters/__init__.py`` following the printed
checklist. This tool never auto-modifies that file (A5) — it only prints text.

SSRF guard: fail-open (Track A). The post_url comes from the adapter we just
called with our own credentials — it is operator-controlled, not machine-sourced.
If the guard is absent, a stderr warning is emitted.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

# Populate the adapter registry so dofollow_status() and registered_platforms()
# have data before we read them.
import backlink_publisher.publishing.adapters  # noqa: F401

from backlink_publisher._util.errors import DependencyError, PipelineError, UsageError, handle_error
from backlink_publisher._util.logger import PipelineLogger, set_log_level
from backlink_publisher.config import load_config
from backlink_publisher.publishing.adapters import publish, verify_adapter_setup
from backlink_publisher.publishing.adapters.link_attr_verifier import inspect_target_anchor
from backlink_publisher.publishing.registry import dofollow_status, registered_platforms, visibility
from backlink_publisher.cli._canary_flip_hint import format_canary_hint

canary_logger = PipelineLogger("canary-seed")

_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}

# SSRF guard — fail-open (Track A). See module docstring.
try:
    from backlink_publisher._util.net_safety import _check_url_for_ssrf as _ssrf_check
    _SSRF_GUARD_ACTIVE = True
except Exception:  # noqa: BLE001
    _ssrf_check = None  # type: ignore[assignment]
    _SSRF_GUARD_ACTIVE = False


def _sleep(seconds: float) -> None:
    """Monkeypatchable sleep seam."""
    if seconds > 0:
        time.sleep(seconds)


def _validate_post_url_ssrf(url: str) -> Optional[str]:
    """Return block reason if SSRF-dangerous, else None. Fail-open when guard absent."""
    if _ssrf_check is None:
        return None
    return _ssrf_check(url)


def _first_target_url(config: Any) -> Optional[str]:
    """Return first configured [target.*].main_url, or None."""
    ttu = getattr(config, "target_three_url", {})
    if ttu:
        return next(iter(ttu.values())).main_url
    return None


def _build_stub_payload(platform: str, target_url: str) -> dict:
    return {
        "platform": platform,
        "target_url": target_url,
        "title": "canary-seed verification",
        "slug": f"canary-seed-{platform}",
        "content_markdown": (
            f"Verification post for canary-seed. [Visit site]({target_url})."
        ),
        "tags": [],
        "links": [{"url": target_url, "anchor": "Visit site"}],
        "url_mode": "direct",
        "publish_mode": "auto",
    }


# Per-post secrets an adapter may stash in ``AdapterResult._provider_meta`` that
# are required to delete the canary post later (rentry returns an ``edit_code``
# at creation that is never recoverable afterward — without persisting it the
# canary paste becomes an un-deletable orphan).
_DELETE_CREDENTIAL_KEYS = ("edit_code", "delete_token", "delete_url", "deletetoken")


def _extract_delete_credential(result: Any) -> Optional[dict[str, Any]]:
    """Pull deletion secrets out of the adapter result's provider metadata.

    Returns a dict of the delete-relevant keys present in ``_provider_meta``,
    or None when the adapter exposes none. Kept generic so any adapter that
    stashes a delete handle flows into the receipt without canary-seed changes.
    """
    meta = getattr(result, "_provider_meta", None)
    if not meta:
        return None
    creds = {k: meta[k] for k in _DELETE_CREDENTIAL_KEYS if meta.get(k)}
    return creds or None


def _build_delete_hint(
    post_url: str, delete_credential: Optional[dict[str, Any]]
) -> Optional[str]:
    """Human delete instruction; appends the delete credential when present."""
    if not post_url:
        return None
    hint = f"Manual delete required: visit {post_url} and delete this canary post."
    if delete_credential:
        hint += (
            f" Delete credential (keep secret, not recoverable later): "
            f"{json.dumps(delete_credential)}"
        )
    return hint


def _map_verdict(anchor: dict) -> tuple[str, bool, Optional[str]]:
    """Return (verdict, needs_browser_check, reason).

    verdict = "dofollow" | "nofollow" | "ambiguous"
    """
    if not anchor.get("page_readable"):
        return "ambiguous", False, "page_not_readable"
    if not anchor.get("target_anchor_found"):
        return "ambiguous", True, "anchor_not_found"
    if anchor.get("target_is_nofollow"):
        return "nofollow", False, None
    return "dofollow", False, None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="canary-seed",
        description=(
            "Publish a test post to a dofollow=uncertain platform and verify "
            "the rel attribute on the target backlink. Outputs advisory verdict "
            "JSONL on stdout; RECON on stderr; always exit 0."
        ),
    )
    parser.add_argument(
        "platform",
        help="Platform name (must be in dofollow='uncertain' cohort).",
    )
    parser.add_argument(
        "--target-url",
        default=None,
        metavar="URL",
        help="Money-site URL to embed as the backlink target. Defaults to the "
             "first [target.*].main_url in config.toml.",
    )
    parser.add_argument(
        "--wait-after-publish",
        type=int,
        default=15,
        metavar="N",
        help="Seconds to wait after publishing before fetching the post (default: 15).",
    )
    parser.add_argument(
        "--log-level",
        default="WARN",
        metavar="LEVEL",
        help="Log verbosity: DEBUG|INFO|WARN|ERROR (default: WARN)",
    )
    args = parser.parse_args(argv)

    try:
        if args.log_level not in _LOG_LEVELS:
            raise UsageError(
                f"canary-seed: --log-level must be one of {sorted(_LOG_LEVELS)}; "
                f"got {args.log_level!r}"
            )
        set_log_level(args.log_level)

        if not _SSRF_GUARD_ACTIVE:
            print(
                "WARNING: canary-seed SSRF guard inactive (net_safety unavailable). "
                "Post URL from adapter is treated as trusted.",
                file=sys.stderr,
            )

        # A1: validate platform is canary-eligible.
        # Eligible = dofollow="uncertain" AND not retired. Retired platforms
        # (e.g. writeas, hashnode) keep a stale "uncertain" flag but must never
        # be canaried: they have no bound credentials, so publish raises and the
        # run reports a misleading `publish_failed` verdict. Exclude retired both
        # from eligibility and from the hint list — mirrors the
        # `visibility(name) != "retired"` filter in config/_toml_utils.py.
        status = dofollow_status(args.platform)
        eligible = sorted(
            p for p in registered_platforms()
            if dofollow_status(p) == "uncertain" and visibility(p) != "retired"
        )
        if status != "uncertain" or visibility(args.platform) == "retired":
            raise UsageError(
                f"canary-seed: platform {args.platform!r} is not in the "
                f"canary-eligible dofollow='uncertain' cohort "
                f"(status={status!r}, visibility={visibility(args.platform)!r}). "
                f"Eligible platforms: {eligible}."
            )

        config = load_config()

        # A2: resolve target URL
        target_url = args.target_url or _first_target_url(config)
        if not target_url:
            raise DependencyError(
                "canary-seed: no target URL available. Provide --target-url <URL> "
                "or add a [target.*] section to config.toml."
            )

        # A6: offline credential check
        try:
            verify_adapter_setup(args.platform, config, mode="offline")
        except PipelineError as exc:
            raise DependencyError(
                f"canary-seed: no credential configured for {args.platform!r}. "
                f"Run the appropriate login helper first. Details: {exc.message}"
            ) from exc

        # A2: publish minimal stub
        payload = _build_stub_payload(args.platform, target_url)
        t0 = time.monotonic()
        post_url = ""
        verdict = "ambiguous"
        reason: Optional[str] = None
        rel_tokens: Optional[list[str]] = None
        needs_browser_check = False
        delete_credential: Optional[dict[str, Any]] = None

        try:
            result = publish(payload, "auto", config)
            _sleep(args.wait_after_publish)
            post_url = result.published_url or result.draft_url
            delete_credential = _extract_delete_credential(result)
        except PipelineError as exc:
            reason = "publish_failed"
            canary_logger.warn("publish_failed", platform=args.platform, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            reason = "publish_failed"
            canary_logger.warn("publish_exception", platform=args.platform, error=repr(exc))

        # A3: fetch + inspect anchor
        if not post_url:
            if reason is None:
                reason = "no_post_url_returned"
        else:
            # SSRF guard (fail-open for Track A)
            blocked = _validate_post_url_ssrf(post_url)
            if blocked:
                reason = f"ssrf_blocked:{blocked}"
                canary_logger.warn("post_url_ssrf_blocked", platform=args.platform, reason=blocked)
            else:
                try:
                    anchor = inspect_target_anchor(post_url, target_url)
                    verdict, needs_browser_check, reason = _map_verdict(anchor)
                    raw_rel = anchor.get("target_rel") or ""
                    rel_tokens = [t.strip() for t in raw_rel.split() if t.strip()] if raw_rel else []
                except Exception as exc:  # noqa: BLE001
                    reason = "inspect_failed"
                    canary_logger.warn("inspect_failed", platform=args.platform, error=repr(exc))

        duration_s = round(time.monotonic() - t0, 2)
        fetched_at = datetime.now(timezone.utc).isoformat()

        # A4: emit JSONL
        receipt: dict[str, Any] = {
            "platform": args.platform,
            "post_url": post_url,
            "target_url": target_url,
            "verdict": verdict,
            "rel_tokens": rel_tokens,
            "needs_browser_check": needs_browser_check,
            "delete_hint": _build_delete_hint(post_url, delete_credential),
            "delete_credential": delete_credential,
            "fetched_at": fetched_at,
            "duration_s": duration_s,
        }
        if reason is not None:
            receipt["reason"] = reason

        print(json.dumps(receipt))

        # RECON summary on stderr
        canary_logger.recon(
            "canary_seed_result",
            platform=args.platform,
            verdict=verdict,
            post_url=post_url or "(none)",
            needs_browser_check=needs_browser_check,
            ssrf_guard_active=_SSRF_GUARD_ACTIVE,
        )
        if verdict == "ambiguous":
            canary_logger.recon(
                "canary_seed_ambiguous_note",
                reason=reason,
                hint="Inspect post manually or retry with a browser-capable tool.",
            )

        # Operator-facing guided edit checklist (Plan 2026-06-05-011) — stderr only,
        # never mutates source (A5). stdout JSONL above is the unchanged contract.
        # Wrapped so a formatter error can never suppress the verdict or the exit-0
        # advisory contract (the JSONL is already on stdout by this point).
        try:
            print(
                format_canary_hint(
                    args.platform, verdict, post_url, rel_tokens,
                    reason=reason, date=fetched_at[:10],
                ),
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001 — advisory hint must never break exit 0
            canary_logger.warn("flip_hint_failed", platform=args.platform, error=repr(exc))

    except PipelineError as exc:
        handle_error(exc)


if __name__ == "__main__":
    main()
