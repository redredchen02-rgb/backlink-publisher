"""Shared helpers for publish-backlinks CLI.

Extracted from ``publish_backlinks.py`` to keep the main CLI file focused
on ``main()`` and the publish loop.
"""

from __future__ import annotations

from concurrent.futures import as_completed, ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

from backlink_publisher._util.logger import publish_logger
from backlink_publisher.linkcheck.http import _max_concurrent as _linkcheck_max_concurrent
from backlink_publisher.linkcheck.http import check_url
from backlink_publisher.linkcheck.verify import verify_published

# Re-export names moved to _publish_cli.py during the monolith split
# (Plan 2026-06-01). These re-exports keep existing import paths working
# for the ~30 test and production call sites that import from _publish_helpers.
from ._publish_cli import (  # noqa: F401
    _build_parser,
    _handle_auth_expired,
    _handle_checkpoint_ops,
)

_HTTP_5XX_RE = re.compile(r"\b5[0-9]{2}\b")


def _gate_banner_sentinel() -> Path:
    """Lazy resolver for the gate-banner sentinel path.

    Uses the env-aware ``_cache_dir()`` so the path lands in the test
    sandbox (not real ``~/.cache``) when ``BACKLINK_PUBLISHER_CACHE_DIR``
    is set.  Mirrors the ``frw_token_path()`` pattern in ``_util/secrets.py``.
    """
    from backlink_publisher import config as _cfg

    return _cfg._cache_dir() / "backlink-publisher" / "v0.3-gate-banner-seen"






def _release_acquired_leases(store: Any, acquired: list[str], pid: int) -> None:
    for plat in acquired:
        try:
            store.release_lease(plat, pid)
        except Exception as e:
            publish_logger.warning(f"Failed to release lease on {plat!r}: {e}")


def _acquire_publish_leases(platforms: set[str], dry_run: bool) -> None:
    if dry_run or not platforms:
        return

    import atexit

    from backlink_publisher._util.errors import emit_error
    from backlink_publisher.events.store import EventStore

    store = EventStore()
    pid = os.getpid()
    acquired = []

    for plat in sorted(platforms):
        if store.acquire_lease(plat, pid, ttl_seconds=3600):
            acquired.append(plat)
        else:
            _release_acquired_leases(store, acquired, pid)
            lease_details = store.get_lease(plat)
            owner_info = f"PID {lease_details['owner_pid']}" if lease_details else "unknown"
            emit_error(
                f"error: another publish process ({owner_info}) is currently active for platform {plat!r}. "
                "Aborting to prevent concurrent publishing conflicts.",
                exit_code=3,
            )

    atexit.register(_release_acquired_leases, store, acquired, pid)


