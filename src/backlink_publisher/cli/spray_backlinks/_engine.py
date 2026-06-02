"""Pure kernel for ``spray-backlinks`` — no I/O, no ``sys.stdout``.

Unit 1 establishes the seed→N-platform *expansion* and the result dataclasses.
Later units layer gating + cap (Unit 2), LLM rewrite + anchor (Unit 3), the
diversity audit (Unit 4), and burst dispatch (Unit 5) onto this skeleton.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backlink_publisher._util.errors import UsageError


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
    row: dict[str, Any] | None = None


@dataclass
class SprayOutcome:
    candidates: list[SprayCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def surviving(self) -> list[SprayCandidate]:
        return [c for c in self.candidates if not c.dropped]


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
