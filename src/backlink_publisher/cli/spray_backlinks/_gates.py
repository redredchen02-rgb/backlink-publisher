"""Cross-seed idempotency, checkpoint helpers, and per-seed file I/O for spray-backlinks.

Extracted from ``core.py`` (Wave 3 split, completed by plan 2026-07-06-003 U6).
``core.py`` retains argparse wiring, input validation, and the top-level loop
call; this module holds all the durable-state helpers (checkpoint read/write,
run-id generation, resume bootstrap, cross-seed governance closure, and
per-seed output files).

The checkpoint directory is threaded in as an explicit ``cdir`` parameter:
``core.py`` resolves it once via its module-global ``_spray_checkpoint_dir``
(the test seam — monkeypatched by the CLI tests) and passes it down, so these
helpers stay free of hidden filesystem state.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import sys
from typing import Any

from backlink_publisher._util.errors import UsageError
from backlink_publisher._util.io import atomic_write_json
from backlink_publisher._util.logger import get_logger
from backlink_publisher.config import _cache_dir

log = get_logger("spray-backlinks")

_SPRAY_CHECKPOINT_DIR_NAME = "spray-checkpoints"


# ── cross-seed governance ──────────────────────────────────────────────────


def _make_cross_seed_checker(
    used: set[tuple[str, str]],
) -> Callable[[str, str], bool]:
    """Build ``already_published_fn`` closure for ``gate_candidates``."""
    def _check(platform: str, main_domain: str) -> bool:
        return (main_domain, platform) in used
    return _check


# ── checkpoint helpers ─────────────────────────────────────────────────────


def _spray_checkpoint_dir() -> Path:
    return _cache_dir() / _SPRAY_CHECKPOINT_DIR_NAME


def _checkpoint_path(cdir: Path, run_id: str) -> Path:
    return cdir / f"{run_id}.json"


def _generate_run_id() -> str:
    """Same pattern as ``backlink_publisher.checkpoint.generate_run_id``."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + os.urandom(4).hex()


def _list_checkpoints(cdir: Path) -> list[tuple[str, int, str]]:
    """List recent spray checkpoints: (run_id, completed, total)."""
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
            except (json.JSONDecodeError, OSError, ValueError):
                # Logged (not silenced) then skipped — one corrupt checkpoint
                # file must not stop the listing of the others.
                log.debug("checkpoint_json_corrupt", file=f.name)
    return results


def _handle_list_checkpoints(args: Any, cdir: Path) -> bool:
    """Print recent checkpoints and return True if the caller should exit."""
    if not args.list_checkpoints:
        return False
    checkpoints = _list_checkpoints(cdir)
    if not checkpoints:
        print("spray-backlinks: no checkpoints found", file=sys.stderr)
    else:
        for run_id, done, summary in checkpoints:
            print(f"{run_id}  {summary} seeds", file=sys.stderr)
    return True


def _save_checkpoint(
    cdir: Path,
    run_id: str,
    args: Any,
    checkpoint_seeds: list[dict[str, Any]],
    cross_seed_used: set[tuple[str, str]],
) -> None:
    """Persist checkpoint after each seed."""
    cdir.mkdir(parents=True, exist_ok=True)
    cpath = _checkpoint_path(cdir, run_id)
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


def _setup_resume(
    args: Any, rows: list[dict[str, Any]], cdir: Path,
) -> tuple[str, list[int], list[dict[str, Any]], set[tuple[str, str]]]:
    """Parse checkpoint for --resume; return (run_id, indices, checkpoint_seeds, cross_seed_used)."""
    cross_seed_used: set[tuple[str, str]] = set()
    seed_indices_to_process: list[int] = list(range(len(rows)))
    checkpoint_seeds: list[dict[str, Any]] = []

    if args.resume:
        cpath = _checkpoint_path(cdir, args.resume)
        if not cpath.exists():
            raise UsageError(
                f"spray-backlinks: checkpoint {args.resume!r} not found "
                f"(looked in {cpath})"
            )
        ckpt: dict[str, Any] = json.loads(cpath.read_text(encoding="utf-8"))
        for s in ckpt.get("seeds", []):
            checkpoint_seeds.append(s)
            if s.get("status") == "completed":
                idx = s["index"]
                if idx not in seed_indices_to_process:
                    raise UsageError(
                        f"spray-backlinks: checkpoint {args.resume!r} marks seed "
                        f"index {idx} completed, but the resumed input has only "
                        f"{len(rows)} row(s) (valid indices 0..{len(rows) - 1}); "
                        f"the input file does not match the checkpoint"
                    )
                seed_indices_to_process.remove(idx)
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


# ── per-seed file output ───────────────────────────────────────────────────


def _domain_slug(main_domain: str) -> str:
    """Strip protocol for a filesystem-safe filename fragment."""
    for prefix in ("https://", "http://"):
        if main_domain.startswith(prefix):
            return main_domain[len(prefix):]
    return main_domain


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
