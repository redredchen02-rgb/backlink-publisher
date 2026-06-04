"""Canonical platform-name normalization (plan 2026-06-04-001 Unit 3 / R4).

A single physical platform can surface under several adapter strings over its
fallback chain (e.g. ``telegraph`` and ``telegraph-api``; ``blogger`` and
``blogger-api``). Left un-normalized, the equity ledger and channel scorecard
double-count them as separate platforms, inflating the "unverified/dead"
picture an operator reads. This module is the single home for the
adapter-string → bare-platform map (previously private to
``idempotency.backfill``) so both the dedup backfill and the ledger read path
share one grep-tested table instead of two.
"""
from __future__ import annotations

#: Explicit live adapter-string → bare-platform map. A platform's registered
#: fallback chain can emit MORE than one string over its history, so every live
#: string a chain can produce must map. velog/devto register an API adapter as
#: primary (``velog-graphql`` / ``devto``) with the browser dispatcher
#: (``{channel}-browser-attach``) as fallback; mastodon is browser-only. hashnode
#: emits both ``hashnode-gql`` and ``hashnode`` from its one adapter.
#: ``test_every_live_adapter_string_is_mapped`` greps the adapter sources and
#: fails if a new live string appears unmapped. Non-publisher helpers (``llm-*``)
#: and the unregistered ``http-form-post`` are intentionally absent → quarantine.
_ADAPTER_STRING_TO_PLATFORM: dict[str, str] = {
    "blogger-api": "blogger",
    "devto": "devto",
    "ghpages": "ghpages",
    "gitlabpages": "gitlabpages",
    "hackmd": "hackmd",
    "hashnode": "hashnode",
    "hashnode-gql": "hashnode",
    "mataroa": "mataroa",
    "hatena": "hatena",
    "linkedin": "linkedin",
    "livejournal-api": "livejournal",
    "medium-api": "medium",
    "medium-brave": "medium",
    "medium-browser": "medium",
    "notion": "notion",
    "rentry": "rentry",
    "substack": "substack",
    "telegraph-api": "telegraph",
    "telegraph-cdp": "telegraph",
    "tumblr": "tumblr",
    "notesio-form-post": "notesio",
    "txtfyi-form-post": "txtfyi",
    "velog-graphql": "velog",
    "wordpresscom": "wordpresscom",
    "writeas": "writeas",
    # Browser-dispatcher fallback strings (adapter = f"{channel}-browser-attach").
    "velog-browser-attach": "velog",
    "devto-browser-attach": "devto",
    "mastodon-browser-attach": "mastodon",
    # Wave-2 JP channels
    "qiita": "qiita",
    "qiita-api": "qiita",
    "zenn": "zenn",
    "zenn-github": "zenn",
}


def canonical_platform(name: str | None) -> str | None:
    """Collapse an adapter-string platform to its bare canonical name.

    Pass-through for unmapped values and ``None``/empty: a value that is already
    a bare platform name (or an unknown string we must not silently drop) is
    returned unchanged, so this is safe to apply at any read seam.
    """
    if not name:
        return name
    return _ADAPTER_STRING_TO_PLATFORM.get(name, name)
