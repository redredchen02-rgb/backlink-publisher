"""``spray-backlinks`` CLI shell — argparse + JSONL I/O + exit-code discipline.

Owns all I/O: reads one or more seeds from stdin/``--input``, fans each out
across the selected platforms, and writes publish-ready rows to stdout or to
per-seed files (``--output-dir``). Multi-seed (U3): seeds are processed
independently; per-seed failure does not abort the run; output rows carry a
``seed_id`` field. Cross-seed governance (U4): within a run, each
(main_domain, platform) pair is only published once; subsequent seeds targeting
the same domain automatically skip that platform. Resume (U5): ``--resume``
skips completed seeds and retries failed ones via checkpoint files. The pure
kernel lives in ``_engine`` and never touches ``sys.stdout``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, cast

from backlink_publisher import config_echo
from backlink_publisher._util.errors import (
    emit_envelope_and_exit,
    handle_error,
    PipelineError,
    UsageError,
)
from backlink_publisher._util.io import atomic_write_json
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher._util.logger import get_logger, set_log_level

_log = get_logger("spray-backlinks")
from backlink_publisher.config import _cache_dir, load_config

# Populate the adapter registry so registered_platforms() is non-empty when
# argparse help / validation runs.
import backlink_publisher.publishing.adapters  # noqa: F401
from backlink_publisher.publishing.registry import registered_platforms
from backlink_publisher.schema import validate_input_payload

from ._audit import audit_batch, AuditReport
from ._dispatch import dispatch_burst
from ._draft import _default_rewrite_fn, draft_row
from ._engine import (
    expand_seed,
    gate_candidates,
    SprayCandidate,
    validate_platform_selection,
)

_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}
_DISPATCH_MODES = {"dry-run", "burst"}
_DEFAULT_CAP = 5
_DEFAULT_MAX_SEEDS = 10
_SPRAY_CHECKPOINT_DIR_NAME = "spray-checkpoints"


def _build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        prog="spray-backlinks",
        description=(
            "Fan one or more seeds out to multiple platforms as publish-ready rows "
            "(operator-invoked drafting verb)."
        ),
    )
    parser.add_argument(
        "--input", "-i",
        type=argparse.FileType("r"),
        default=None,
        help="Input seed JSONL (one or more rows; default: stdin)",
    )
    parser.add_argument(
        "--max-seeds",
        type=int,
        default=_DEFAULT_MAX_SEEDS,
        metavar="N",
        help=f"Max seeds to accept (default: {_DEFAULT_MAX_SEEDS})",
    )
    parser.add_argument(
        "--seed-delay-min",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Min inter-seed delay in seconds (opt-in; default: no delay)",
    )
    parser.add_argument(
        "--seed-delay-max",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Max inter-seed delay in seconds (opt-in; default: no delay)",
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
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Per-seed output directory (one JSONL file per seed; default: stdout)",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RUN_ID",
        help="Resume a previous run by run_id (skips completed seeds, retries failures)",
    )
    parser.add_argument(
        "--list-checkpoints",
        action="store_true",
        default=False,
        help="List recent spray-backlinks checkpoints and exit",
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
    parser.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable cProfile profiling (saved to ~/.cache/backlink-publisher/profiles/)",
    )
    return parser


def _parse_platforms(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _main_anchor_of(row: dict[str, Any]) -> str:
    for link in row.get("links", []):
        if link.get("kind") == "main_domain":
            return str(link.get("anchor", ""))
    return ""


def _main_domain_of(seed: dict[str, Any]) -> str:
    return str(seed.get("main_domain", "")).rstrip("/")


def _domain_slug(main_domain: str) -> str:
    """Strip protocol for a filesystem-safe filename fragment."""
    for prefix in ("https://", "http://"):
        if main_domain.startswith(prefix):
            return main_domain[len(prefix):]
    return main_domain


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
            # Anchors come from the static (provider-neutered) path -> reproducible;
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
    print(
        "[audit] body-distinctness is the gate; link byte-signature is "
        "informational only (same-target shots share links by design). "
        "Spot-check the body_excerpt before publishing.",
        file=sys.stderr,
    )
    if not report.passed:
        print(f"[audit] FAILED: {report.fail_reason}", file=sys.stderr)


def _make_cross_seed_checker(
    used: set[tuple[str, str]],
) -> Callable[[str, str], bool]:
    """Build ``already_published_fn`` closure for ``gate_candidates``."""
    def _check(platform: str, main_domain: str) -> bool:
        return (main_domain, platform) in used
    return _check


def _spray_checkpoint_dir() -> Path:
    return _cache_dir() / _SPRAY_CHECKPOINT_DIR_NAME


def _checkpoint_path(run_id: str) -> Path:
    return _spray_checkpoint_dir() / f"{run_id}.json"


def _generate_run_id() -> str:
    """Same pattern as ``backlink_publisher.checkpoint.generate_run_id``."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + os.urandom(4).hex()


