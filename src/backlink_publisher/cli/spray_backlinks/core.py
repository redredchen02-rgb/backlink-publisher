"""``spray-backlinks`` CLI shell — argparse + JSONL I/O + exit-code discipline.

Owns all I/O: reads ONE seed from stdin/``--input``, fans it out across the
selected platforms, and writes publish-ready rows to stdout (data only;
diagnostics to stderr; exit 0 on success). The pure kernel lives in
``_engine`` and never touches ``sys.stdout``.

Unit 1 wires the scaffold + seed expansion. Gating/cap (Unit 2), LLM rewrite +
anchor (Unit 3), the diversity audit + ``--dry-run`` preview (Unit 4), and burst
dispatch (Unit 5) layer onto this shell.
"""

from __future__ import annotations

import sys
from typing import Any

# Populate the adapter registry so registered_platforms() is non-empty when
# argparse help / validation runs.
import backlink_publisher.publishing.adapters  # noqa: F401
from backlink_publisher import config_echo
from backlink_publisher._util.errors import (
    PipelineError,
    UsageError,
    emit_envelope_and_exit,
    handle_error,
)
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher._util.logger import set_log_level
from backlink_publisher.config import load_config
from backlink_publisher.publishing.registry import registered_platforms
from backlink_publisher.schema import validate_input_payload

from ._audit import AuditReport, audit_batch
from ._dispatch import dispatch_burst
from ._draft import _default_rewrite_fn, draft_row
from ._engine import (
    SprayCandidate,
    expand_seed,
    gate_candidates,
    validate_platform_selection,
)

_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
_DISPATCH_MODES = {"dry-run", "burst"}
_DEFAULT_CAP = 5


def _build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="spray-backlinks",
        description=(
            "Fan one seed out to multiple platforms as publish-ready rows "
            "(operator-invoked drafting verb; emits a reviewable JSONL artifact)."
        ),
    )
    parser.add_argument(
        "--input", "-i",
        type=argparse.FileType("r"),
        default=None,
        help="Input seed JSONL (one row; default: stdin)",
    )
    parser.add_argument(
        "--platforms",
        default="",
        metavar="A,B,C",
        help="Comma-separated platforms to fan out to (operator selection)",
    )
    parser.add_argument(
        "--cap",
        type=int,
        default=_DEFAULT_CAP,
        metavar="N",
        help=f"Hard max platforms per seed (blast-radius cap; default: {_DEFAULT_CAP})",
    )
    parser.add_argument(
        "--dispatch",
        default="dry-run",
        metavar="MODE",
        help="dry-run (preview only, no side effects) | burst (default: dry-run)",
    )
    parser.add_argument(
        "--mode",
        default="draft",
        metavar="MODE",
        help="Publish mode for burst dispatch: draft | publish (default: draft)",
    )
    parser.add_argument(
        "--force",
        default="",
        metavar="A,B",
        help=(
            "Comma-separated platforms to keep despite a soft health/quality "
            "gate warning (the override reason is recorded). The hard cap and "
            "cell gate are NOT overridable."
        ),
    )
    parser.add_argument(
        "--no-fetch-verify",
        action="store_true",
        default=False,
        help="Skip the plan-time URL content gate (dev/replay/offline targets)",
    )
    parser.add_argument(
        "--log-level",
        default="WARN",
        metavar="LEVEL",
        help="Log verbosity: DEBUG|INFO|WARN|ERROR (default: WARN)",
    )
    return parser


