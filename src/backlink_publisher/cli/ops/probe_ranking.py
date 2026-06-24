"""probe-ranking — GSC keyword ranking snapshot CLI (Plan 2026-06-16-003 Unit 4).

Queries GSC Search Analytics for keyword positions and records snapshots in
events.db as ``ranking.snapshot`` events.

Contract:
* ``--dry-run`` is the **default**: prints keyword list + config status; no
  network; exit 0.
* ``--probe`` hits GSC. Requires ``[gsc]`` config; absent → exit 3.
* Window: recent 30d (startDate=-30d, endDate=today). Non-overlapping with
  the baseline window (-60d to -30d) used by snapshot_baseline().
* Each keyword → one ``ranking.snapshot`` event per run.
* ``flock`` guards overlapping runs.
* stdout = JSONL per-keyword snapshot; stderr = config banner + diagnostics.
* Exit 0; exit 3 on missing config; exit 6 advisory (GSC error).
"""

from __future__ import annotations

import fcntl
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backlink_publisher._util.errors import (
    DependencyError,
    ExternalServiceError,
    emit_error,
    handle_error,
)
from backlink_publisher._util.logger import get_logger
from backlink_publisher.config import load_config
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import RANKING_SNAPSHOT

from backlink_publisher import config_echo

_log = get_logger("probe-ranking")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="probe-ranking",
        description=(
            "GSC keyword ranking snapshot: for each keyword in config, query GSC "
            "Search Analytics for the recent 30-day position. Emits "
            "ranking.snapshot events to events.db. stdout = JSONL. "
            "Without --probe this is a zero-network dry preview."
        ),
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="enable GSC API probing (default: zero-network dry preview)",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    config_echo.emit_banner(cfg, "probe-ranking")

    gsc_cfg = cfg.gsc

    if gsc_cfg is None or not gsc_cfg.ranking_keywords:
        _log.recon("probe_ranking_no_keywords")
        print("probe-ranking: no keywords configured ([gsc].ranking_keywords)", file=sys.stderr)
        return

    keywords = gsc_cfg.ranking_keywords

    if not args.probe:
        for kw in keywords:
            print(json.dumps({"type": "dry_run", "keyword": kw}), flush=True)
        print(
            f"probe-ranking: dry-run — {len(keywords)} keyword(s); add --probe to run",
            file=sys.stderr,
        )
        _log.recon("probe_ranking_dry_run", count=len(keywords))
        return

    if not gsc_cfg.property_url or not gsc_cfg.credential_path:
        handle_error(
            DependencyError(
                "probe-ranking: --probe requires [gsc] config with "
                "credential_path and property_url. See config.example.toml."
            )
        )

    # -- flock guard -----------------------------------------------------------
    lock_path = Path(cfg.config_dir) / "probe-ranking.lock"
    lock_fh = open(lock_path, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fh.close()
        print("probe-ranking: another instance is running (flock held)", file=sys.stderr)
        sys.exit(6)

    try:
        _probe_and_record(gsc_cfg, keywords)
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def _probe_and_record(gsc_cfg: Any, keywords: list[str]) -> None:
    from backlink_publisher.gsc.client import GscClient

    try:
        client = GscClient(gsc_cfg.credential_path, gsc_cfg.property_url)
    except ExternalServiceError as exc:
        handle_error(exc)
        return  # handle_error() always exits; return is a defensive guard

    store = EventStore()
    run_id = str(uuid.uuid4())

    today = datetime.now(timezone.utc).date()
    end_date = today.isoformat()
    start_date = (today - timedelta(days=30)).isoformat()

    try:
        response = client.search_analytics_query(
            {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": ["query"],
                "rowLimit": 25000,
            }
        )
    except ExternalServiceError as exc:
        _log.recon("probe_ranking_gsc_error", error=str(exc))
        print(f"probe-ranking: GSC query failed: {exc}", file=sys.stderr)
        sys.exit(6)

    # Index GSC rows by query string (lowercased for matching)
    gsc_by_query: dict[str, dict] = {}
    for row in response.get("rows", []):
        keys = row.get("keys", [])
        if keys:
            gsc_by_query[keys[0].lower()] = row

    for keyword in keywords:
        gsc_row = gsc_by_query.get(keyword.lower())
        avg_position = gsc_row["position"] if gsc_row else None
        impressions = int(gsc_row.get("impressions", 0)) if gsc_row else 0
        clicks = int(gsc_row.get("clicks", 0)) if gsc_row else 0

        payload = {
            "keyword": keyword,
            "avg_position": avg_position,
            "impressions": impressions,
            "clicks": clicks,
            "date_range_start": start_date,
            "date_range_end": end_date,
        }
        store.append(
            RANKING_SNAPSHOT,
            payload,
            target_url=gsc_cfg.property_url,
            run_id=run_id,
        )
        row_out = {
            "type": "ranking_snapshot",
            "keyword": keyword,
            "avg_position": avg_position,
            "impressions": impressions,
            "clicks": clicks,
            "date_range_start": start_date,
            "date_range_end": end_date,
        }
        print(json.dumps(row_out, ensure_ascii=False), flush=True)

    _log.recon("probe_ranking_complete", keywords=len(keywords), run_id=run_id)


def snapshot_baseline(gsc_cfg: Any, keywords: list[str] | None = None) -> None:
    """Record a baseline ranking snapshot using the pre-build window (-60d to -30d).

    Called advisory from plan-backlinks/core.py before building links.
    Uses a non-overlapping window: -60d to -30d before today, so comparison
    with a subsequent 30d follow-up snapshot is statistically valid.

    Returns early (no network call) when keywords is empty or GSC is not configured.
    Exceptions from GscClient or the API propagate to the caller — the call site
    in plan-backlinks/core.py wraps this in try/except to keep it advisory.
    """
    if keywords is None:
        keywords = []
    if not keywords or not gsc_cfg or not gsc_cfg.property_url or not gsc_cfg.credential_path:
        return

    from backlink_publisher.gsc.client import GscClient

    client = GscClient(gsc_cfg.credential_path, gsc_cfg.property_url)
    store = EventStore()
    run_id = str(uuid.uuid4())

    today = datetime.now(timezone.utc).date()
    end_date = (today - timedelta(days=30)).isoformat()
    start_date = (today - timedelta(days=60)).isoformat()

    response = client.search_analytics_query(
        {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query"],
            "rowLimit": 25000,
        }
    )

    gsc_by_query: dict[str, dict] = {}
    for row in response.get("rows", []):
        keys = row.get("keys", [])
        if keys:
            gsc_by_query[keys[0].lower()] = row

    for keyword in keywords:
        gsc_row = gsc_by_query.get(keyword.lower())
        payload = {
            "keyword": keyword,
            "avg_position": gsc_row["position"] if gsc_row else None,
            "impressions": int(gsc_row.get("impressions", 0)) if gsc_row else 0,
            "clicks": int(gsc_row.get("clicks", 0)) if gsc_row else 0,
            "date_range_start": start_date,
            "date_range_end": end_date,
        }
        store.append(
            RANKING_SNAPSHOT,
            payload,
            target_url=gsc_cfg.property_url,
            run_id=run_id,
        )

    _log.recon("probe_ranking_baseline_complete", keywords=len(keywords))
