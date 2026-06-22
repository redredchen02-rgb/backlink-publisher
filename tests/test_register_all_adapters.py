"""U3 (plan 2026-06-22-001): explicit, idempotent register_all_adapters() bootstrap.

Locks the contract that registration is now a named, idempotent call while the
import-side-effect path (relied on by the ~50 CLI entrypoints) keeps working.
"""
from __future__ import annotations


__tier__ = "unit"

import backlink_publisher.publishing.adapters as adapters
from backlink_publisher.publishing.registry import registered_platforms

# The 24 built-in adapter slugs registered by register_all_adapters() (the
# register(...) table in publishing/adapters/__init__.py). Catalog-driven entries
# register on top via register_catalog_entries(); these are the always-present core.
_BUILTIN_SLUGS = {
    "blogger", "devto", "ghpages", "gitlabpages", "hackmd", "hashnode", "hatena",
    "linkedin", "livejournal", "mastodon", "mataroa", "medium", "notesio", "notion",
    "qiita", "rentry", "substack", "telegraph", "tumblr", "txtfyi", "velog",
    "wordpresscom", "writeas", "zenn",
}


def test_register_all_adapters_is_public_and_callable():
    """The explicit bootstrap is exported from the adapters package so the facade
    (U6) and any host can import + call it instead of relying on import-as-side-effect."""
    assert callable(adapters.register_all_adapters)


def test_builtin_slugs_registered():
    """All 24 built-in platforms are present after import (the auto-invoke at module
    bottom ran the register table)."""
    plats = set(registered_platforms())
    missing = _BUILTIN_SLUGS - plats
    assert not missing, f"built-in slugs missing from registry: {sorted(missing)}"


def test_register_all_adapters_is_idempotent():
    """A second/third call is a no-op (sentinel: blogger already registered), so the
    facade can call it freely without disturbing the registry or test snapshots."""
    before = list(registered_platforms())
    adapters.register_all_adapters()
    adapters.register_all_adapters()
    assert list(registered_platforms()) == before


def test_bare_import_populates_registry_backward_compat():
    """Importing the adapters package (what the ~50 CLI entrypoints do) still
    populates the registry via the preserved import-side-effect auto-invoke."""
    assert _BUILTIN_SLUGS <= set(registered_platforms())