def _partition_paused(rows: list[dict[str, Any]], platform_arg: str | None, config: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Split *rows* into (publishable_rows, sorted_paused_platforms).

    A platform an operator paused via /ce:health (``LockedHealthStore.paused``)
    is dropped pre-dispatch (Plan 2026-06-03-004 Phase 2 U8). ``is_paused`` is
    fail-SAFE — a store read error reports not-paused, so a transient fault
    never silently blocks publishing.
    """
    from backlink_publisher.health.persistence import locked_store

    platforms = {platform_arg or r.get("platform", "") for r in rows}
    paused = sorted(p for p in platforms if p and locked_store.is_paused(p, config))
    if not paused:
        return rows, []
    paused_set = set(paused)
    kept = [
        r for r in rows
        if (platform_arg or r.get("platform", "")) not in paused_set
    ]
    return kept, paused


def _maybe_emit_gate_banner(skip_flag: bool) -> None:
    sentinel = _gate_banner_sentinel()
    if skip_flag or sentinel.exists():
        return
    publish_logger.warning(
        f"publish-backlinks now performs a publish-time reachability re-check "
        f"on every row before dispatch. Use --skip-publish-time-check to "
        f"restore prior behavior. This message will not repeat (sentinel: {sentinel})."
    )
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch(exist_ok=True)
    except OSError:
        pass


def _check_row_reachability(row: dict[str, Any]) -> tuple[bool, str | None]:

    urls = [row.get("target_url", "")]
    for link in row.get("links", []):
        if isinstance(link, dict):
            url = link.get("url")
            if url:
                urls.append(url)
    urls = [u for u in urls if u]
    if not urls:
        return True, None

    if len(urls) == 1:
        ok, _err = check_url(urls[0])
        return (True, None) if ok else (False, urls[0])

    workers = min(_linkcheck_max_concurrent(), len(urls))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_url, u): u for u in urls}
        first_failure: str | None = None
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                ok, _err = fut.result()
            except (ConnectionError, TimeoutError, ValueError):
                # Logged (not silenced) then degraded to a failed-reachability
                # result for this one URL; the other futures still complete.
                publish_logger.debug("link_check_future_failed", url=url, exc_info=True)
                ok = False
            if not ok and first_failure is None:
                first_failure = url
                for other in futures:
                    if not other.done():
                        other.cancel()
                break
    if first_failure is not None:
        return False, first_failure
    return True, None


def _canary_gate(
    platform: str,
    *,
    warned: set[str],
) -> tuple[bool, str | None]:
    """Read-side canary health gate for the publish row loop (Plan
    2026-05-27-001 Unit 4).

    Returns ``(skip, reason)``:

    - ``(True, reason)`` → the row must be filtered out of the payload. This
      ONLY happens when the platform is **quarantined** AND its
      ``[canary.<platform>]`` config opts in with ``hard_skip = true``.
    - ``(False, None)`` → proceed. If the platform is merely *degraded*
      (drift-confirmed / quarantined-but-not-opted-in) a single advisory
      WARNING is emitted to stderr — deduped per platform within this
      invocation via ``warned`` so it doesn't spam every row.

    Fail-open: a platform with no canary health (never run / not configured)
    or any error reading the store is treated as healthy → never blocks, no
    spurious warning. The WARNING payload carries ONLY non-sensitive fields
    (platform name, verdict, debounce counts) — never credentials/URLs.
    """
    if not platform:
        return False, None
    try:
        from backlink_publisher.canary.store import (
            get_health,
            is_degraded,
            is_quarantined,
            read_canary_config,
        )

        if not is_degraded(platform):
            return False, None

        if is_quarantined(platform):
            cfg = read_canary_config(platform)
            if cfg is not None and cfg.get("hard_skip"):
                return (
                    True,
                    f"因 canary 漂移已隔離(quarantined),且該平台配置 hard_skip=true → "
                    f"略過 {platform} 的本行發布",
                )

        # Degraded but not hard-skipped → advisory WARNING (deduped per platform).
        if platform not in warned:
            warned.add(platform)
            rec = get_health(platform)
            publish_logger.warning(
                f"[canary] platform={platform} status={rec.get('status')} "
                f"consecutive_failures={rec.get('consecutive_failures')} "
                f"quarantined={rec.get('quarantined')} — "
                f"canary 偵測到契約漂移(advisory,仍照常發布);"
                f"請複查 adapter / 重新 seed canary,或 flip 成 hard_skip"
            )
    except Exception as exc:  # noqa: BLE001 — fail-open: never block publish on canary read error
        publish_logger.debug(f"[canary] gate read failed for {platform!r}: {exc}")
        return False, None
    return False, None


def _make_banner_emit() -> Any:
    store_holder: dict[str, Any] = {}

    def _emit(kind: str, payload: dict[str, Any]) -> None:
        publish_logger.info(
            f"banner-embed: {kind} {payload}",
            extra={"banner_event": kind, **payload},
        )
        if "store" not in store_holder:
            from backlink_publisher.events.store import EventStore
            store_holder["store"] = EventStore()
        try:
            store_holder["store"].append(kind, payload)
        except Exception as exc:
            publish_logger.warning(
                f"banner-event EventStore.append({kind!r}) failed: {exc}"
            )

    return _emit


def _error_class(exc: Exception) -> str:
    from backlink_publisher.publishing.adapters.retry import classify_exception
    return classify_exception(exc).value


def _check_token_drift(
    initial_revs: dict[str, int], *, raises: bool = True
) -> str | None:
    """Detect mid-run credential rotation of an already-bound platform.

    Default (``raises=True``): emit_error(exit 3) on drift — the kill-switch the
    CLI/resume paths rely on (and the unit tests assert). ``raises=False`` is the
    in-process variant for ``publish_rows``: it returns the abort message instead
    of raising SystemExit, so the caller can stop the run via a typed sentinel
    while still honouring the safety property (do NOT publish with rotated
    credentials — the loop aborts the run, it does not continue).
    """
    from backlink_publisher._util.errors import emit_error
    from backlink_publisher.config import snapshot_token_revs

    # Re-scan only the platforms present at run-start: the comparison below
    # only inspects keys in initial_revs, so reading the other (unbound) token
    # files every row was pure waste (10xN opens+parses on the publish path).
    # A credential file CREATED mid-run is intentionally not tracked — it was
    # never in initial_revs; only rotation/revocation of an already-bound
    # platform aborts the run.
    current = snapshot_token_revs(initial_revs.keys())
    for plat, init_rev in initial_revs.items():
        if current.get(plat, 0) != init_rev:
            msg = (
                f"error: configuration for platform {plat!r} was updated mid-run. "
                "Aborting to prevent using revoked credentials."
            )
            if raises:
                emit_error(msg, exit_code=3)
            return msg
    return None


def _do_verify(
    no_verify: bool,
    dry_run: bool,
    result: Any,
    row: dict[str, Any],
) -> tuple[bool, str]:

    if no_verify or dry_run:
        return True, ""
    verify_url = result.published_url or result.draft_url
    if not verify_url:
        return False, "no URL to verify"
    needs_extended_wait = getattr(result, "post_publish_delay_seconds", 0) > 0
    max_wait = 30 if needs_extended_wait else 10
    required_links = [lnk["url"] for lnk in row.get("links", []) if lnk.get("required")]
    vr = verify_published(
        verify_url,
        title=row.get("title", ""),
        required_link_urls=required_links,
        max_wait=max_wait,
    )
    return vr.ok, vr.reason


def _build_failure_row(
    status: str,
    row: dict[str, Any],
    platform: str,
    error: str,
    ts: str,
    *,
    adapter: str = "",
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row.get("id", ""),
        "platform": platform,
        "status": status,
        "title": row.get("title", ""),
        "draft_url": "",
        "published_url": "",
        "created_at": ts,
        "adapter": adapter,
        "error": error,
    }
    out.update(extra)
    return out


def _build_skip_row(
    row: dict[str, Any], platform: str, live_url: str | None, ts: str
) -> dict[str, Any]:
    """A SKIP-DUPLICATE output row (enforce gate, U7): the backlink is already
    live, so it carries the recorded ``live_url`` and ``error=None`` — it counts
    as a present backlink for downstream, distinguished by its status."""
    return {
        "id": row.get("id", ""),
        "platform": platform,
        "status": "skipped_duplicate",
        "title": row.get("title", ""),
        "draft_url": "",
        "published_url": live_url or "",
        "created_at": ts,
        "adapter": platform,
        "error": None,
        "_dedup_verdict": "skip",
    }


def _try_update_ckpt_failed(
    run_id: str | None,
    row_id: str,
    error: str,
    error_class: str,
) -> str | None:
    from .. import checkpoint

    if run_id is None:
        return None
    try:
        checkpoint.update_item(run_id, row_id, "failed", error=error, error_class=error_class)
    except Exception as ckpt_exc:
        print(f"[WARN] checkpoint update failed: {ckpt_exc}", file=sys.stderr)
        return None
    return run_id


def _load_throttle_config() -> tuple[int, int]:
    return (
        int(os.environ.get("MEDIUM_THROTTLE_MIN", "60")),
        int(os.environ.get("MEDIUM_THROTTLE_MAX", "300")),
    )


def _do_sleep(seconds: float) -> None:
    """Sleep for the specified number of seconds. (Mockable for tests)"""
    time.sleep(seconds)


def _sleep_with_throttle(throttle_min: int, throttle_max: int, context: str = "") -> None:
    sleep_secs = random.uniform(throttle_min, throttle_max)
    label = f" ({context})" if context else ""
    publish_logger.info(f"throttle: sleeping {sleep_secs:.0f}s{label}")
    _do_sleep(sleep_secs)


def _record_publish_failure(
    outputs: list[dict[str, Any]],
    row: dict[str, Any],
    platform: str,
    ts: str,
    run_id: str | None,
    exc: Exception,
    err_class: str,
    err_msg: str,
) -> str | None:
    outputs.append(_build_failure_row("failed", row, platform, err_msg, ts, adapter=platform))
    new_run_id = _try_update_ckpt_failed(run_id, row.get("id", ""), err_msg, err_class)
    # Observe-only dedup record (U2): map this failure to failed/uncertain. Never
    # gates publish; a store error is swallowed inside the gate helper.
    from backlink_publisher.cli._dedup_gate import record_failure
    record_failure(row, platform, error_class=err_class, run_id=run_id)
    publish_logger.error(
        f"publish failed: {exc}",
        extra={"id": row.get("id"), "platform": platform},
    )
    return new_run_id


def _record_publish_path(platform: str, result: Any, row: dict[str, Any]) -> int:
    """Record per-platform forward-path drift advisory verdict after publish.

    Reads the target-specific fields from the adapter's ``link_attr_verification``
    result (computed in Unit 1 with no extra fetch) and writes a ``link-alive``
    or ``drift`` verdict to the per-platform ``_publish_path`` stream in
    ``canary-health.json``. Issues a WARN on drift naming the offending link(s).

    Returns 1 if drift was recorded, 0 otherwise (for the epilogue count).
    Skips silently (returns 0) when:
    - verification was skipped/absent (R5: skipped → nothing recorded)
    - no required links in the payload (``target_*`` fields absent)

    Advisory only: never raises, never changes exit code.
    Plan 2026-05-27-006 Unit 3.
    """
    meta = (result._provider_meta or {}) if result._provider_meta is not None else {}
    link_attr = meta.get("link_attr_verification") or {}
    if link_attr.get("verification") != "ok":
        return 0  # skipped or missing — R5: record nothing
    if "target_found" not in link_attr:
        return 0  # no required links in payload — nothing checkable

    is_drift = (
        bool(link_attr.get("target_nofollow"))
        or bool(link_attr.get("target_rewritten"))
        or not bool(link_attr.get("target_found", True))
    )

    try:
        from backlink_publisher.canary.store import (
            record_publish_path_verdict,
            STATUS_DRIFT_CONFIRMED,
            STATUS_LINK_ALIVE,
        )
        verdict = STATUS_DRIFT_CONFIRMED if is_drift else STATUS_LINK_ALIVE
        record_publish_path_verdict(platform, verdict)
    except Exception as _exc:  # noqa: BLE001
        publish_logger.debug(
            f"[publish-path-canary] store write failed for {platform!r}: {_exc}"
        )  # advisory — never fail publish

    if is_drift:
        nofollow_urls = link_attr.get("target_nofollow_urls", [])
        rewritten_urls = link_attr.get("target_rewritten_urls", [])
        missing_urls = link_attr.get("target_missing_urls", [])
        row_id = row.get("id", "")
        publish_logger.warning(
            f"[publish-path-canary] id={row_id} platform={platform} verdict=drift "
            f"nofollow={nofollow_urls} rewritten={rewritten_urls} missing={missing_urls}",
            extra={"id": row_id, "platform": platform},
        )
        return 1
    return 0


def _medium_throttle_sleep(
    row_idx: int,
    last_success_idx: int,
    platform: str,
    throttle_min: int,
    throttle_max: int,
    *,
    dry_run: bool,
) -> None:
    if dry_run or row_idx == 0:
        return
    if last_success_idx != row_idx - 1 or platform != "medium":
        return
    _sleep_with_throttle(throttle_min, throttle_max, "next Medium post")


def _run_reconciler(args: Any) -> dict[str, Any] | None:
    if args.dry_run:
        return None
    if not args.reconcile and not args.reconcile_all:
        return None

    try:
        from ..events.reconciler import reconcile_all

        summary = reconcile_all()

        return {
            "event": "reconciler_summary",
            "auto_fixed": summary.auto_fixed,
            "quarantined": summary.quarantined,
            "cleared": summary.cleared,
            "history_gaps": summary.history_gaps,
            "history_checked": summary.history_checked,
            "total_checkpoints": summary.total_checkpoints,
            "skipped_quarantined": summary.skipped_quarantined,
        }
    except Exception as exc:
        from backlink_publisher._util.logger import publish_logger
        publish_logger.warning(f"reconciler pass failed: {exc}")
        return None


def _write_reconciler_report(summary: dict[str, Any] | None) -> None:
    if summary is None:
        return
    try:
        import json as _json
        print(_json.dumps(summary, sort_keys=True))
    except Exception as exc:
        from backlink_publisher._util.logger import publish_logger
        publish_logger.warning(f"reconciler report write failed: {exc}")


@dataclass
class PublishExitDecision:
    """The pure exit-code verdict for a finished publish run (U4-3).

    Single source of truth shared by the impure CLI epilogue (which dispatches
    stderr + emit_error/emit_envelope_and_exit off ``kind``) and the in-process
    ``PublishOutcome.terminal_exit_code`` — so a CLI and an embedded caller can
    never disagree on what a given output set means. ``successful``/``failed``/
    ``unverified`` are computed once here and reused so the recon counts match
    the verdict exactly.

    ``kind`` selects the impure dispatch; ``exit_code`` is the value it yields:
      - "failed"         -> 4, envelope ExternalServiceError, print failed rows
      - "all_held"       -> 3, emit_error (operator must adjudicate holds)
      - "none_published" -> 5, emit_error
      - "unverified"     -> 5, envelope InternalError, print unverified rows
      - "ok"             -> 0, no exit
    """

    kind: str
    exit_code: int
    message: str | None
    successful: list[dict[str, Any]]
    failed: list[dict[str, Any]]
    unverified: list[dict[str, Any]]


def _decide_publish_exit(
    outputs: list[dict[str, Any]],
    *,
    dry_run: bool,
    dedup_hold_count: int,
) -> PublishExitDecision:
    """Pure exit-code decision for the publish epilogue (U4-3).

    Replicates the epilogue's branch *precedence* exactly (NOT a count): a
    failed output row wins over everything (exit 4); only then does a live run
    with zero successes mean held>0 ? 3 : 5; only then does an unverified
    success mean 5. exit 3 from this path therefore means exactly
    "zero success AND zero failed AND holds>0".
    """
    successful = [r for r in outputs if r.get("error") is None]
    failed = [r for r in outputs if r.get("error") is not None]
    unverified = [s for s in successful if s.get("status", "").endswith("_unverified")]

    if failed:
        return PublishExitDecision(
            "failed", 4, f"{len(failed)} payload(s) failed to publish",
            successful, failed, unverified,
        )
    if not dry_run and not successful:
        if dedup_hold_count > 0:
            return PublishExitDecision(
                "all_held", 3,
                f"all {dedup_hold_count} row(s) held by the dedup gate "
                "(uncertain/in-flight); adjudicate with --list-uncertain / "
                "--adjudicate-uncertain, then re-run",
                successful, failed, unverified,
            )
        return PublishExitDecision(
            "none_published", 5, "no payloads were published",
            successful, failed, unverified,
        )
    if unverified:
        return PublishExitDecision(
            "unverified", 5, f"{len(unverified)} payload(s) failed verification",
            successful, failed, unverified,
        )
    return PublishExitDecision("ok", 0, None, successful, failed, unverified)


def _publish_epilogue(
    outputs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    args: Any,
    run_id: str | None,
    success_count: int,
    fail_count: int,
    skipped_unreachable_count: int,
    skipped_quarantined_count: int = 0,
    publish_path_drift_count: int = 0,
    dedup_skip_count: int = 0,
    dedup_hold_count: int = 0,
    checkpoint_disabled: bool = False,
) -> None:
    # Phase 1: projection.
    if run_id is not None:
        from ..events import project_run_safe as _project_run_safe
        _project_run_safe(run_id)

    # Phase 2: reconciler (always runs, RECON.log always written).
    reconciler_summary = _run_reconciler(args)

    # R18/U7 dedup reconciliation line — counts only, no campaign URLs. Always
    # emitted (zeros in observe) so the signal is uniform; RECON level per
    # [[recon-log-level-for-always-on-signals]].
    dispatched = sum(
        1 for r in outputs if r.get("_dedup_verdict") != "skip"
    )
    publish_logger.recon(
        "dedup_reconciliation",
        skipped_already_published=dedup_skip_count,
        held_uncertain=dedup_hold_count,
        dispatched=dispatched,
        skipped_canary=skipped_quarantined_count,
    )

    decision = _decide_publish_exit(
        outputs, dry_run=args.dry_run, dedup_hold_count=dedup_hold_count
    )
    successful, failed, unverified = (
        decision.successful, decision.failed, decision.unverified,
    )

    recon_extra: dict[str, Any] = {}
    if checkpoint_disabled:
        recon_extra["checkpoint_disabled"] = True
    publish_logger.recon(
        "publish_reconciliation",
        input_payloads=len(rows),
        output_rows=len(successful),
        delta=len(rows) - len(successful),
        dropped={
            "failed": len(failed),
            "unverified": len(unverified),
        },
        dropped_ids={
            "failed": [r.get("id", "") for r in failed],
            "unverified": [r.get("id", "") for r in unverified],
        },
        **recon_extra,
    )

    if successful:
        from backlink_publisher._util.jsonl import write_jsonl
        write_jsonl(successful)

    _write_reconciler_report(reconciler_summary)

    from backlink_publisher._util.errors import emit_envelope_and_exit, emit_error

    # Impure dispatch off the pure verdict. The kinds are mutually exclusive and
    # each emit_* raises SystemExit, so exactly one branch fires (matching the
    # original early-exit if-chain byte-for-byte).
    if decision.kind == "failed":
        for f in failed:
            print(f"publish failed: {f['error']}", file=sys.stderr)
        emit_envelope_and_exit("ExternalServiceError", 4, decision.message or "")
    if decision.kind in ("all_held", "none_published"):
        # all_held: operator-action required (adjudicate the holds), exit 3, not 5.
        emit_error(decision.message or "", exit_code=decision.exit_code)
    if decision.kind == "unverified":
        for u in unverified:
            print(
                f"verification failed: id={u.get('id', '')} status={u.get('status', '')}",
                file=sys.stderr,
            )
        emit_envelope_and_exit("InternalError", 5, decision.message or "")

    publish_logger.info(
        f"publish complete: {success_count} succeeded, {fail_count} failed, "
        f"{skipped_unreachable_count} skipped_unreachable, "
        f"{skipped_quarantined_count} skipped_quarantined, "
        f"{publish_path_drift_count} publish_path_drift",
        extra={
            "success": success_count,
            "failed": fail_count,
            "skipped_unreachable": skipped_unreachable_count,
            "skipped_quarantined": skipped_quarantined_count,
            "publish_path_drift_count": publish_path_drift_count,
        },
    )