def _list_checkpoints() -> list[tuple[str, int, str]]:
    """List recent spray checkpoints: (run_id, completed, total)."""
    cdir = _spray_checkpoint_dir()
    results: list[tuple[str, int, str]] = []
    if not cdir.exists():
        return results
    for f in sorted(cdir.iterdir(), reverse=True):
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                total = len(data.get("seeds", []))
                done = sum(1 for s in data.get("seeds", []) if s.get("status") == "completed")
                results.append((data.get("run_id", f.stem), done, f"{done}/{total}"))
            except Exception:
                _log.debug("checkpoint_json_corrupt", file=f.name)
    return results


def _save_checkpoint(
    run_id: str,
    args: Any,
    checkpoint_seeds: list[dict[str, Any]],
    cross_seed_used: set[tuple[str, str]],
) -> None:
    """Persist checkpoint after each seed."""
    cdir = _spray_checkpoint_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    cpath = _checkpoint_path(run_id)
    data: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "args": {
            "platforms": args.platforms,
            "cap": args.cap,
            "dispatch": args.dispatch,
            "mode": args.mode,
            "max_seeds": args.max_seeds,
        },
        "seeds": checkpoint_seeds,
        "cross_seed_used": sorted([list(p) for p in cross_seed_used]),
    }
    atomic_write_json(cpath, data)


