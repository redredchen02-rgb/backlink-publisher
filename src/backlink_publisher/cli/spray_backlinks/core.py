"""``spray-backlinks`` CLI shell — argparse + JSONL I/O + exit-code discipline.

Owns the I/O boundary: reads one or more seeds from stdin/``--input``, fans
each out across the selected platforms, and writes publish-ready rows to
stdout or to per-seed files (``--output-dir``). Multi-seed (U3): seeds are
processed independently; per-seed failure does not abort the run; output rows
carry a ``seed_id`` field. Cross-seed governance (U4): within a run, each
(main_domain, platform) pair is only published once; subsequent seeds
targeting the same domain automatically skip that platform. Resume (U5):
``--resume`` skips completed seeds and retries failed ones via checkpoint
files.

Split layout (Wave 3 Unit 1, completed by plan 2026-07-06-003 U6): the pure
kernel lives in ``_engine``, argparse in ``_args``, durable-state helpers in
``_gates``, and the seed loop in ``_run``. This module stays the single test
seam: ``_spray_checkpoint_dir`` / ``_default_rewrite_fn`` / ``dispatch_burst``
are re-exported here and dereferenced late (via closures) so monkeypatching
``core.<name>`` still steers the run.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from backlink_publisher import config_echo
from backlink_publisher._util.errors import (
    emit_envelope_and_exit,
    handle_error,
    PipelineError,
    UsageError,
)
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher._util.logger import set_log_level
from backlink_publisher.config import load_config

# Populate the adapter registry so registered_platforms() is non-empty when
# argparse help / validation runs.
import backlink_publisher.publishing.adapters  # noqa: F401
from backlink_publisher.publishing.registry import registered_platforms
from backlink_publisher.schema import validate_input_payload

from ._args import _build_parser, _parse_platforms, _validate_args
from ._dispatch import dispatch_burst  # test seam — dereferenced late in main()
from ._draft import _default_rewrite_fn  # test seam — dereferenced late in main()
from ._engine import validate_platform_selection
from ._gates import (
    _handle_list_checkpoints,
    _make_cross_seed_checker,
    _setup_resume,
    _spray_checkpoint_dir,  # test seam — dereferenced late in main()
)
from ._run import _run_seed_loop


def _read_seed_rows(args: Any) -> list[dict[str, Any]]:
    """Read seed rows and enforce count + schema pre-validation (exit 2)."""
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
    return rows


def _finish_run(
    args: Any,
    output_dir: Path | None,
    n_seeds: int,
    all_output_rows: list[dict[str, Any]],
    total_surviving: int,
    seed_errors_list: list[str],
) -> None:
    """Post-loop epilogue: JSONL output, run summary, exit-code dispatch."""
    if args.dispatch == "burst" and not output_dir:
        write_jsonl(all_output_rows)

    verb = "candidate" if args.dispatch == "dry-run" else "burst"
    print(
        f"[spray] {verb} done: {total_surviving} surviving shots "
        f"across {n_seeds} seeds ({len(seed_errors_list)} seed errors)",
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
            f"spray-backlinks: {len(seed_errors_list)} of {n_seeds} "
            f"seeds failed; check stderr for details",
        )


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    try:
        _validate_args(args)
        set_log_level(args.log_level)

        cdir = _spray_checkpoint_dir()
        if _handle_list_checkpoints(args, cdir):
            return

        from backlink_publisher._util.profiling import profile_if_enabled
        with profile_if_enabled(args):
            platforms = validate_platform_selection(
                _parse_platforms(args.platforms), registered_platforms()
            )
            rows = _read_seed_rows(args)

            run_id, seed_indices_to_process, checkpoint_seeds, cross_seed_used = (
                _setup_resume(args, rows, cdir)
            )

            cfg = load_config()
            config_echo.emit_banner(cfg, "spray-backlinks")

            output_dir: Path | None = None
            if args.output_dir:
                output_dir = Path(args.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)

            all_output_rows, total_surviving, seed_errors_list = _run_seed_loop(
                args=args,
                rows=rows,
                seed_indices_to_process=seed_indices_to_process,
                checkpoint_seeds=checkpoint_seeds,
                cross_seed_used=cross_seed_used,
                platforms=platforms,
                cfg=cfg,
                run_id=run_id,
                cdir=cdir,
                output_dir=output_dir,
                cross_seed_checker=_make_cross_seed_checker(cross_seed_used),
                # Late-bound closures: resolve the core-module globals at call
                # time so tests can monkeypatch core._default_rewrite_fn /
                # core.dispatch_burst (the documented seams).
                rewrite_factory=lambda: _default_rewrite_fn(cfg),
                dispatch_fn=lambda *a, **kw: dispatch_burst(*a, **kw),
            )

            _finish_run(
                args, output_dir, len(rows),
                all_output_rows, total_surviving, seed_errors_list,
            )
    except PipelineError as exc:
        handle_error(exc)


if __name__ == "__main__":
    main()
