"""
Durability lint: enforce status vocabulary canon on docs/plans/*.md

Canon: {active, completed, shipped, parked}
Done-family: {completed, shipped}

This test must stay green — it is the guard that keeps the vocab from drifting.
"""
__tier__ = "unit"

import re
import pathlib
import pytest

PLANS_DIR = pathlib.Path(__file__).parent.parent / "docs" / "plans"
CANON = {"active", "completed", "shipped", "parked"}
DONE_FAMILY = {"completed", "shipped"}

STATUS_RE = re.compile(r"^status:\s*(\S+)", re.MULTILINE)


def _iter_plans():
    return sorted(PLANS_DIR.glob("*.md"))


def _parse_status(path: pathlib.Path) -> str | None:
    m = STATUS_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def test_all_plans_have_status():
    missing = [p.name for p in _iter_plans() if _parse_status(p) is None]
    assert missing == [], f"Plans missing status: frontmatter: {missing}"


def test_no_off_canon_status():
    off = {
        p.name: tok
        for p in _iter_plans()
        if (tok := _parse_status(p)) not in CANON
    }
    assert off == {}, (
        "Off-canon status tokens found — normalize to "
        f"{sorted(CANON)}: {off}"
    )


def test_active_count_bounded():
    """Fail loudly if active plans exceed a reasonable ceiling."""
    active = [p.name for p in _iter_plans() if _parse_status(p) == "active"]
    assert len(active) <= 10, (
        f"Too many active plans ({len(active)} > 10). "
        f"Active set: {active}"
    )


def test_parked_plans_have_resume_trigger():
    """Every parked plan must carry a written resume trigger (parked: field or body keyword)."""
    failures = []
    for p in _iter_plans():
        if _parse_status(p) != "parked":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        has_trigger = (
            bool(re.search(r"^parked:", text, re.MULTILINE))
            or "resume" in text.lower()
            or "trigger" in text.lower()
        )
        if not has_trigger:
            failures.append(p.name)
    assert failures == [], (
        f"Parked plans without a resume trigger: {failures}"
    )
