"""Unit tests for GA4 source → channel mapping (Plan 2026-06-15-004 U2)."""
from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher.referral.channel_map import (
    CHANNEL_SOURCE_ALIASES,
    map_source_to_channel,
    UNKNOWN_CHANNEL,
)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("medium.com", "medium"),
        ("m.medium.com", "medium"),
        ("MEDIUM.COM", "medium"),
        ("blogspot.com", "blogger"),
        ("zenn.dev", "zenn"),
        ("notion.site", "notion"),
        ("dev.to", "devto"),
        ("linkedin.com", "linkedin"),
        ("l.linkedin.com", "linkedin"),
        ("user.github.io", "ghpages"),
        ("qiita.com", "qiita"),
        ("hashnode.dev", "hashnode"),
        ("wordpress.com", "wordpresscom"),
    ],
)
def test_known_sources_map_to_channel(source, expected):
    assert map_source_to_channel(source) == expected


@pytest.mark.parametrize("source", [None, "", "   ", "example.com", "google"])
def test_unmatched_source_maps_to_unknown(source):
    assert map_source_to_channel(source) == UNKNOWN_CHANNEL


def test_aliases_cover_registered_platforms():
    """Every registered platform should have a channel_map entry (no silent
    'unknown' attribution for a platform we actually publish to)."""
    from backlink_publisher.publishing import registry
    import backlink_publisher.publishing.adapters  # noqa: F401  populate registry

    missing = set(registry.registered_platforms()) - set(CHANNEL_SOURCE_ALIASES)
    assert not missing, f"registered platforms missing a source alias: {sorted(missing)}"


def test_no_token_is_substring_of_another_channels_token():
    """Substring matching is order-independent only if no channel's token is a
    substring of another channel's token (adversarial collision guard)."""
    all_tokens = [
        (ch, tok) for ch, toks in CHANNEL_SOURCE_ALIASES.items() for tok in toks
    ]
    for ch_a, tok_a in all_tokens:
        for ch_b, tok_b in all_tokens:
            if ch_a != ch_b:
                assert tok_a not in tok_b, (
                    f"token {tok_a!r} ({ch_a}) is a substring of "
                    f"{tok_b!r} ({ch_b}) — ambiguous match"
                )
