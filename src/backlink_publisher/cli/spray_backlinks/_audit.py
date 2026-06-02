"""Unit 4 — link/anchor diversity audit + body-similarity readout.

Execution note (discovery): spray's same-target fan-out intentionally shares
the SAME backlinks (and, with the provider neutered, the same static anchors)
across every shot — only the LLM prose differs. So footprint's link
byte-signature axis is *degenerate* here (≈100% concentration by construction)
and is reported **informational only**, never gated.

The meaningful v1 signal — and the one that measures the feature's actual goal —
is **body distinctness**: a lightweight max-pairwise shingle-Jaccard across the
shot bodies. The batch is gated on it (a near-identical batch means the LLM
rewrite failed). The full SimHash analyzer remains a follow-on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Near-identical bodies = the LLM rewrite did not produce distinct content.
# Permissive on purpose: only catch genuine failure, not borderline overlap.
_BODY_SIMILARITY_FAIL = 0.90
_SHINGLE_K = 4

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _shingles(text: str, k: int = _SHINGLE_K) -> set[tuple[str, ...]]:
    tokens = _WORD_RE.findall(text.lower())
    if len(tokens) < k:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def max_pairwise_similarity(bodies: list[str]) -> float:
    """Highest shingle-Jaccard between any two bodies (0.0 if < 2 bodies)."""
    if len(bodies) < 2:
        return 0.0
    shingle_sets = [_shingles(b) for b in bodies]
    worst = 0.0
    for i in range(len(shingle_sets)):
        for j in range(i + 1, len(shingle_sets)):
            worst = max(worst, _jaccard(shingle_sets[i], shingle_sets[j]))
    return worst


def _link_concentration(rows: list[dict[str, Any]]) -> float | None:
    """Informational only: footprint byte-signature top-axis concentration over
    rendered HTML. Returns None if footprint sees no links. NOT a gate."""
    try:
        from backlink_publisher._util.markdown import render_to_html
        from backlink_publisher.footprint import analyze_corpus

        html = [render_to_html(r.get("content_markdown", "")) for r in rows]
        report = analyze_corpus(html)
        if report.total_links == 0:
            return None
        top = max(
            (max(c.values()) for c in (
                report.attr_order_counts,
                report.rel_value_counts,
                report.target_value_counts,
                report.preceding_char_counts,
            ) if c),
            default=0,
        )
        return top / report.total_links if report.total_links else None
    except Exception:
        return None  # informational; never break the run


def _main_anchor(row: dict[str, Any]) -> str:
    for link in row.get("links", []):
        if link.get("kind") == "main_domain":
            return str(link.get("anchor", ""))
    return ""


@dataclass
class AuditReport:
    n: int
    body_max_similarity: float
    distinct_main_anchors: int
    link_concentration: float | None
    passed: bool
    fail_reason: str | None = None


def audit_batch(rows: list[dict[str, Any]]) -> AuditReport:
    bodies = [r.get("content_markdown", "") for r in rows]
    sim = max_pairwise_similarity(bodies)
    distinct_anchors = len({_main_anchor(r) for r in rows})
    concentration = _link_concentration(rows)

    passed = sim < _BODY_SIMILARITY_FAIL
    reason = None
    if not passed:
        reason = (
            f"bodies too similar: max pairwise shingle-Jaccard {sim:.2f} "
            f">= {_BODY_SIMILARITY_FAIL:.2f} — the LLM rewrite did not produce "
            f"distinct content (re-seed or re-run)"
        )
    return AuditReport(
        n=len(rows),
        body_max_similarity=sim,
        distinct_main_anchors=distinct_anchors,
        link_concentration=concentration,
        passed=passed,
        fail_reason=reason,
    )
