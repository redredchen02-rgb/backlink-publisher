"""Per-seed run orchestration for ``spray-backlinks``.

Extracted from ``core.py`` (plan 2026-07-06-003 U6, completing the Wave 3
Unit 1 split). Holds the seed loop: expand → gate → draft → audit → dispatch,
plus checkpointing and the opt-in inter-seed delay.

The LLM rewrite factory and the burst dispatcher are injected as callables
(``rewrite_factory`` / ``dispatch_fn``) rather than imported here, so
``core.py`` remains the single test seam (the CLI tests monkeypatch
``core._default_rewrite_fn`` and ``core.dispatch_burst``) and this module has
no shared mutable state with the shell.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import random
import sys
import time
from typing import Any, cast

from backlink_publisher._util.jsonl import write_jsonl

from ._args import _parse_platforms
from ._audit import audit_batch, AuditReport
from ._draft import draft_row
from ._engine import (
    _seed_main_domain as _main_domain_of,
)
from ._engine import (
    expand_seed,
    gate_candidates,
    SprayCandidate,
)
from ._gates import _save_checkpoint, _write_per_seed_file


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


def _run_burst(
    seed_label: str,
    seed_index: int,
    seed_main_domain: str,
    surviving: list[SprayCandidate],
    report: AuditReport,
    cfg: Any,
    args: Any,
    dispatch_fn: Callable[..., Any],
    output_dir: Path | None,
) -> tuple[bool, list[dict[str, Any]] | None, str | None, list[tuple[str, str]]]:
    """Burst-mode tail of one seed: audit gate → jittered dispatch → per-seed file.

    Returns (seed_failed, output_rows_or_None, error_msg_or_None, cross_seed_pairs).
    """
    if not report.passed:
        err_msg = f"{seed_label}: diversity audit failed ({report.fail_reason})"
        print(f"[audit] {seed_label}: {report.fail_reason}",
              file=sys.stderr)
        print(f"[spray] {seed_label} FAILED (audit)", file=sys.stderr)
        return True, None, err_msg, []

    # Unit 5: jittered burst dispatch
    summary = dispatch_fn(
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

    # Audit finding [04]: dispatch failures must reach the run's exit code.
    # n_succeeded==0 (nothing landed) is a whole-seed failure; any failed shot
    # is a PartialFailure. Returning err_msg populates seed_errors_list so
    # _finish_run's exit-2 branch fires — a burst whose publishes failed must
    # NOT exit 0 with success-looking output.
    seed_failed = summary.n_succeeded == 0 and summary.n_failed > 0
    dispatch_err: str | None = None
    if summary.n_failed > 0:
        failed_plats = ", ".join(plat for plat, _ in summary.failed)
        dispatch_err = (
            f"{seed_label}: {summary.n_failed}/{len(surviving)} shots failed to "
            f"{verb} ({failed_plats})"
        )
    return seed_failed, seed_rows, dispatch_err, pairs


def _process_seed(
    seed_index: int,
    seed: dict[str, Any],
    n_seeds: int,
    platforms: list[str],
    cfg: Any,
    args: Any,
    rewrite_fn: Any,
    rewrite_factory: Callable[[], Any],
    dispatch_fn: Callable[..., Any],
    cross_seed_checker: Callable[[str, str], bool],
    force: frozenset[str],
    output_dir: Path | None,
) -> tuple[bool, list[dict[str, Any]] | None, int, str | None, Any, list[tuple[str, str]]]:
    """Process one seed: expand → gate → draft → audit → dispatch.

    Returns (seed_failed, output_rows_or_None, surviving_count, error_msg_or_None, rewrite_fn, cross_seed_pairs).
    """
    seed_label = f"seed#{seed_index}"
    print(f"[spray] processing {seed_label} ({seed_index + 1}/{n_seeds})",
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
        rewrite_fn = rewrite_factory()

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

    seed_failed, seed_rows, err_msg, pairs = _run_burst(
        seed_label, seed_index, seed_main_domain, surviving, report,
        cfg, args, dispatch_fn, output_dir,
    )
    return seed_failed, seed_rows, len(surviving), err_msg, rewrite_fn, pairs


def _run_seed_loop(
    args: Any,
    rows: list[dict[str, Any]],
    seed_indices_to_process: list[int],
    checkpoint_seeds: list[dict[str, Any]],
    cross_seed_used: set[tuple[str, str]],
    platforms: list[str],
    cfg: Any,
    run_id: str,
    cdir: Path,
    output_dir: Path | None,
    cross_seed_checker: Callable[[str, str], bool],
    rewrite_factory: Callable[[], Any],
    dispatch_fn: Callable[..., Any],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Run every pending seed with checkpointing and opt-in inter-seed delay.

    Returns (all_output_rows, total_surviving, seed_errors_list).
    """
    all_output_rows: list[dict[str, Any]] = []
    total_surviving = 0
    seed_errors_list: list[str] = []
    force = frozenset(_parse_platforms(args.force))
    rewrite_fn = None

    for seed_index in seed_indices_to_process:
        seed = rows[seed_index]
        seed_main_domain = _main_domain_of(seed)

        seed_failed, seed_rows, n_surviving, seed_error, rewrite_fn, cross_pairs = (
            _process_seed(
                seed_index, seed, len(rows), platforms, cfg, args,
                rewrite_fn, rewrite_factory, dispatch_fn,
                cross_seed_checker, force, output_dir,
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
        _save_checkpoint(cdir, run_id, args, checkpoint_seeds, cross_seed_used)

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

    return all_output_rows, total_surviving, seed_errors_list