def _write_per_seed_file(
    output_dir: Path,
    seed_index: int,
    main_domain: str,
    rows: list[dict[str, Any]],
) -> None:
    """Write per-seed JSONL file under ``output_dir``."""
    slug = _domain_slug(main_domain).replace("/", "_")
    fpath = output_dir / f"seed-{seed_index:04d}-{slug}.jsonl"
    with open(fpath, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _handle_list_checkpoints(args: Any) -> bool:
    """Print recent checkpoints and return True if the caller should exit."""
    if not args.list_checkpoints:
        return False
    checkpoints = _list_checkpoints()
    if not checkpoints:
        print("spray-backlinks: no checkpoints found", file=sys.stderr)
    else:
        for run_id, done, summary in checkpoints:
            print(f"{run_id}  {summary} seeds", file=sys.stderr)
    return True


def _validate_args(args: Any) -> None:
    """Post-parse closed-set validation. Raises UsageError on violations."""
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
    if args.max_seeds < 1:
        raise UsageError("spray-backlinks: --max-seeds must be >= 1")
    if args.seed_delay_min is not None and args.seed_delay_min < 1:
        raise UsageError("spray-backlinks: --seed-delay-min must be >= 1")
    if args.seed_delay_max is not None and args.seed_delay_max < 1:
        raise UsageError("spray-backlinks: --seed-delay-max must be >= 1")
    if (
        args.seed_delay_min is not None
        and args.seed_delay_max is not None
        and args.seed_delay_min > args.seed_delay_max
    ):
        raise UsageError(
            "spray-backlinks: --seed-delay-min must be <= --seed-delay-max"
        )


def _setup_resume(
    args: Any, rows: list[dict[str, Any]],
) -> tuple[str, list[int], list[dict[str, Any]], set[tuple[str, str]]]:
    """Parse checkpoint for --resume; return (run_id, indices, checkpoint_seeds, cross_seed_used)."""
    cross_seed_used: set[tuple[str, str]] = set()
    seed_indices_to_process: list[int] = list(range(len(rows)))
    checkpoint_seeds: list[dict[str, Any]] = []

    if args.resume:
        cpath = _checkpoint_path(args.resume)
        if not cpath.exists():
            raise UsageError(
                f"spray-backlinks: checkpoint {args.resume!r} not found "
                f"(looked in {cpath})"
            )
        ckpt: dict[str, Any] = json.loads(cpath.read_text(encoding="utf-8"))
        for s in ckpt.get("seeds", []):
            checkpoint_seeds.append(s)
            if s.get("status") == "completed":
                seed_indices_to_process.remove(s["index"])
                for pair in s.get("cross_seed_pairs", []):
                    cross_seed_used.add((pair[0], pair[1]))
        run_id = args.resume
        total_seeds = len(ckpt.get("seeds", []))
        print(
            f"[spray] resuming {run_id}: {len(seed_indices_to_process)} "
            f"seed(s) remaining ({total_seeds - len(seed_indices_to_process)} completed)",
            file=sys.stderr,
        )
    else:
        run_id = _generate_run_id()

    return run_id, seed_indices_to_process, checkpoint_seeds, cross_seed_used


def _process_seed(
    seed_index: int,
    seed: dict[str, Any],
    rows: list[dict[str, Any]],
    platforms: list[str],
    cfg: Any,
    args: Any,
    rewrite_fn: Any,
    cross_seed_checker: Callable[[str, str], bool],
    force: frozenset[str],
    output_dir: Path | None,
) -> tuple[bool, list[dict[str, Any]] | None, int, str | None, Any, list[tuple[str, str]]]:
    """Process one seed: expand → gate → draft → audit → dispatch.

    Returns (seed_failed, output_rows_or_None, surviving_count, error_msg_or_None, rewrite_fn, cross_seed_pairs).
    """
    seed_label = f"seed#{seed_index}"
    print(f"[spray] processing {seed_label} ({seed_index + 1}/{len(rows)})",
          file=sys.stderr)

    candidates = expand_seed(seed, platforms)
    gate_candidates(
        candidates, cfg.cell_assignments, args.cap,
        force=force, already_published_fn=cross_seed_checker,
    )

    for cand in candidates:
        if cand.dropped:
            print(
                f"[gate] drop {cand.platform}: {cand.gate_reason}",
                file=sys.stderr,
            )

    surviving = [c for c in candidates if not c.dropped]
    seed_main_domain = _main_domain_of(seed)

    if not surviving:
        print(f"[spray] {seed_label} all platforms gated out — skipped",
              file=sys.stderr)
        return False, None, 0, None, rewrite_fn, []

    # Lazy LLM init — only when there are surviving candidates
    if rewrite_fn is None:
        rewrite_fn = _default_rewrite_fn(cfg)

    # Unit 3: per-shot LLM rewrite
    for shot_idx, cand in enumerate(surviving):
        cand.row = draft_row(
            cand.seed, cand.platform, shot_idx, cfg,
            rewrite_fn=rewrite_fn,
            fetch_verify_enabled=not args.no_fetch_verify,
        )

    # Unit 4: link/anchor diversity audit
    report = audit_batch(cast(list[dict[str, Any]], [c.row for c in surviving]))

    if args.dispatch == "dry-run":
        _emit_preview(surviving, report)
        pairs = [(seed_main_domain, c.platform) for c in surviving]
        return False, None, len(surviving), None, rewrite_fn, pairs

    # burst mode
    if not report.passed:
        err_msg = f"{seed_label}: diversity audit failed ({report.fail_reason})"
        print(f"[audit] {seed_label}: {report.fail_reason}",
              file=sys.stderr)
        print(f"[spray] {seed_label} FAILED (audit)", file=sys.stderr)
        return True, None, len(surviving), err_msg, rewrite_fn, []

    # Unit 5: jittered burst dispatch
    summary = dispatch_burst(
        cast(list[dict[str, Any]], [c.row for c in surviving]), cfg, args.mode,
    )
    for plat, err in summary.failed:
        print(f"[burst] {seed_label} FAILED {plat}: {err}",
              file=sys.stderr)
    verb = "published" if args.mode == "publish" else "drafted"
    print(
        f"[burst] {seed_label} mode={args.mode}: {verb} "
        f"{summary.n_succeeded}/{len(surviving)}, "
        f"failed {summary.n_failed}",
        file=sys.stderr,
    )
    for c in surviving:
        if c.row:
            c.row["seed_id"] = seed_index
    seed_rows = [c.row for c in surviving if c.row is not None]

    if output_dir and seed_rows:
        _write_per_seed_file(output_dir, seed_index, seed_main_domain, seed_rows)

    pairs = [(seed_main_domain, c.platform) for c in surviving]
    return False, seed_rows, len(surviving), None, rewrite_fn, pairs


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    try:
        _validate_args(args)
        set_log_level(args.log_level)

        if _handle_list_checkpoints(args):
            return

        from backlink_publisher._util.profiling import profile_if_enabled
        with profile_if_enabled(args):
            platforms = validate_platform_selection(
                _parse_platforms(args.platforms), registered_platforms()
            )

            rows = list(read_jsonl(args.input))
            if len(rows) == 0:
                raise UsageError("spray-backlinks: no seed rows on input")
            if len(rows) > args.max_seeds:
                raise UsageError(
                    f"spray-backlinks: {len(rows)} seed rows exceeds --max-seeds "
                    f"({args.max_seeds})"
                )

            pre_errors = 0
            for seed_index, seed in enumerate(rows):
                errors = validate_input_payload(seed, 1)
                if errors:
                    pre_errors += len(errors)
                    print(f"[seed#{seed_index}] {'; '.join(errors)}", file=sys.stderr)
            if pre_errors:
                emit_envelope_and_exit(
                    "InputValidationError", 2,
                    f"spray-backlinks: {pre_errors} seed validation error(s) across "
                    f"{len(rows)} seed(s)",
                )

            run_id, seed_indices_to_process, checkpoint_seeds, cross_seed_used = (
                _setup_resume(args, rows)
            )

            cfg = load_config()
            config_echo.emit_banner(cfg, "spray-backlinks")

            output_dir: Path | None = None
            if args.output_dir:
                output_dir = Path(args.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

            all_output_rows: list[dict[str, Any]] = []
            total_surviving = 0
            seed_errors_list: list[str] = []
            force = frozenset(_parse_platforms(args.force))
            rewrite_fn = None
            cross_seed_checker = _make_cross_seed_checker(cross_seed_used)

            for seed_index in seed_indices_to_process:
                seed = rows[seed_index]
                seed_main_domain = _main_domain_of(seed)

                seed_failed, seed_rows, n_surviving, seed_error, rewrite_fn, cross_pairs = (
                    _process_seed(
                        seed_index, seed, rows, platforms, cfg, args,
                        rewrite_fn, cross_seed_checker, force, output_dir,
                    )
                )

                total_surviving += n_surviving
                if seed_rows:
                    all_output_rows.extend(seed_rows)
                if seed_error:
                    seed_errors_list.append(seed_error)

                # Track cross-seed usage for subsequent seeds
                for pair in cross_pairs:
                    cross_seed_used.add(pair)

                seed_status = "failed" if seed_failed else (
                    "skipped" if seed_rows is None else "completed"
                )
                checkpoint_seeds.append({
                    "index": seed_index,
                    "main_domain": seed_main_domain,
                    "status": seed_status,
                    "n_shots": len(seed_rows) if seed_rows else 0,
                    "cross_seed_pairs": cross_pairs,
                })
                _save_checkpoint(run_id, args, checkpoint_seeds, cross_seed_used)

                if args.dispatch == "burst":
                    n_done = sum(1 for s in checkpoint_seeds
                                 if s.get("status") in ("completed", "skipped"))
                    print(
                        f"[spray] progress: {n_done}/{len(rows)} seeds processed",
                        file=sys.stderr,
                    )

                last_idx = seed_indices_to_process[-1]
                if (
                    seed_index != last_idx
                    and args.seed_delay_min is not None
                ):
                    delay = random.randint(
                        args.seed_delay_min,
                        args.seed_delay_max or args.seed_delay_min,
                    )
                    print(f"[spray] waiting {delay}s before next seed",
                          file=sys.stderr)
                    time.sleep(delay)

            if args.dispatch == "burst" and not output_dir:
                write_jsonl(all_output_rows)

            verb = "candidate" if args.dispatch == "dry-run" else "burst"
            print(
                f"[spray] {verb} done: {total_surviving} surviving shots "
                f"across {len(rows)} seeds ({len(seed_errors_list)} seed errors)",
                file=sys.stderr,
            )
            for err in seed_errors_list:
                print(f"[spray] seed error: {err}", file=sys.stderr)

            if total_surviving == 0:
                emit_envelope_and_exit(
                    "InputValidationError", 2,
                    "spray-backlinks: all platforms gated out across all seeds — "
                    "nothing to dispatch",
                )
            if seed_errors_list and args.dispatch == "burst":
                emit_envelope_and_exit(
                    "PartialFailure", 2,
                    f"spray-backlinks: {len(seed_errors_list)} of {len(rows)} "
                    f"seeds failed; check stderr for details",
                )
    except PipelineError as exc:
        handle_error(exc)


if __name__ == "__main__":
    main()
