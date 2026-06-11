"""Spray-backlinks execution kernel — seed expansion, gating, and run orchestration.

Contains the pure expansion/gating kernel (``expand_seed``, ``gate_candidates``,
``validate_platform_selection``) plus the main spray-run orchestrator
(``_run_spray``) that ``core.py``'s ``main()`` calls after argument validation.
Output helpers for the dry-run preview are co-located here because they use
types defined in this module.
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backlink_publisher._util.errors import (
    UsageError,
    emit_envelope_and_exit,
)
from backlink_publisher._util.jsonl import read_jsonl, write_jsonl
from backlink_publisher.config import load_config
from backlink_publisher.publishing.registry import registered_platforms
from backlink_publisher.schema import validate_input_payload
from backlink_publisher import config_echo


# ── Dataclasses ────────────────────────────────────────────────────────────


@dataclass
class SprayCandidate:
    """One fan-out shot: a seed clone pinned to a single platform.

    ``gate_reason`` / ``dropped`` are populated by Unit 2's gate; ``row`` is the
    publish-ready payload filled in by Unit 3's draft step.
    """

    platform: str
    seed: dict[str, Any]
    dropped: bool = False
    gate_reason: str | None = None
    # Non-blocking advisory: this platform may already host a link to the same
    # money site (cross-seed footprint risk). v1 does not govern cross-seed
    # footprint; surfaced for the operator (see plan R3 accepted residual risk).
    cross_seed_warning: str | None = None
    row: dict[str, Any] | None = None


# ── Pure kernel ────────────────────────────────────────────────────────────


def expand_seed(seed: dict[str, Any], platforms: list[str]) -> list[SprayCandidate]:
    """Clone the seed once per selected platform, overriding ``platform``.

    Order is preserved so downstream rendering and per-shot seeding (Unit 3)
    are deterministic in platform order.
    """
    candidates: list[SprayCandidate] = []
    for platform in platforms:
        clone = dict(seed)
        clone["platform"] = platform
        candidates.append(SprayCandidate(platform=platform, seed=clone))
    return candidates


def validate_platform_selection(
    platforms: list[str], registered: list[str]
) -> list[str]:
    """Validate the operator's ``--platforms`` selection post-parse.

    Raises :class:`UsageError` (exit-code contract) rather than relying on
    argparse ``choices=`` (which exits 2 and clashes with the documented
    usage-error code). Dedupes while preserving first-seen order.
    """
    if not platforms:
        raise UsageError("no platforms selected (use --platforms a,b,c)")
    registered_set = set(registered)
    unknown = [p for p in platforms if p not in registered_set]
    if unknown:
        raise UsageError(
            "unknown platform(s): "
            + ", ".join(unknown)
            + f"; registered: {', '.join(registered)}"
        )
    seen: set[str] = set()
    deduped: list[str] = []
    for p in platforms:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def _default_degraded(platform: str) -> bool:
    """Soft-gate signal: is the platform under canary quarantine?"""
    from backlink_publisher.canary.store import is_degraded

    return is_degraded(platform)


def _seed_main_domain(seed: dict[str, Any]) -> str:
    return str(seed.get("main_domain", "")).rstrip("/")


def gate_candidates(
    candidates: list[SprayCandidate],
    cell_assignments: dict[str, list[str]],
    cap: int,
    *,
    force: frozenset[str] = frozenset(),
    degraded_fn: Callable[[str], bool] = _default_degraded,
    already_published_fn: Callable[[str, str], bool] | None = None,
) -> None:
    """Apply gating + the hard blast-radius cap, mutating candidates in place.

    Order of operations (matters):
      1. HARD cell gate — drop platforms not in the seed's money-site cell
         (`_cell_gate_drop`); unenrolled sites are unrestricted.
      2. SOFT health gate — drop canary-degraded platforms unless ``--force``d;
         the reason is recorded so the override is auditable.
      3. HARD cap — among survivors (operator selection order preserved), keep
         the first ``cap``; the rest are dropped as over-cap.
       4. Cross-seed governance — drop surviving shots whose platform already
          linked the money site for a previous seed (hard gate).
    """
    from backlink_publisher.cli.plan_backlinks._engine import _cell_gate_drop

    kept = 0
    for cand in candidates:
        main_domain = _seed_main_domain(cand.seed)
        if _cell_gate_drop(main_domain, cand.platform, cell_assignments):
            cand.dropped = True
            cand.gate_reason = "cell: platform not in money-site cell"
            continue
        if cand.platform not in force and degraded_fn(cand.platform):
            cand.dropped = True
            cand.gate_reason = "degraded: canary quarantine (override with --force)"
            continue
        if kept >= cap:
            cand.dropped = True
            cand.gate_reason = f"over-cap: exceeds --cap {cap}"
            continue
        kept += 1
        if already_published_fn is not None and already_published_fn(
            cand.platform, main_domain
        ):
            cand.dropped = True
            cand.gate_reason = (
                "cross-seed: already published by a previous seed"
            )
            continue


# ── Dry-run preview output helpers ─────────────────────────────────────────


def _main_anchor_of(row: dict[str, Any]) -> str:
    for link in row.get("links", []):
        if link.get("kind") == "main_domain":
            return str(link.get("anchor", ""))
    return ""


def _main_domain_of(seed: dict[str, Any]) -> str:
    return str(seed.get("main_domain", "")).rstrip("/")


def _emit_preview(surviving: list[SprayCandidate], report: Any) -> None:
    """Dry-run artifact: one JSONL row per shot + an audit summary."""
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


# ── Run orchestration ──────────────────────────────────────────────────────


def _run_spray(args: Any) -> None:
    """Core spray logic: validate inputs, run per-seed loop, emit output."""
    from ._audit import audit_batch
    from ._dispatch import dispatch_burst
    from ._draft import _default_rewrite_fn, draft_row
    from ._gates import (
        _checkpoint_path,
        _generate_run_id,
        _make_cross_seed_checker,
        _save_checkpoint,
        _write_per_seed_file,
    )

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

    # Pre-validate all seeds upfront (exit-2: schema rejects before LLM work).
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

    # --- Resume / checkpoint setup -------------------------------------------
    cross_seed_used: set[tuple[str, str]] = set()
    seed_indices_to_process: list[int] = list(range(len(rows)))
    checkpoint_seeds: list[dict[str, Any]] = []
    run_id: str

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

    # --- Main loop -----------------------------------------------------------
    cfg = load_config()
    config_echo.emit_banner(cfg, "spray-backlinks")

    output_dir: Path | None = None
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    all_output_rows: list[dict[str, Any]] = []
    total_candidates = 0
    total_surviving = 0
    seed_errors_list: list[str] = []
    force = frozenset(_parse_platforms(args.force))
    rewrite_fn = None
    cross_seed_checker = _make_cross_seed_checker(cross_seed_used)

    for seed_index in seed_indices_to_process:
        seed = rows[seed_index]
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
        total_candidates += len(candidates)
        total_surviving += len(surviving)
        seed_main_domain = _main_domain_of(seed)

        if not surviving:
            print(f"[spray] {seed_label} all platforms gated out — skipped",
                  file=sys.stderr)
            checkpoint_seeds.append({
                "index": seed_index,
                "main_domain": seed_main_domain,
                "status": "skipped",
                "n_shots": 0,
                "cross_seed_pairs": [],
            })
            _save_checkpoint(run_id, args, checkpoint_seeds, cross_seed_used)
            continue

        if rewrite_fn is None:
            rewrite_fn = _default_rewrite_fn(cfg)
        for shot_idx, cand in enumerate(surviving):
            cand.row = draft_row(
                cand.seed, cand.platform, shot_idx, cfg,
                rewrite_fn=rewrite_fn,
                fetch_verify_enabled=not args.no_fetch_verify,
            )

        report = audit_batch([c.row for c in surviving])

        seed_failed = False
        if args.dispatch == "dry-run":
            _emit_preview(surviving, report)
        else:
            if not report.passed:
                print(f"[audit] {seed_label}: {report.fail_reason}", file=sys.stderr)
                seed_errors_list.append(
                    f"{seed_label}: diversity audit failed ({report.fail_reason})"
                )
                print(f"[spray] {seed_label} FAILED (audit)", file=sys.stderr)
                seed_failed = True
            else:
                summary = dispatch_burst(
                    [c.row for c in surviving], cfg, args.mode,
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
                all_output_rows.extend(seed_rows)

                if output_dir and seed_rows:
                    _write_per_seed_file(
                        output_dir, seed_index, seed_main_domain, seed_rows,
                    )

        for c in surviving:
            cross_seed_used.add((seed_main_domain, c.platform))

        seed_status = "failed" if seed_failed else "completed"
        seed_pairs = [(seed_main_domain, c.platform) for c in surviving]
        checkpoint_seeds.append({
            "index": seed_index,
            "main_domain": seed_main_domain,
            "status": seed_status,
            "n_shots": len(surviving),
            "cross_seed_pairs": seed_pairs,
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
            print(f"[spray] waiting {delay}s before next seed", file=sys.stderr)
            time.sleep(delay)

    # --- Post-loop output ----------------------------------------------------
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


def _parse_platforms(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]
