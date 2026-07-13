"""CLI shell for plan-backlinks (thin-WebUI Phase 2 Unit 7).

Owns: argparse, ``set_log_level`` (H1), ``config_echo`` banner, stdin/file
parsing, ``content_fetch.reset_stats()`` (H2), ``write_jsonl`` to stdout (H3),
and the preflight / canary nudges.

The generation kernel lives in :mod:`._engine` so both this shell and the
in-process ``PipelineAPI.plan()`` path share identical computation.
"""

from __future__ import annotations

import sys
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

from backlink_publisher._util.errors import emit_envelope_and_exit, emit_error
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher._util.logger import plan_logger
from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.config import load_config
import backlink_publisher.publishing.adapters  # noqa: F401  populate registry before argparse

from ... import config_echo
from ...content import fetch as content_fetch
from ._banners import (  # noqa: F401
    _build_banner_runtime,
    _generate_banner_for_payload,
)
from ._cli_args import _build_parser

# Re-export engine symbols for backward compat (tests + __init__.py import
# _dispatch_row / _cell_gate_drop from here).
from ._engine import (  # noqa: F401
    _cell_gate_drop,
    _dispatch_row,
    _emit_link_count_recon,
    _scheduler_enabled_for,
    plan_rows,
    PlanOutcome,
)

# Re-export sub-module symbols so __init__.py and sibling modules
# (._zh_short, ._work_themed) find them at their old import paths.
from ._links import (  # noqa: F401
    _build_link_density_paragraph,
    _build_links,
    _collect_candidate_urls_for_row,
    _ContentGateRowFailure,
    _ROW_REQUIRED_KINDS,
    _SUPPORTING_POOL,
    _SUPPORTING_URLS_FOR_PREFETCH,
    _TARGET_PADDED_LINK_COUNT,
)
from ._payload import (  # noqa: F401
    _generate_payload,
    _resolve_article_anchors,
    ARTICLE_LENGTH_WORDS,
    dofollow_tier_metadata,
)
from ._templates import (  # noqa: F401
    _domain_label_of,
    _TDK_TITLE_TMPL,
    _TEMPLATES,
)


