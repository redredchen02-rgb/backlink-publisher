"""probe-index — GSC page-signal probe CLI (Plan 2026-06-16-003 Unit 3).

Queries GSC Search Analytics for external-link pages published by this tool
to check whether each page has impressions (proxy for indexation). Results
are written to events.db as ``gsc.page_signal`` events.

Contract:
* ``--dry-run`` is the **default**: prints URL count + config status; no
  network calls; exit 0.
* ``--probe`` hits the GSC Search Analytics API. Requires ``[gsc]`` config
  with ``credential_path`` and ``property_url``; absent → exit 3.
* Rolling 30-day dedup: URLs probed within the last 30 days are skipped;
  they re-enter the queue after 30 days to track indexation changes.
* Batch cap: ≤200 URLs per run (GSC quota guard; override with --max-urls).
* ``flock`` guards overlapping runs.
* stdout = JSONL per-URL signal; stderr = config banner + diagnostics.
* Exit 0 on success; exit 3 on config/dependency missing; exit 6 advisory
  (GSC quota exceeded).
"""

from __future__ import annotations

import fcntl
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backlink_publisher._util.errors import (
    DependencyError,
    ExternalServiceError,
    emit_error,
    handle_error,
)
from backlink_publisher._util.logger import get_logger
from backlink_publisher.config import load_config
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL, PUBLISH_CONFIRMED

from .. import config_echo

_log = get_logger("probe-index")

#: Default URL batch cap per run (GSC quota guard).
DEFAULT_MAX_URLS = 200

#: Rolling dedup window in days.
DEDUP_WINDOW_DAYS = 30


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="probe-index",
        description=(
            "GSC page-signal probe: for each published external-link page that "
            "hasn't been probed in 30 days, query GSC Search Analytics and record "
            "whether it has impressions (proxy for indexation). "
            "Without --probe this is a zero-network dry preview. "
            "Emits gsc.page_signal events to events.db. stdout = JSONL."
        ),
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="enable GSC API probing (default: zero-network dry preview)",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=DEFAULT_MAX_URLS,
        metavar="N",
        help=f"max URLs to probe per run (default: {DEFAULT_MAX_URLS})",
    )
    args = parser.parse_args(argv)

    if args.max_urls <= 0:
        emit_error("probe-index: --max-urls must be a positive integer", exit_code=1)

    cfg = load_config()
    config_echo.emit_banner(cfg, "probe-index")

    # -- flock guard (prevent overlapping runs) ---------------------------------
    lock_path = Path(cfg.config_dir) / "probe-index.lock"
    lock_fh = open(lock_path, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fh.close()
        print("probe-index: another instance is running (flock held)", file=sys.stderr)
        sys.exit(6)

    try:
        _run(args, cfg)
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def _run(args, cfg) -> None:
    store = EventStore()
    candidates = _select_candidates(store, args.max_urls)

    if not candidates:
        _log.recon("probe_index_nothing_to_probe", count=0)
        print("probe-index: no unprobed URLs — nothing to do", file=sys.stderr)
        return

    print(
        f"probe-index: {len(candidates)} URL(s) selected "
        f"(dedup window: {DEDUP_WINDOW_DAYS}d, cap: {args.max_urls})",
        file=sys.stderr,
    )

    if not args.probe:
        for url in candidates:
            print(json.dumps({"type": "dry_run", "page_url": url}), flush=True)
        _log.recon("probe_index_dry_run", count=len(candidates))
        return

    # -- Probe path: require [gsc] config --------------------------------------
    gsc_cfg = cfg.gsc
    if gsc_cfg is None or not gsc_cfg.property_url or not gsc_cfg.credential_path:
        handle_error(
            DependencyError(
                "probe-index: --probe requires [gsc] config with credential_path "
                "and property_url. See config.example.toml."
            )
        )
        return  # handle_error() always exits; return is a defensive guard

    from backlink_publisher.gsc.client import GscClient

    try:
        client = GscClient(gsc_cfg.credential_path, gsc_cfg.property_url)
    except ExternalServiceError as exc:
        handle_error(exc)
        return  # handle_error() always exits; return is a defensive guard

    run_id = str(uuid.uuid4())
    _probe_and_record(client, candidates, store, run_id)


def _select_candidates(store: EventStore, max_urls: int) -> list[str]:
    """Return published page URLs not probed in the last 30 days."""
    sql = """
        SELECT DISTINCT p.target_url
        FROM events p
        WHERE p.kind = ?
          AND p.target_url IS NOT NULL
          AND (
              p.target_url NOT IN (
                  SELECT g.target_url
                  FROM events g
                  WHERE g.kind = ?
                    AND g.target_url IS NOT NULL
                    AND g.ts_utc >= datetime('now', '-30 days')
              )
          )
        ORDER BY p.ts_utc ASC
        LIMIT ?
    """
    rows = store.query(sql, (PUBLISH_CONFIRMED, GSC_PAGE_SIGNAL, max_urls))
    return [row["target_url"] for row in rows]


def _probe_and_record(
    client, urls: list[str], store: EventStore, run_id: str
) -> None:
    """Query GSC for page impressions and write gsc.page_signal events."""
    today = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=30)).isoformat()
    end_date = today.isoformat()
    checked_at = today.isoformat()

    try:
        response = client.search_analytics_query(
            {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": ["page"],
                "rowLimit": 25000,
            }
        )
    except ExternalServiceError as exc:
        _log.recon("probe_index_gsc_error", error=str(exc))
        print(f"probe-index: GSC query failed: {exc}", file=sys.stderr)
        sys.exit(6)

    from backlink_publisher._util.url import canonicalize_url

    # Build set of normalized URLs that appeared in GSC (have impressions).
    # Normalize both sides to avoid trailing-slash / scheme-case mismatches.
    gsc_pages: set[str] = set()
    for row in response.get("rows", []):
        keys = row.get("keys", [])
        if keys:
            gsc_pages.add(canonicalize_url(keys[0]))

    for url in urls:
        has_impressions = canonicalize_url(url) in gsc_pages
        payload = {
            "page_url": url,
            "has_impressions": has_impressions,
            "coverage_state": "appeared_in_gsc" if has_impressions else "not_in_gsc",
            "checked_at": checked_at,
        }
        store.append(
            GSC_PAGE_SIGNAL,
            payload,
            target_url=url,
            run_id=run_id,
        )
        row_out = {"type": "probe_index", "page_url": url, "has_impressions": has_impressions}
        print(json.dumps(row_out, ensure_ascii=False), flush=True)

    appeared = sum(1 for u in urls if u in gsc_pages)
    _log.recon(
        "probe_index_complete",
        total=len(urls),
        appeared_in_gsc=appeared,
        not_in_gsc=len(urls) - appeared,
    )
