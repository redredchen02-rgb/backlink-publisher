"""Debt-registry freshness gate — the structural cure for P0's drift.

Why this exists
---------------
The 2026-06-15 P0 audit found 5 of 8 debt items marked ``open`` were in fact
already resolved by v0.4.0 work. A registry that lies is worse than no registry
— it wastes agent and reviewer attention on already-done work. Closing those
items (P0-1) fixed the symptom; this test is the structural cure that keeps
the registry honest going forward.

Each resolved/mitigated debt item makes a *falsifiable claim* about the
codebase. This gate asserts those claims against the repo's actual state, so
the moment a claim becomes false the test fails — surfacing the drift before
the registry silently rots again. Adding a new resolved/mitigated item means
adding a claim here; that is the price of closing a debt.

This is deliberately NOT a generic git-blame-based freshness check (those are
fragile across CI checkouts, shallow clones, and offline runs). It is a small,
concrete, machine-checkable claim per item — each one tied to a specific file
or CI line that must exist for the debt to truly be resolved.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path
import subprocess
import tomllib

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_FILE = REPO_ROOT / "debt_registry.toml"
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"

REGISTRY = tomllib.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
ITEMS = {it["slug"]: it for it in REGISTRY.get("items", [])}


def _grep(pattern: str, path: Path) -> bool:
    """True if ``pattern`` appears anywhere in ``path`` (simple substring)."""
    try:
        return pattern in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


# ─── no-health-surface → resolved: the /health route must exist ───────────────

def test_claim_no_health_surface_resolved_is_true() -> None:
    """``no-health-surface`` is marked resolved — the /health route must exist.

    If this fails, either the route was removed (registry is now correct to
    re-open the debt — flip its status back to ``open``) or the registry lied.
    """
    assert "no-health-surface" in ITEMS, "debt item 'no-health-surface' was deleted"
    assert ITEMS["no-health-surface"]["status"] == "resolved"
    health_py = REPO_ROOT / "webui_app" / "routes" / "health.py"
    assert health_py.exists(), "webui_app/routes/health.py vanished"
    assert _grep('@bp.route("/health"', health_py) or _grep('route("/health"', health_py), (
        "no-health-surface is 'resolved' but the /health route decorator is "
        "gone from health.py. Re-open the debt or restore the route."
    )


# ─── no-coverage-gate → resolved: CI must enforce the threshold ───────────────

def test_claim_no_coverage_gate_resolved_is_true() -> None:
    """``no-coverage-gate`` is resolved — CI must carry --cov-fail-under=80."""
    assert "no-coverage-gate" in ITEMS
    assert ITEMS["no-coverage-gate"]["status"] == "resolved"
    assert CI_FILE.exists(), "CI workflow file vanished"
    assert "--cov-fail-under=80" in CI_FILE.read_text(encoding="utf-8"), (
        "no-coverage-gate is 'resolved' but CI no longer enforces "
        "--cov-fail-under=80. Re-open the debt or restore the gate."
    )


# ─── largest-test-file-bloat → resolved: the split file must be gone ──────────

def test_claim_largest_test_file_bloat_resolved_is_true() -> None:
    """``largest-test-file-bloat`` is resolved — the 1647-SLOC file is split.

    The original test_webui_route_contract.py was split into 7 per-concern
    files in v0.4.0 U2. If the monolith regrows (e.g. someone re-merges them),
    this fails — re-open the debt.
    """
    assert "largest-test-file-bloat" in ITEMS
    assert ITEMS["largest-test-file-bloat"]["status"] == "resolved"
    monolith = REPO_ROOT / "tests" / "test_webui_route_contract.py"
    assert not monolith.exists(), (
        "largest-test-file-bloat is 'resolved' but tests/test_webui_route_contract.py "
        "exists again. Either the file was re-created (re-open the debt) or the "
        "split was reverted."
    )


# ─── test-tier-coverage-incomplete → mitigated: most tests carry __tier__ ─────

def test_claim_test_tier_coverage_mitigated_is_true() -> None:
    """``test-tier-coverage-incomplete`` is mitigated or resolved — ≥90% of tests carry __tier__."""
    assert "test-tier-coverage-incomplete" in ITEMS
    assert ITEMS["test-tier-coverage-incomplete"]["status"] in ("mitigated", "resolved")
    test_files = list((REPO_ROOT / "tests").glob("test_*.py"))
    assert test_files, "no test_*.py files found — repo state is unexpected"
    with_tier = sum(
        1 for f in test_files if "__tier__" in f.read_text(encoding="utf-8")
    )
    coverage = with_tier / len(test_files)
    assert coverage >= 0.90, (
        f"test-tier-coverage-incomplete is 'mitigated' but only {coverage:.0%} "
        f"({with_tier}/{len(test_files)}) of tests carry __tier__. Either finish "
        f"the migration (→ resolved) or re-open as 'open' if it regressed."
    )


# ─── no-recon-schema → mitigated: the recon module + schema test must exist ───

def test_claim_no_recon_schema_mitigated_is_true() -> None:
    """``no-recon-schema`` is mitigated or resolved — _util/recon.py + schema test exist."""
    assert "no-recon-schema" in ITEMS
    assert ITEMS["no-recon-schema"]["status"] in ("mitigated", "resolved")
    recon_mod = REPO_ROOT / "src" / "backlink_publisher" / "_util" / "recon.py"
    recon_test = REPO_ROOT / "tests" / "test_recon_schema.py"
    assert recon_mod.exists(), (
        "no-recon-schema is 'mitigated' but _util/recon.py vanished. Re-open."
    )
    assert recon_test.exists(), (
        "no-recon-schema is 'mitigated' but tests/test_recon_schema.py vanished. "
        "The schema lock is gone — re-open the debt."
    )
    assert _grep("def emit_recon", recon_mod) and _grep("def parse_recon_line", recon_mod), (
        "no-recon-schema is 'mitigated' but the recon module lost its core API."
    )


# ─── orphan-code-unknown → mitigated: vulture gate must exist ─────────────────

def test_claim_orphan_code_unknown_mitigated_is_true() -> None:
    """``orphan-code-unknown`` is mitigated or resolved — the vulture advisory gate exists."""
    assert "orphan-code-unknown" in ITEMS
    assert ITEMS["orphan-code-unknown"]["status"] in ("mitigated", "resolved")
    vulture_test = REPO_ROOT / "tests" / "test_dead_code_advisory.py"
    assert vulture_test.exists(), (
        "orphan-code-unknown is 'mitigated' but tests/test_dead_code_advisory.py "
        "vanished. Re-open the debt."
    )
    assert _grep("vulture", vulture_test), (
        "orphan-code-unknown is 'mitigated' but the advisory test no longer "
        "references vulture."
    )


# ─── debt-registry-staleness → mitigated: this very file must exist ───────────

def test_claim_debt_registry_staleness_mitigated_is_true() -> None:
    """``debt-registry-staleness`` is mitigated or resolved — this freshness gate must exist.

    The debt is "the registry can re-drift"; the mitigation is automated
    freshness checking. If THIS file is deleted, the mitigation is gone and the
    debt must re-open. Self-referential by design.
    """
    assert "debt-registry-staleness" in ITEMS
    assert ITEMS["debt-registry-staleness"]["status"] in ("mitigated", "resolved")
    assert Path(__file__).exists()  # tautological, but documents intent
    # And the resolved_date field must be enforced (the P0 schema change).
    schema_test = REPO_ROOT / "tests" / "test_debt_registry_format.py"
    assert _grep("resolved_date", schema_test), (
        "debt-registry-staleness is 'mitigated' but the format test no longer "
        "enforces the resolved_date field that records when debts close."
    )


def test_claim_no_stewardship_model_resolved_is_true() -> None:
    """``no-stewardship-model`` is resolved — .github/CODEOWNERS must exist."""
    assert "no-stewardship-model" in ITEMS
    assert ITEMS["no-stewardship-model"]["status"] == "resolved"
    codeowners = REPO_ROOT / ".github" / "CODEOWNERS"
    assert codeowners.exists(), (
        "no-stewardship-model is 'resolved' but .github/CODEOWNERS does not exist. "
        "Re-create it or revert the debt status to 'open'."
    )


# ─── recheck-ledger-liveness-seam → resolved: liveness consults recheck verdict ─

def test_claim_recheck_ledger_liveness_seam_resolved_is_true() -> None:
    """``recheck-ledger-liveness-seam`` is resolved (PR #31) — the ledger
    liveness derivation must consult the latest ``link.rechecked`` verdict so a
    dead recheck overrides a stale ``verified_at``.

    Falsifiable: if the override is reverted, ``_link_liveness`` no longer takes
    a recheck verdict and these markers vanish from aggregate.py — re-open the
    debt rather than letting the undercounting-inverse silently return."""
    assert "recheck-ledger-liveness-seam" in ITEMS
    assert ITEMS["recheck-ledger-liveness-seam"]["status"] == "resolved"
    aggregate = REPO_ROOT / "src" / "backlink_publisher" / "ledger" / "aggregate.py"
    assert aggregate.exists(), "ledger/aggregate.py vanished"
    assert _grep("recheck_verdict", aggregate) and _grep("is_deterministic_dead", aggregate), (
        "recheck-ledger-liveness-seam is 'resolved' but ledger/aggregate.py no "
        "longer threads the recheck verdict into liveness. Re-open the debt or "
        "restore the override (dead link.rechecked must lower the live count)."
    )


# ─── meta: every resolved/mitigated item must have a claim test ───────────────
#
# This is the anti-rot backstop. If someone marks a debt resolved/mitigated
# WITHOUT adding a claim test above, this fails — forcing them to write the
# falsifiable check that keeps the registry honest. Open/accepted items are
# exempt (they make no "this is done" claim).

_CLAIM_TEST_SLUGS: set[str] = {
    "no-health-surface",
    "no-coverage-gate",
    "largest-test-file-bloat",
    "test-tier-coverage-incomplete",
    "no-recon-schema",
    "orphan-code-unknown",
    "debt-registry-staleness",
    "recheck-ledger-liveness-seam",
    "no-stewardship-model",
}


def test_every_resolved_or_mitigated_item_has_a_freshness_claim() -> None:
    """Every debt marked resolved/mitigated must have a claim test in this file.

    Closing a debt without a falsifiable claim is exactly how the 2026-06-15
    drift happened — silent status flips with nothing checking the codebase
    agrees. This test refuses to let that happen again.
    """
    closed = {
        slug
        for slug, it in ITEMS.items()
        if it.get("status") in {"resolved", "mitigated"}
    }
    missing_claims = closed - _CLAIM_TEST_SLUGS
    assert not missing_claims, (
        "These debt items are marked resolved/mitigated but have no freshness "
        "claim test in test_debt_registry_freshness.py:\n  "
        + "\n  ".join(sorted(missing_claims))
        + "\nAdd a test_claim_<slug>_*_is_true() function that asserts the "
        "falsifiable codebase invariant behind the 'done' claim. Closing a "
        "debt requires writing the check that keeps it honest."
    )