def _read_input_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Validate input-source flags and read seed rows (bulk CSV/sitemap or JSONL).

    Applies the ``--max-rows`` truncation guard before returning.
    """
    bulk_sources = [args.from_csv, args.from_sitemap]
    if sum(bool(x) for x in bulk_sources) > 1:
        emit_error("--from-csv and --from-sitemap are mutually exclusive", exit_code=2)
    if (args.from_csv or args.from_sitemap) and args.input:
        emit_error("--from-csv / --from-sitemap cannot be combined with --input", exit_code=2)

    plan_logger.info("plan-backlinks started", extra={"mode": "generate"})

    if args.from_csv or args.from_sitemap:
        from ...bulk_input import parse_csv, parse_sitemap, urls_to_seed_rows

        if args.from_csv:
            try:
                urls = parse_csv(args.from_csv)
            except Exception as exc:
                emit_error(f"failed to read CSV: {exc}", exit_code=2)
                return  # type: ignore[unreachable]
        else:
            try:
                urls = parse_sitemap(args.from_sitemap)
            except RuntimeError as exc:
                emit_error(str(exc), exit_code=2)
                return  # type: ignore[unreachable]

        if not urls:
            emit_error("no URLs found in input source", exit_code=2)
            return  # type: ignore[unreachable]

        rows: list[dict[str, Any]] = urls_to_seed_rows(
            urls,
            platform=args.default_platform,
            language=args.default_language,
            url_mode=args.default_url_mode,
            publish_mode=args.default_publish_mode,
        )
        plan_logger.info(f"read {len(rows)} seed rows from bulk input")
    else:
        try:
            rows = list(read_jsonl(args.input))
        except SystemExit as exc:
            raise SystemExit(exc.code)

    if len(rows) > args.max_rows:
        import sys as _sys
        print(
            f"[warn] plan-backlinks: truncated input from {len(rows)} to"
            f" {args.max_rows} rows (--max-rows={args.max_rows})",
            file=_sys.stderr,
        )
        rows = rows[:args.max_rows]

    plan_logger.info(f"read {len(rows)} seed rows")
    return rows


def _snapshot_gsc_baseline(cfg: Any) -> None:
    """Advisory GSC baseline snapshot: record keyword positions before building links.

    Non-overlapping window (-60d to -30d) so a follow-up probe-ranking (recent 30d)
    gives a statistically valid before/after comparison. Silently skipped when GSC
    is not configured or any error occurs — never blocks plan generation.
    """
    try:
        from backlink_publisher.cli.ops.probe_ranking import snapshot_baseline
        gsc_cfg = getattr(cfg, "gsc", None)
        keywords = gsc_cfg.ranking_keywords if gsc_cfg else []
        snapshot_baseline(gsc_cfg, keywords)
    except Exception as exc:
        import logging as _logging
        _logging.getLogger("plan-backlinks").debug(
            "gsc baseline hook skipped: %s", exc, exc_info=True
        )


def main(argv: list[str] | None = None) -> None:
    """Generate backlink article payloads from seed URLs.

    This is the main entry point for the plan-backlinks CLI command.
    It reads seed URLs from various input sources (JSONL, CSV, sitemap),
    generates article plans, and outputs them as JSONL to stdout.

    Args:
        argv: Command-line arguments. If None, uses sys.argv[1:].
    """
    args = _build_parser().parse_args(argv)

    # H1: set_log_level stays in the shell — never inside the engine.
    from backlink_publisher._util.logger import set_log_level
    set_log_level(args.log_level)

    if args.no_fetch_verify:
        plan_logger.recon("fetch_verify_disabled", reason="cli_flag")

    rows = _read_input_rows(args)

    cfg = load_config()
    config_echo.emit_banner(cfg, "plan-backlinks")

    # H2: reset fetch stats here (shell responsibility) so plan_rows sees
    # clean per-run counters; the in-process PipelineAPI.plan() path does NOT
    # reset — accepts cumulative stats (documented acceptable, audit surface 2).
    content_fetch.reset_stats()

    _snapshot_gsc_baseline(cfg)

    from backlink_publisher._util.profiling import profile_if_enabled
    with profile_if_enabled(args):
        outcome = plan_rows(
            rows, cfg,
            work_count=args.work_count,
            fetch_verify_enabled=not args.no_fetch_verify,
        )

    if outcome.errors:
        for err in outcome.errors:
            print(err, file=sys.stderr)
        plan_logger.error(f"generation failed: {len(outcome.errors)} errors")
        emit_envelope_and_exit(
            "InputValidationError", 2, f"generation failed: {len(outcome.errors)} errors"
        )

    plan_logger.info(f"generated {len(outcome.outputs)} payloads")
    # H3: write_jsonl to stdout stays in the shell — engine never touches sys.stdout.
    write_jsonl(outcome.outputs)

    _emit_success_nudges(outcome.outputs)


def _emit_success_nudges(outputs: list[dict[str, Any]]) -> None:
    """Advisory recon nudges emitted after a successful plan run."""
    # Preflight nudge (Plan 2026-05-26-008 R3a): advisory on success path only.
    distinct_targets = {
        canonicalize_url(target.strip())
        for row in outputs
        if isinstance((target := row.get("target_url")), str) and target.strip()
    }
    if distinct_targets:
        plan_logger.recon(
            "preflight_nudge",
            distinct_targets=len(distinct_targets),
            hint="run `preflight-targets` to verify destination pages before publishing",
        )

    # Canary advisory nudge (Plan 2026-05-27-001 Unit 4): surface degraded platforms.
    try:
        from backlink_publisher.canary.store import is_degraded

        planned_platforms = {
            p.strip()
            for row in outputs
            if isinstance((p := row.get("platform")), str) and p.strip()
        }
        degraded = sorted(p for p in planned_platforms if is_degraded(p))
        if degraded:
            plan_logger.recon(
                "canary_advisory_nudge",
                degraded_platforms=",".join(degraded),
                hint="canary 偵測到上述平台契約漂移;發布前請複查 adapter 或重新 seed canary",
            )
    except Exception as exc:
        import logging as _logging
        _logging.getLogger("plan-backlinks").debug(
            "canary nudge skipped: %s", exc, exc_info=True
        )
