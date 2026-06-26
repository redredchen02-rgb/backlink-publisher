"""Spray-backlinks pure kernel — seed expansion, gating, and platform validation.

The run orchestrator lives in ``core.py::main()``; this module provides only the
stateless, testable kernel that ``main()`` and tests import directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backlink_publisher._util.errors import UsageError

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
