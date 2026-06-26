"""History entry re-verification service.

Plan 2026-05-19-006 Unit 5. The publish pipeline already records
``*_unverified`` status when post-publish verify fails (CLI flow), and
older history entries may have been recorded under the old "hard-write
status='published'" code path even though the article never appeared.

This service re-fetches each entry's ``article_urls`` and updates the real
status. The default ``verify_fn`` routes through the shared
:func:`backlink_publisher.recheck.probe.probe_liveness` engine (Plan
2026-05-29-004 U2) so the WebUI recheck and the ``recheck-backlinks`` CLI share
one liveness implementation and can never disagree about the same URL.
``verify_fn`` is parameterised so tests can inject a fake without going out to
the real network (which the autouse conftest fixtures block).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from backlink_publisher.linkcheck.verify import VerificationResult

# Type alias for the injection point: same signature as `verify_published`.
VerifyFn = Callable[..., VerificationResult]


def _default_verify(
    url: str,
    *,
    title: str = "",
    required_link_urls: Sequence[str] = (),
    max_wait: int = 10,
    article_id: int | None = None,
    platform: str | None = None,
    host: str | None = None,
    **_kwargs,
) -> VerificationResult:
    """Route the WebUI recheck through the shared ``probe_liveness`` engine so
    the WebUI manual recheck and the ``recheck-backlinks`` CLI can never give
    contradictory liveness judgments about the same URL (Plan 2026-05-29-004 U2
    / origin R1 — single recheck engine).

    Maps the 5-verdict taxonomy back to the ``(ok, reason)`` contract
    ``recheck_one`` consumes: a present backlink (``alive``/``dofollow_lost``)
    -> ``ok=True``; ``host_gone``/``link_stripped``/``probe_error`` ->
    ``ok=False``. ``title`` is accepted for signature compatibility; the anchor
    inspection (target present + its own ``rel``) is a stronger liveness signal
    than the old title-substring check.

    The full verdict is also persisted as a ``link.rechecked`` event (when
    ``article_id`` is known) so a manual WebUI recheck immediately feeds the R6
    dofollow badge and the R5 survival dashboard, instead of waiting for the
    weekly CLI job. ``platform`` is required for ``probe_liveness`` to classify
    ``expected_nofollow`` (and the dofollow verdict) per the channel's norm.
    """
    from backlink_publisher.recheck import verdicts
    from backlink_publisher.recheck.probe import probe_liveness

    target = required_link_urls[0] if required_link_urls else ""
    out = probe_liveness(url, target, platform=platform, timeout=max_wait)
    _persist_recheck_verdict(
        out, live_url=url, target_url=target,
        article_id=article_id, platform=platform, host=host,
    )
    ok = out["verdict"] in (verdicts.ALIVE, verdicts.DOFOLLOW_LOST)
    return VerificationResult(ok=ok, reason=out.get("reason") or out["verdict"])


def _persist_recheck_verdict(
    out: dict,
    *,
    live_url: str,
    target_url: str,
    article_id: int | None,
    platform: str | None,
    host: str | None,
) -> None:
    """Append one ``link.rechecked`` event carrying the probe verdict so the R6
    badge + R5 survival read it immediately. Best-effort: a write failure, a row
    with no ``article_id`` (the badge join keys on it), or a liveness-only probe
    (no operator link → ``probe_liveness`` short-circuits to ALIVE without a
    dofollow check, which would render a false-green badge) all skip the write
    and leave the row at its no-signal default. Payload mirrors
    ``events_io.emit_recheck`` so the read side is identical to the CLI path.
    """
    if article_id is None or not target_url:
        return
    from backlink_publisher.events.kinds import LINK_RECHECKED
    from backlink_publisher.events.publish_writer import write_event

    write_event(
        LINK_RECHECKED,
        {
            "verdict": out.get("verdict"),
            "reason": out.get("reason"),
            "live_url": live_url,
            "platform": platform,
            "expected_nofollow": bool(out.get("expected_nofollow")),
            "confirmed_dofollow": bool(out.get("confirmed_dofollow", False)),
            "confirmed_nofollow": bool(out.get("confirmed_nofollow", False)),
            "source": "webui_recheck",
        },
        target_url=target_url or None, host=host, article_id=article_id,
    )


@dataclass
class RecheckSummary:
    checked: int = 0
    confirmed: int = 0          # was unverified/failed → became published/drafted
    downgraded_to_failed: int = 0  # was published/_unverified → now failed
    skipped: int = 0            # no article_urls / unrecheckable

    def as_flash(self) -> str:
        return (
            f"已核实 {self.checked} 条："
            f"{self.confirmed} 升为已发布，"
            f"{self.downgraded_to_failed} 标为失败，"
            f"{self.skipped} 跳过"
        )


def _resolve_required_link(item: dict) -> list[str]:
    target = (item.get("target_url") or "").strip()
    return [target] if target else []


def _final_status_for(original: str, ok: bool) -> str:
    """Map (original status, verify ok?) to the new status to persist."""
    if ok:
        # Strip an ``_unverified`` suffix when verify confirms the post.
        if original.endswith("_unverified"):
            return original[: -len("_unverified")]
        if original in ("failed", "unknown"):
            return "published"
        return original
    # ok=False — verify could not find title + anchor on the live page
    return "failed"


def recheck_one(
    item: dict,
    *,
    verify_fn: VerifyFn = _default_verify,
    max_wait_per_url: int = 10,
) -> dict:
    """Re-verify a single history item.

    Returns a dict of mutations to merge into the item:
    ``status``, ``verify_error`` (only on failure), ``verified_at``,
    plus an ``_outcome`` key consumed by :func:`recheck_many` for the
    summary count.
    """
    article_urls: Sequence[str] = _resolve_article_urls(item)
    title = item.get("title", "")
    required_links = _resolve_required_link(item)
    original_status = item.get("status", "")
    # Identity for the link.rechecked event the verify_fn persists (so a manual
    # recheck feeds the badge/survival). events.db rows carry an int article_id
    # as ``id``; legacy/non-numeric ids → None → no write (badge stays default).
    try:
        article_id: int | None = int(item.get("id"))
    except (TypeError, ValueError):
        article_id = None
    platform = item.get("platform") or None
    host = item.get("host") or None

    if not article_urls:
        return {
            "status": "failed",
            "verify_error": "no article URL to verify",
            "verified_at": datetime.now().isoformat(timespec="seconds"),
            "_outcome": "skipped",
        }

    last_reason = "no verifiable URL"
    for url in article_urls:
        try:
            result = verify_fn(
                url,
                title=title,
                required_link_urls=required_links,
                max_wait=max_wait_per_url,
                article_id=article_id,
                platform=platform,
                host=host,
            )
        except Exception as exc:
            last_reason = f"verify error: {exc}"
            continue
        if result.ok:
            new_status = _final_status_for(original_status, ok=True)
            return {
                "status": new_status,
                "verified_at": datetime.now().isoformat(timespec="seconds"),
                "_outcome": "confirmed",
                # clear stale verify_error if any
                "verify_error": None,
            }
        last_reason = result.reason or last_reason

    new_status = _final_status_for(original_status, ok=False)
    return {
        "status": new_status,
        "verify_error": last_reason,
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "_outcome": "downgraded",
    }


def _resolve_article_urls(item: dict) -> list[str]:
    urls = item.get("article_urls")
    if isinstance(urls, Sequence) and not isinstance(urls, (str, bytes)):
        resolved = [str(url).strip() for url in urls if str(url).strip()]
        if resolved:
            return resolved

    for key in ("published_url", "draft_url", "target_url"):
        url = str(item.get(key, "") or "").strip()
        if url:
            return [url]
    return []


def recheck_many(
    items: list[dict],
    *,
    verify_fn: VerifyFn = _default_verify,
    max_wait_per_url: int = 10,
) -> tuple[dict[str, dict], RecheckSummary]:
    """Verify a batch of items. Returns ``(id -> mutation_dict, summary)``.

    Caller is responsible for applying the mutations via
    ``history_store.bulk_update`` / ``update_item``.
    """
    by_id: dict[str, dict] = {}
    summary = RecheckSummary()
    for item in items:
        item_id = item.get("id")
        if not item_id:
            continue
        mutation = recheck_one(
            item, verify_fn=verify_fn, max_wait_per_url=max_wait_per_url,
        )
        outcome = mutation.pop("_outcome", None)
        # Strip None values so bulk_update doesn't overwrite with literal nulls
        # unless intended (verify_error=None is intentional to clear stale errors).
        by_id[item_id] = mutation
        summary.checked += 1
        if outcome == "confirmed":
            summary.confirmed += 1
        elif outcome == "downgraded":
            summary.downgraded_to_failed += 1
        elif outcome == "skipped":
            summary.skipped += 1
    return by_id, summary
