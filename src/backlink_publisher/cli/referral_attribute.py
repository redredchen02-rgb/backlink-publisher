"""referral-attribute — channel-level GA4 referral attribution CLI (Plan 2026-06-15-004).

Contract:
* ``--probe`` is required to hit the GA4 Data API (default = zero-network dry-run).
* On ``--probe`` results are written to the event store (``events.db``) via
  ``referral.observed`` events, one per channel with referral sessions.
* Pure-read attribution: the publish pipeline is never touched, so the dofollow
  backlink is preserved. Reuses the existing ``click_track`` GA4 path.
* stdout = JSONL; stderr = diagnostics + config banner.
* Targets passed as positional args. ``--property`` required when no config default.
* Exit 0 on success; exit 1 on usage errors.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from backlink_publisher._util.errors import emit_error
from backlink_publisher._util.logger import get_logger
from backlink_publisher.click_track.engine import ClickQueryOptions
from backlink_publisher.config import ClickTrackConfig, load_config
from backlink_publisher.events.store import EventStore
from backlink_publisher.referral.engine import attribute_site
from backlink_publisher.referral.store import append_referral_observed

from .. import config_echo

_log = get_logger("referral-attribute")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="referral-attribute",
        description=(
            "Channel-level referral attribution: query GA4 for referral traffic "
            "and aggregate it per backlink channel into referral.observed events. "
            "Without --probe this is a zero-network dry preview. stdout = JSONL."
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
            "referral-attribute: --window-days must be a positive integer",
            exit_code=1,
        )

    if not args.targets:
        print(
            "referral-attribute: no targets specified; provide domain(s) as "
            "positional args",
            file=sys.stderr,
        )
        return

    cfg = load_config()
    config_echo.emit_banner(cfg, "referral-attribute")

    property_id = args.property
    if property_id is None:
        emit_error(
            "referral-attribute: --property is required (no default configured)",
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
            f"referral-attribute: dry-run — {len(args.targets)} target(s)"
            f"  property={property_id}"
            f"  add --probe to query GA4",
            file=sys.stderr,
        )

    store = EventStore(path=Path(args.store_path)) if args.store_path else EventStore()

    for target_site in args.targets:
        result = attribute_site(
            target_site=target_site,
            property_id=property_id,
            config=click_cfg or ClickTrackConfig(),
            opts=opts,
        )

        if opts.dry_run:
            pass  # no store writes in dry-run mode
        elif result.error_reason:
            pass  # error surfaced in JSONL row below; no referral events written
        else:
            for channel in result.channels:
                append_referral_observed(
                    store,
                    target_site=target_site,
                    channel=channel.channel,
                    sessions=channel.sessions,
                    window_start=channel.window_start,
                    window_end=channel.window_end,
                )

        row: dict = {
            "type": "referral_attribution",
            "target_site": target_site,
            "property_id": property_id,
            "error_class": result.error_class,
            "error_reason": result.error_reason,
        }
        if result.channels:
            row["channels"] = [
                {
                    "channel": c.channel,
                    "sessions": c.sessions,
                    "window_start": c.window_start,
                    "window_end": c.window_end,
                }
                for c in result.channels
            ]
        print(json.dumps(row, ensure_ascii=False), flush=True)

    _log.recon(
        "referral_attribute_run",
        targets=len(args.targets),
        property_id=property_id,
        dry_run=not args.probe,
    )


if __name__ == "__main__":
    main()
