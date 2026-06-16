"""Static selector-drift guard for browser-tier recipes (Plan 2026-06-15-001 B3).

Live DOM drift (a site renaming a CSS selector) can only be caught by an attended
run against the real site — that is the ``real_browser_publish_smoke`` marker
tests, run via ``make selector-smoke``. THIS file catches the *other* drift class:
an in-repo refactor that deletes, renames, or empties a load-bearing selector
constant. It runs in CI (no browser) and fails the moment a recipe loses one of
the selectors its publish flow depends on, instead of that surfacing as a silent
publish failure in production.

Each browser recipe (devto, velog, mastodon — Medium uses the separate
Brave/Browser adapters, not the recipe system) must expose, under whatever name,
a selector in each load-bearing category below. Names differ per platform, so the
manifest pins the *required category -> the accepted constant names* per platform.
"""

from __future__ import annotations

__tier__ = "unit"

import re

import pytest

from backlink_publisher.publishing.browser_publish.recipes import (
    _devto_selectors,
    _mastodon_selectors,
    _velog_selectors,
)

# platform -> {category: (accepted constant names...)}. A category passes if AT
# LEAST ONE of its accepted names exists on the module and is non-empty.
_MANIFEST = {
    "velog": {
        "module": _velog_selectors,
        "compose": ("COMPOSE_URL",),
        "body": ("BODY_EDITOR_CONTAINER", "BODY_EDITOR_FOCUSABLE"),
        "title": ("TITLE_INPUT",),
        "publish": ("OPEN_PUBLISH_DIALOG_BUTTON", "CONFIRM_PUBLISH_BUTTON_IN_DIALOG"),
        "published_re": ("POST_PUBLISHED_URL_RE",),
    },
    "devto": {
        "module": _devto_selectors,
        "compose": ("COMPOSE_URL",),
        "body": ("BODY_EDITOR_TEXTAREA",),
        "title": ("TITLE_INPUT",),
        "publish": ("PUBLISH_BUTTON",),
        "published_re": ("POST_PUBLISHED_URL_RE",),
    },
    "mastodon": {
        "module": _mastodon_selectors,
        "compose": ("COMPOSE_PATH",),
        "body": ("COMPOSE_TEXTAREA",),
        "publish": ("PUBLISH_BUTTON",),
        "published_re": ("POST_PUBLISHED_URL_RE",),
    },
}

# Categories every recipe must have (title is optional — mastodon has no title).
_REQUIRED_CATEGORIES = ("compose", "body", "publish", "published_re")


def _first_present(mod, names):
    for name in names:
        if hasattr(mod, name):
            val = getattr(mod, name)
            if val:
                return name, val
    return None, None


@pytest.mark.parametrize("platform", sorted(_MANIFEST))
def test_recipe_exposes_required_selectors(platform):
    spec = _MANIFEST[platform]
    mod = spec["module"]
    for category in _REQUIRED_CATEGORIES:
        name, val = _first_present(mod, spec[category])
        assert name is not None, (
            f"{platform}: selector category {category!r} missing — none of "
            f"{spec[category]} present/non-empty on {mod.__name__}. "
            f"A recipe refactor likely dropped a load-bearing selector."
        )


@pytest.mark.parametrize("platform", sorted(_MANIFEST))
def test_published_url_regex_is_compiled_pattern(platform):
    """The success signal (post-published URL match) must stay a valid regex.

    Stored as a pattern string (compiled at use) or a pre-compiled Pattern; either
    way it must compile, so a malformed/emptied success matcher fails CI rather
    than silently never matching (which would mark every publish as failed).
    """
    spec = _MANIFEST[platform]
    _name, val = _first_present(spec["module"], spec["published_re"])
    assert val is not None
    pattern = val.pattern if isinstance(val, re.Pattern) else val
    assert isinstance(pattern, str) and pattern, (
        f"{platform}: POST_PUBLISHED_URL_RE must be a non-empty regex"
    )
    re.compile(pattern)  # raises re.error on a malformed success matcher


def test_manifest_covers_all_browser_recipes():
    """If a new browser recipe is added, it must be added to this drift guard."""
    import backlink_publisher.publishing.adapters  # noqa: F401 — populate registry
    from backlink_publisher.publishing.browser_publish import RECIPES

    assert set(RECIPES) == set(_MANIFEST), (
        "Browser recipes and the selector-drift manifest diverged: "
        f"recipes={sorted(RECIPES)} manifest={sorted(_MANIFEST)}. "
        "Add the new recipe's required selectors to _MANIFEST."
    )
