"""Plan 2026-06-05-003 U6 — deep-link + hash scroll to #pane-llm.

The settings panes are tabbed (JS toggles a single .active pane), and pytest
has no JS runtime, so this is the plan-sanctioned downgrade: assert the anchor
target exists, the Pro CTAs point at it, and settings.js wires the hash so it
activates the LLM pane (taking precedence over the stored pane).
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path


def test_pane_llm_anchor_target_exists():
    html = Path("webui_app/templates/settings.html").read_text(encoding="utf-8")
    assert 'id="pane-llm"' in html


def test_nav_pill_and_nudge_ctas_point_at_pane_llm():
    base = Path("webui_app/templates/base.html").read_text(encoding="utf-8")
    index = Path("webui_app/templates/index.html").read_text(encoding="utf-8")
    assert '/settings#pane-llm' in base   # nav pill CTA
    assert '/settings#pane-llm' in index  # index nudge CTA


def test_settings_js_maps_pane_llm_hash_to_llm_pane():
    js = Path("webui_app/static/js/settings.js").read_text(encoding="utf-8")
    assert "'#pane-llm': 'llm'" in js


def test_settings_js_hash_takes_precedence_over_session_storage():
    """The deep-link hash must win over the last-visited pane so a CTA always
    lands on the Pro pane."""
    js = Path("webui_app/static/js/settings.js").read_text(encoding="utf-8")
    start = js.index("function _initActivePane()")
    body = js[start:start + 800]
    hash_pos = body.index("_hashToPaneKey")
    session_pos = body.index("sessionStorage.getItem")
    assert hash_pos < session_pos, "hash must be read before sessionStorage"
    assert "scrollIntoView" in body
