"""R10: geo/click_track/pr_outreach/debt_report are demoted (documented as
peripheral in AGENTS.md) but stay importable + entrypoint-backed.

Zero-breakage baseline: the four packages must still import (the WebUI health
panel + config parser lazy-import them) and keep their console entrypoints so
``test_no_orphan_code.py`` stays green without an allowlist patch.
"""

from __future__ import annotations

__tier__ = "unit"

import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
_AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"

# Entrypoints that transitively keep each peripheral package non-orphan.
_REQUIRED_SCRIPTS = {
    "probe-citations": "backlink_publisher.cli.probe_citations:main",   # imports geo
    "pr-opportunities": "backlink_publisher.cli.pr_opportunities:main",  # imports pr_outreach
    "click-track": "backlink_publisher.cli.click_track:main",
    "debt-report": "backlink_publisher.cli.debt_report:main",
}


def test_peripheral_packages_still_import():
    import backlink_publisher.geo  # noqa: F401
    import backlink_publisher.click_track  # noqa: F401
    import backlink_publisher.pr_outreach  # noqa: F401
    import backlink_publisher.cli.debt_report  # noqa: F401


@pytest.fixture(scope="module")
def scripts() -> dict:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]["scripts"]


@pytest.mark.parametrize("name,target", sorted(_REQUIRED_SCRIPTS.items()))
def test_entrypoints_retained(scripts, name, target):
    # Removing these would orphan the peripheral packages → demote, not delete.
    assert scripts.get(name) == target


def test_agents_md_marks_them_peripheral():
    body = _AGENTS.read_text(encoding="utf-8")
    assert "Peripheral / meta modules" in body
    for pkg in ("geo/", "pr_outreach/", "click_track/", "debt_report"):
        assert pkg in body
    # comment_outreach must NOT be demoted (load-bearing).
    assert "comment_outreach" in body and "load-bearing" in body