def _parse_platforms(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _main_anchor_of(row: dict[str, Any]) -> str:
    for link in row.get("links", []):
        if link.get("kind") == "main_domain":
            return str(link.get("anchor", ""))
    return ""


def _emit_preview(surviving: list[SprayCandidate], report: AuditReport) -> None:
    """Dry-run artifact: one JSONL row per shot + an audit summary. No side
    effects. The operator spot-checks the LLM body before any publish."""
    for cand in surviving:
        row = cand.row or {}
        body = row.get("content_markdown", "")
        write_jsonl([{
            "kind": "shot",
            "platform": cand.platform,
            "title": row.get("title", ""),
            "main_anchor": _main_anchor_of(row),
            "body_chars": len(body),
            "body_excerpt": body[:200],
            # Anchors come from the static (provider-neutered) path → reproducible;
            # the LLM body is intentionally non-deterministic.
            "anchor_reproducible": True,
            "cross_seed_warning": cand.cross_seed_warning,
        }])
    write_jsonl([{
        "kind": "audit_summary",
        "n": report.n,
        "body_max_similarity": round(report.body_max_similarity, 4),
        "distinct_main_anchors": report.distinct_main_anchors,
        "link_concentration_informational": report.link_concentration,
        "passed": report.passed,
        "fail_reason": report.fail_reason,
    }])
    # Caveat on stderr: the gate measures body distinctness; the footprint
    # link byte-signature is informational (degenerate for same-target fan-out).
    print(
        "[audit] body-distinctness is the gate; link byte-signature is "
        "informational only (same-target shots share links by design). "
        "Spot-check the body_excerpt before publishing.",
        file=sys.stderr,
    )
    if not report.passed:
        print(f"[audit] FAILED: {report.fail_reason}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    try:
        # Closed-set validation post-parse (repo convention: UsageError exit 1,
        # not argparse choices= exit 2). See [[argparse-choices-vs-usage-error]].
        if args.log_level not in _LOG_LEVELS:
            raise UsageError(
                f"spray-backlinks: --log-level must be one of {sorted(_LOG_LEVELS)}; "
                f"got {args.log_level!r}"
            )
        if args.dispatch not in _DISPATCH_MODES:
            raise UsageError(
                f"spray-backlinks: --dispatch must be one of {sorted(_DISPATCH_MODES)}; "
                f"got {args.dispatch!r}"
            )
        if args.mode not in {"draft", "publish"}:
            raise UsageError(
                f"spray-backlinks: --mode must be draft|publish; got {args.mode!r}"
            )
        if args.cap < 1:
            raise UsageError("spray-backlinks: --cap must be >= 1")
        set_log_level(args.log_level)

        platforms = validate_platform_selection(
            _parse_platforms(args.platforms), registered_platforms()
        )

        rows = list(read_jsonl(args.input))
        # v1 is single-seed scope: exactly one seed row per invocation.
        if len(rows) != 1:
            raise UsageError(
                f"spray-backlinks: expected exactly 1 seed row, got {len(rows)} "
                "(v1 is single-seed; run once per seed)"
            )
        seed = rows[0]
        seed_errors = validate_input_payload(seed, 1)
        if seed_errors:
            for err in seed_errors:
                print(err, file=sys.stderr)
            emit_envelope_and_exit(
                "InputValidationError", 2,
                f"seed validation failed: {len(seed_errors)} errors",
            )

        cfg = load_config()
        config_echo.emit_banner(cfg, "spray-backlinks")

        candidates = expand_seed(seed, platforms)
        force = frozenset(_parse_platforms(args.force))
        gate_candidates(candidates, cfg.cell_assignments, args.cap, force=force)

        # Gate diagnostics to stderr (data stays on stdout).
        for cand in candidates:
            if cand.dropped:
                print(
                    f"[gate] drop {cand.platform}: {cand.gate_reason}",
                    file=sys.stderr,
                )
            elif cand.cross_seed_warning:
                print(
                    f"[warn] {cand.platform}: {cand.cross_seed_warning}",
                    file=sys.stderr,
                )

        surviving = [c for c in candidates if not c.dropped]
        if not surviving:
            emit_envelope_and_exit(
                "InputValidationError", 2,
                "spray-backlinks: all platforms gated out — nothing to draft",
            )

        # Unit 3: per-shot LLM rewrite. _default_rewrite_fn raises (exit 3) when
        # no LLM is configured — the R4a hard abort, no identical-content fallback.
        rewrite_fn = _default_rewrite_fn(cfg)
        for shot_idx, cand in enumerate(surviving):
            cand.row = draft_row(
                cand.seed, cand.platform, shot_idx, cfg,
                rewrite_fn=rewrite_fn,
                fetch_verify_enabled=not args.no_fetch_verify,
            )

        # Unit 4: link/anchor diversity audit + body-similarity readout.
        report = audit_batch([c.row for c in surviving])

        if args.dispatch == "dry-run":
            _emit_preview(surviving, report)
            return  # dry-run: zero side effects

        # burst: the body-distinctness gate is hard — abort before dispatch.
        if not report.passed:
            print(f"[audit] {report.fail_reason}", file=sys.stderr)
            emit_envelope_and_exit(
                "InputValidationError", 2,
                f"spray-backlinks: diversity audit failed ({report.fail_reason})",
            )

        # Unit 5: jittered burst dispatch (continue-on-failure incl. AuthExpired).
        summary = dispatch_burst([c.row for c in surviving], cfg, args.mode)
        for plat, err in summary.failed:
            print(f"[burst] FAILED {plat}: {err}", file=sys.stderr)
        print(
            f"[burst] published {summary.n_published}/{len(surviving)}, "
            f"failed {summary.n_failed}",
            file=sys.stderr,
        )
        # Rows still emitted to stdout as the reviewable artifact.
        write_jsonl(c.row for c in surviving)
    except PipelineError as exc:
        handle_error(exc)


if __name__ == "__main__":
    main()
