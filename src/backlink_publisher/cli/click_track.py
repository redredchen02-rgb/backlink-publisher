"""click-track — GA4 click tracking CLI verb (Plan 2026-06-02-001).

Contract:
* ``--probe`` is required to hit the GA4 Data API (default = zero-network dry-run).
* On ``--probe`` results are written to the event store (``events.db``)
  via ``click.observed`` / ``click.query_failed`` events.
* stdout = JSONL; stderr = diagnostics + config banner.
* Targets passed as positional args. ``--property`` required when no config default.
* Exit 0 on success; exit 1 on usage errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backlink_publisher._util.errors import emit_error
from backlink_publisher._util.logger import get_logger
from backlink_publisher.click_track.engine import ClickQueryOptions, handle_site
from typing import cast

from backlink_publisher.click_track.store import _Appendable, append_observed, append_query_failed
from backlink_publisher.config import ClickTrackConfig, load_config
from backlink_publisher.events.store import EventStore

from .. import config_echo

_log = get_logger("click-track")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="click-track",
        description=(
            "GA4 click tracking: query Google Analytics 4 for referral traffic "
            "from backlink sources. Without --probe this is a zero-network dry "
            "preview. stdout = JSONL."
        ),
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="enable GA4 API queries (default: zero-network dry preview)",
    )
    parser.add_argument(
        "--property",
        default=None,
        metavar="PID",
        help="GA4 property ID (required unless configured in config.toml)",
    )
    parser.add_argument(
        "--credential-path",
        default=None,
        metavar="PATH",
        help="path to GA4 service-account JSON key (overrides config.toml)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        metavar="N",
        help="look-back window in days (default: 7)",
    )
    parser.add_argument(
        "--store-path",
        default=None,
        metavar="PATH",
        help="path to events.db (default: ~/.cache/backlink-publisher/events.db)",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help="target site domain(s)",
    )
    args = parser.parse_args(argv)

    if args.window_days <= 0:
        emit_error(
            "click-track: --window-days must be a positive integer",
            exit_code=1,
        )

    if not args.targets:
        print(
            "click-track: no targets specified; provide domain(s) as positional args",
            file=sys.stderr,
        )
        return

    cfg = load_config()
    config_echo.emit_banner(cfg, "click-track")

    property_id = args.property
    if property_id is None:
        emit_error(
            "click-track: --property is required (no default configured)",
            exit_code=1,
        )

    click_cfg: ClickTrackConfig | None = cfg.click_track
    if args.credential_path:
        click_cfg = ClickTrackConfig(credential_path=args.credential_path)

    opts = ClickQueryOptions(
        window_days=args.window_days,
        dry_run=not args.probe,
    )

    if not args.probe:
        print(
            f"click-track: dry-run — {len(args.targets)} target(s)"
            f"  property={property_id}"
            f"  add --probe to query GA4",
            file=sys.stderr,
        )

    store = EventStore(path=Path(args.store_path)) if args.store_path else EventStore()

    for target_site in args.targets:
        result = handle_site(
            target_site=target_site,
            property_id=property_id,
            config=click_cfg or ClickTrackConfig(),
            opts=opts,
        )

        # Persist probe results to the event store.
        _store = cast(_Appendable, store)
        if opts.dry_run:
            pass  # no store writes in dry-run mode
        elif result.error_reason:
            append_query_failed(_store, target_site, error_reason=result.error_reason)
        else:
            for stat in result.stats:
                append_observed(
                    _store,
                    target_site=target_site,
                    sessions=stat.sessions,
                    users=stat.users,
                    pageviews=stat.pageviews,
                    window_start=stat.window_start,
                    window_end=stat.window_end,
                    source_url=stat.source_url,
                )

        # Emit JSONL row to stdout.
        row: dict = {
            "type": "click_query",
            "target_site": target_site,
            "property_id": property_id,
            "error_class": result.error_class,
            "error_reason": result.error_reason,
        }
        if result.stats:
            row["stats"] = [
                {
                    "source_domain": s.source_domain,
                    "sessions": s.sessions,
                    "users": s.users,
                    "pageviews": s.pageviews,
                    "window_start": s.window_start,
                    "window_end": s.window_end,
                }
                for s in result.stats
            ]
        print(json.dumps(row, ensure_ascii=False), flush=True)

    _log.recon(
        "click_track_run",
        targets=len(args.targets),
        property_id=property_id,
        dry_run=not args.probe,
    )


if __name__ == "__main__":
    main()
