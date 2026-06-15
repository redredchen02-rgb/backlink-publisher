"""Map a GA4 ``sessionSource`` (referrer host) to a backlink channel.

Plan 2026-06-15-004 U2. Pure, dependency-light transform: GA4 normalises a
referrer (e.g. ``m.medium.com`` → ``medium.com``, ``l.facebook.com`` →
``facebook``), so we match a source string against per-channel alias tokens by
case-insensitive substring. An unmatched source maps to :data:`UNKNOWN_CHANNEL`
rather than being dropped — a referral we cannot attribute is still a referral,
and surfacing it as ``unknown`` keeps the count honest.

The alias table is deliberately a code constant, not config: the registered
platform set changes rarely and a missing alias degrades gracefully to
``unknown`` (visible in the scorecard) instead of failing.
"""

from __future__ import annotations

#: Channel for any source that matches no alias. Kept (not dropped) so the
#: scorecard/g3 totals stay truthful and operators can spot attribution gaps.
UNKNOWN_CHANNEL = "unknown"

#: ``channel -> alias tokens``. A source matches a channel if any token is a
#: case-insensitive substring of the (lower-cased) source. The channel key is
#: the registry platform slug (``registry.registered_platforms()``) so scorecard
#: rows line up. Order within the dict is the tie-break: the first channel with a
#: matching token wins. Tokens must not be a substring of another channel's
#: token (guarded by ``tests/test_referral_channel_map.py``) to keep matching
#: order-independent. Best-effort: an unmatched source maps to ``unknown``.
CHANNEL_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "blogger": ("blogspot", "blogger"),
    "devto": ("dev.to", "forem"),
    "ghpages": ("github.io",),
    "gitlabpages": ("gitlab.io",),
    "hackmd": ("hackmd.io", "hackmd"),
    "hashnode": ("hashnode",),
    "hatena": ("hatenablog", "hatena"),
    "linkedin": ("linkedin",),
    "livejournal": ("livejournal",),
    "mastodon": ("mastodon", "mstdn"),
    "mataroa": ("mataroa",),
    "medium": ("medium",),
    "notesio": ("notes.io",),
    "notion": ("notion.so", "notion.site", "notion"),
    "qiita": ("qiita",),
    "rentry": ("rentry",),
    "substack": ("substack",),
    "telegraph": ("telegra.ph", "graph.org"),
    "tumblr": ("tumblr",),
    "txtfyi": ("txt.fyi",),
    "velog": ("velog",),
    "wordpresscom": ("wordpress.com", "wordpress"),
    "writeas": ("write.as", "writeas"),
    "zenn": ("zenn",),
}


def _normalise(source: str) -> str:
    """Lower-case and strip a GA4 source for matching."""
    return source.strip().lower()


def map_source_to_channel(source: str | None) -> str:
    """Return the channel for a GA4 ``sessionSource``.

    An empty/``None`` source or one matching no alias returns
    :data:`UNKNOWN_CHANNEL`.
    """
    if not source:
        return UNKNOWN_CHANNEL
    norm = _normalise(source)
    if not norm:
        return UNKNOWN_CHANNEL
    for channel, tokens in CHANNEL_SOURCE_ALIASES.items():
        if any(token in norm for token in tokens):
            return channel
    return UNKNOWN_CHANNEL
