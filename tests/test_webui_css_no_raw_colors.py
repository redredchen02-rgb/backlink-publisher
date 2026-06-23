"""Token-compliance gate for the v0.5.0 CORE-FLOW pages (plan U3 / R3).

Goal: keep the *core user journey* (index, settings, monitor hub) on the
`tokens.css` semantic palette instead of raw Bootstrap colour classes / raw
hex / raw rgba(), so the dark console theme stays internally consistent.

Scope is deliberately an explicit ALLOWLIST. The ~30 fast-follow pages
(health, sites, equity_ledger, keep_alive, pipeline_dashboard, the
_settings_* binding partials, copilot.*) still carry raw classes today and
MUST NOT redden this gate — they get tokenized in a later unit. tokens.css is
the token SOURCE (legitimately holds raw rgba/hex for orbs, *-soft status
colours, alert overrides) and is likewise out of scope, as are global_nav.css
/ components.css which are already token-clean shared layers.

Ceilings follow the existing budget-file idiom (monolith_budget.toml /
complexity_budget.toml): a per-file integer ceiling with a one-line rationale,
raised in the same change that earns it — NOT a `/* token-exempt */` comment
grammar. The residual raw rgba() left under the CSS ceilings are decorative,
varied-alpha layer tints / shadows / gradients that do not map 1:1 onto a
single semantic token; forcing a token per alpha step would invent dozens of
throwaway vars for no consistency gain.
"""
from __future__ import annotations

__tier__ = "unit"

import re
from pathlib import Path

import pytest

CSS_DIR = Path(__file__).resolve().parents[1] / "webui_app" / "static" / "css"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "webui_app" / "templates"

# ── CORE-FLOW allowlist — the only files this gate scans ─────────────────────
# Templates: index + settings + monitor hub (the named core-flow pages). Their
# publish-workbench tab partials (_tab_*) + copilot panel are fast-follow and
# intentionally excluded.
CORE_FLOW_TEMPLATES = ("index.html", "monitor_hub.html")  # settings.html retired U8

# Raw Bootstrap *colour* classes that must be 0 in core templates. Layout/size
# classes (btn-sm, btn-close, btn-outline-*, bg-transparent…) are NOT colour
# classes and are out of scope.
RAW_BTN_BG = re.compile(
    r"\b(?:btn-(?:primary|secondary|success|danger|warning|info)"
    r"|bg-(?:primary|success|danger|warning|info|light|dark|white))\b"
)

# CSS files in scope + their raw-literal ceilings. A raw literal is a `#hex` or
# `rgba()/rgb()` NOT already wrapped as a `var(--…)` reference. Ceilings are set
# to the post-tokenization residual count; each line carries its rationale.
CSS_CEILINGS = {
    # index.css: status-soft tints + surface/border hexes tokenized; residual is
    # decorative varied-alpha layer tints, shadows, gradients, and the light-mode
    # health-summary fallbacks with no 1:1 semantic token.
    "index.css": 70,
    # settings.css retired in U8 (Plan 2026-06-18-002).
    # monitor_hub.css: a single white hover tint, consistent with global_nav.css.
    "monitor_hub.css": 1,
}

RAW_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)")


def _count_raw_literals(css_text: str) -> int:
    """Count #hex / rgba() literals that are NOT inside a var(--…) reference.

    var(--token) references contain no colour literal, so a plain findall over
    the source already excludes them; we only strip /* … */ comments so a hex
    mentioned in prose does not inflate the count.
    """
    no_comments = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    return len(RAW_LITERAL.findall(no_comments))


@pytest.mark.parametrize("name", CORE_FLOW_TEMPLATES)
def test_core_template_has_no_raw_color_class(name):
    """Core-flow templates carry 0 raw Bootstrap colour classes (use tokens)."""
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    hits = RAW_BTN_BG.findall(text)
    assert hits == [], (
        f"{name} carries raw Bootstrap colour classes {hits}; "
        f"use a token-driven class (e.g. btn-app-primary in components.css)."
    )


@pytest.mark.parametrize("name", sorted(CSS_CEILINGS))
def test_core_css_raw_literals_under_ceiling(name):
    """Core-flow CSS raw #hex / rgba() literals stay at-or-under the ceiling."""
    text = (CSS_DIR / name).read_text(encoding="utf-8")
    count = _count_raw_literals(text)
    ceiling = CSS_CEILINGS[name]
    assert count <= ceiling, (
        f"{name} has {count} raw colour literals, ceiling is {ceiling}. "
        f"Tokenize the new ones to tokens.css vars, or — if genuinely "
        f"decorative/ambiguous — raise the ceiling here with a rationale."
    )


def test_allowlist_excludes_fast_follow_pages():
    """Guard: the gate must NOT scan known-dirty fast-follow pages.

    If a future edit accidentally adds one of these to an allowlist, this test
    fails loudly — the whole point of U3 is that fast-follow pages stay dirty
    without reddening CI.
    """
    fast_follow_templates = {
        "health.html",
        "sites.html",
        "equity_ledger.html",
        "keep_alive.html",
        "pipeline_dashboard.html",
    }
    assert fast_follow_templates.isdisjoint(CORE_FLOW_TEMPLATES)
    # CSS source-of-truth + already-clean shared layers stay out of scope.
    for excluded in ("tokens.css", "global_nav.css", "components.css", "copilot.css"):
        assert excluded not in CSS_CEILINGS
