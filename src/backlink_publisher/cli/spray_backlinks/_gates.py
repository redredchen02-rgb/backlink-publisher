"""Cross-seed idempotency, checkpoint helpers, and per-seed file I/O for spray-backlinks.

Extracted from ``core.py`` (Wave 3 split). ``core.py`` retains argparse, input
validation, and the top-level loop call; this module holds all the durable-state
helpers (checkpoint read/write, run-id generation, cross-seed governance closure,
and per-seed output files).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, UTC
import json
import os
from pathlib import Path
from typing import Any

from backlink_publisher._util.io import atomic_write_json
from backlink_publisher._util.logger import get_logger
from backlink_publisher.config import _cache_dir

log = get_logger("spray-backlinks-gates")

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
                log.debug("checkpoint_json_corrupt", file=f.name)
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
