"""Unit 2 — spray-backlinks smart gate + hard blast-radius cap.

Tests the pure gate kernel directly (no config-file plumbing) plus one CLI
integration. The cell gate is HARD, the health gate is SOFT (overridable), the
cap is HARD, and the cross-seed warning is non-blocking.
"""
from __future__ import annotations

__tier__ = "unit"
from backlink_publisher.cli.spray_backlinks._engine import (
    SprayCandidate,
    expand_seed,
    gate_candidates,
)


def _seed(main_domain: str = "https://example.com") -> dict:
    return {
        "target_url": "https://example.com/post",
        "main_domain": main_domain,
        "language": "zh-CN",
        "platform": "x",
        "url_mode": "A",
        "publish_mode": "draft",
    }


def _never_degraded(_platform: str) -> bool:
    return False


def test_cell_gate_drops_platform_not_in_money_site_cell():
    cands = expand_seed(_seed(), ["telegraph", "rentry"])
    cells = {"https://example.com": ["telegraph"]}  # rentry not enrolled
    gate_candidates(cands, cells, cap=10, degraded_fn=_never_degraded)
    by_plat = {c.platform: c for c in cands}
    assert not by_plat["telegraph"].dropped
    assert by_plat["rentry"].dropped
    assert "cell" in by_plat["rentry"].gate_reason


def test_unenrolled_site_is_unrestricted():
    cands = expand_seed(_seed(), ["telegraph", "rentry"])
    gate_candidates(cands, {}, cap=10, degraded_fn=_never_degraded)
    assert all(not c.dropped for c in cands)


def test_hard_cap_trims_extras_in_selection_order():
    cands = expand_seed(_seed(), ["a", "b", "c", "d"])
    gate_candidates(cands, {}, cap=2, degraded_fn=_never_degraded)
    survivors = [c.platform for c in cands if not c.dropped]
    assert survivors == ["a", "b"]
    over = [c for c in cands if c.dropped]
    assert all("over-cap" in c.gate_reason for c in over)


def test_degraded_soft_drop_unless_forced():
    cands = expand_seed(_seed(), ["telegraph", "rentry"])
    degraded = {"telegraph"}
    gate_candidates(
        cands, {}, cap=10, degraded_fn=lambda p: p in degraded
    )
    by_plat = {c.platform: c for c in cands}
    assert by_plat["telegraph"].dropped
    assert "degraded" in by_plat["telegraph"].gate_reason
    assert not by_plat["rentry"].dropped


def test_force_overrides_soft_health_gate():
    cands = expand_seed(_seed(), ["telegraph"])
    gate_candidates(
        cands, {}, cap=10, force=frozenset({"telegraph"}),
        degraded_fn=lambda p: True,
    )
    assert not cands[0].dropped  # forced despite degraded


def test_force_does_not_override_hard_cell_gate():
    cands = expand_seed(_seed(), ["rentry"])
    cells = {"https://example.com": ["telegraph"]}  # rentry excluded
    gate_candidates(
        cands, cells, cap=10, force=frozenset({"rentry"}),
        degraded_fn=_never_degraded,
    )
    assert cands[0].dropped  # cell gate is hard — force can't override


def test_cross_seed_warning_fires_on_already_published():
    cands = expand_seed(_seed(), ["telegraph", "rentry"])
    already = {("telegraph", "https://example.com")}
    gate_candidates(
        cands, {}, cap=10, degraded_fn=_never_degraded,
        already_published_fn=lambda p, d: (p, d) in already,
    )
    by_plat = {c.platform: c for c in cands}
    assert by_plat["telegraph"].dropped
    assert "cross-seed" in by_plat["telegraph"].gate_reason
    assert not by_plat["rentry"].dropped


def test_cap_counts_only_survivors_not_gated_out():
    # b is cell-dropped; cap=2 should still admit a, c (not stop at a).
    cands = expand_seed(_seed(), ["a", "b", "c"])
    cells = {"https://example.com": ["a", "c"]}  # b excluded
    gate_candidates(cands, cells, cap=2, degraded_fn=_never_degraded)
    survivors = [c.platform for c in cands if not c.dropped]
    assert survivors == ["a", "c"]
