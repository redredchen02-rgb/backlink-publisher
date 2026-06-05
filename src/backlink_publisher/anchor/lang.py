"""Anchor-text language gate (R4 of plan 2026-05-14-001).

Pure-function helpers that decide whether an anchor text matches a row's
declared language. Uses a codepoint-set heuristic rather than ``detect_language``
because anchor surface forms are typically 2-4 characters — the keyword-list
scorer in :mod:`language_check` scores zero on them and falls into the
"unknown -> allow through" branch, defeating the gate.

Public entry: :func:`check_anchor_language`. Exemption order is:

1. ``link_kind`` not in ``{"main_domain", "target"}`` -> exempt.
   Auxiliary citations (Wiki, MDN, GitHub) legitimately use foreign-language
   names in any host article.
2. ``anchor`` is a member of ``branded_pool`` -> exempt.
   Latin brand names ("Apple", "Notion") in zh-CN articles are intentional.
3. ``row_language`` outside :data:`~backlink_publisher.language_check.SUPPORTED_LANGUAGES`
   -> exempt with no codepoint check (the gate cannot speak for non-enum
   languages; R3 contract).
4. Apply the per-language codepoint rule (see :data:`_LANGUAGE_RULES`).
"""

from __future__ import annotations

from backlink_publisher.anchor.resolver import (
    _CJK_BMP_START,
    _CJK_BMP_END,
    _HANGUL_BMP_START,
    _HANGUL_BMP_END,
)
from backlink_publisher.linkcheck.language import SUPPORTED_LANGUAGES

__all__ = ["check_anchor_language"]


#: Cyrillic block (only defined in lang.py — no other module uses it).
_CYR_START, _CYR_END = 0x0400, 0x04FF

#: Link kinds whose anchor text is subject to R4. Anything else is exempt.
_GATED_KINDS = frozenset({"main_domain", "target"})

#: Latin-only anchor patterns that are allowed for zh-CN targets (C0
#: optimisation 2026-06-05). These are domain-like anchors (bare domains,
#: "click here", "visit site", "official website") that do not carry CJK
#: codepoints but are legitimate anchor text for Chinese backlinks targeting
#: a specific domain (e.g. "51acgs.com", "acgs").
#: Extended via the env var ``BACKLINK_ANCHOR_ALLOWED_LATIN_PATTERNS``
#: (comma-separated, applied as lowercased substring match).
_ALLOWED_LATIN_ANCHOR_PATTERNS: tuple[str, ...] = (
    # Domain patterns — bare domain anchors in zh-CN context
    ".com", ".cn", ".net", ".org", ".io", ".co",
    # Common CTAs used as anchor text across languages
    "click here", "visit", "official website", "learn more",
    "read more", "get started", "sign up", "homepage",
    # Short brand/identifier anchors common in zh-CN backlinks
    "官网", "官方网站", "首页",
)

#: The env var to extend ``_ALLOWED_LATIN_ANCHOR_PATTERNS`` at runtime.
#: Comma-separated, lowercased substring match — e.g.
#: ``BACKLINK_ANCHOR_ALLOWED_LATIN_PATTERNS=acgs,51acgs`` allows "51acgs" as
#: a zh-CN anchor.
_ALLOWED_LATIN_PATTERNS_ENV = "BACKLINK_ANCHOR_ALLOWED_LATIN_PATTERNS"

#: Cached expanded patterns (computed once on first use).
_extended_latin_patterns: tuple[str, ...] | None = None


def _get_allowed_latin_patterns() -> tuple[str, ...]:
    """Return the allowed Latin anchor patterns, including env var extensions.

    Computed at most once; the env var is read on first call so an operator
    can set it before the validate gate runs without restart.
    """
    global _extended_latin_patterns
    if _extended_latin_patterns is not None:
        return _extended_latin_patterns
    import os
    base = list(_ALLOWED_LATIN_ANCHOR_PATTERNS)
    raw = os.environ.get(_ALLOWED_LATIN_PATTERNS_ENV, "")
    if raw.strip():
        for fragment in raw.split(","):
            frag = fragment.strip().lower()
            if frag:
                base.append(frag)
    _extended_latin_patterns = tuple(base)
    return _extended_latin_patterns


def _is_allowed_latin_anchor(anchor: str) -> bool:
    """Return True if the anchor matches an allowed Latin pattern (C0 zh-CN relaxation).

    Substring match is intentionally permissive: "51acgs.com→51acgs" would be
    matched by a pattern "51acgs" or ".com". The env var is the operator's
    escape hatch for domain-specific patterns not covered by the defaults.
    """
    anchor_lower = anchor.lower()
    for pattern in _get_allowed_latin_patterns():
        if pattern in anchor_lower:
            return True
    return False


def _has_cjk(text: str) -> bool:
    return any(_CJK_BMP_START <= ord(c) <= _CJK_BMP_END for c in text)


def _has_cyrillic(text: str) -> bool:
    return any(_CYR_START <= ord(c) <= _CYR_END for c in text)


def _has_latin_letter(text: str) -> bool:
    return any(("A" <= c <= "Z") or ("a" <= c <= "z") for c in text)


def _has_hangul(text: str) -> bool:
    return any(_HANGUL_BMP_START <= ord(c) <= _HANGUL_BMP_END for c in text)


def _check_zh_cn(anchor: str) -> tuple[bool, str | None]:
    if _has_cjk(anchor):
        return True, None
    # C0 (2026-06-05): zh-CN anchor relaxation — allow Latin-only anchors
    # that match known patterns (domain suffixes, common CTAs, brand names).
    # This prevents valid anchors like "51acgs.com" or "acgs" from failing
    # the CJK codepoint check when targeting Chinese sites with Latin-domain
    # anchors. The operator can extend the pattern list via the env var
    # ``BACKLINK_ANCHOR_ALLOWED_LATIN_PATTERNS`` (comma-separated).
    if _is_allowed_latin_anchor(anchor):
        return True, None
    return False, "anchor missing CJK codepoint"


def _check_ru(anchor: str) -> tuple[bool, str | None]:
    if _has_cyrillic(anchor):
        return True, None
    return False, "anchor missing Cyrillic codepoint"


def _check_en(anchor: str) -> tuple[bool, str | None]:
    if not _has_latin_letter(anchor):
        return False, "anchor missing Latin letter"
    if _has_cjk(anchor):
        return False, "en anchor contains CJK codepoint"
    if _has_cyrillic(anchor):
        return False, "en anchor contains Cyrillic codepoint"
    return True, None


def _check_ko(anchor: str) -> tuple[bool, str | None]:
    """Plan 2026-05-18-006 Unit 3 R7 — ko anchor strict-mirror of en.

    Required: at least one Hangul Syllable codepoint. Forbidden: any CJK
    BMP codepoint (rejects mixed-script Hanja ko anchors like ``"金正恩"``),
    any Cyrillic codepoint. Latin letters / digits / punctuation are
    allowed (mixed ko + Latin brand mentions like ``"Apple 한국"`` pass).

    Mixed-script proper nouns (``"金正恩 인터뷰"``, ``"首爾"``) go via the
    branded_pool exemption at the call site (see module docstring step 2);
    Unit 3's rule does not modify the existing exemption order.
    """
    if not _has_hangul(anchor):
        return False, "anchor missing Hangul codepoint"
    if _has_cjk(anchor):
        return False, "ko anchor contains CJK codepoint"
    if _has_cyrillic(anchor):
        return False, "ko anchor contains Cyrillic codepoint"
    return True, None


_LANGUAGE_RULES = {
    "zh-CN": _check_zh_cn,
    "ru": _check_ru,
    "en": _check_en,
    "ko": _check_ko,
}


def check_anchor_language(
    anchor: str,
    row_language: str,
    link_kind: str,
    branded_pool: list[str],
) -> tuple[bool, str | None]:
    """Return ``(ok, reason)`` for the anchor against the row's language.

    ``ok=True`` means the anchor passes (either exempted or matched the
    codepoint rule). ``reason`` is a short tag the caller can use to compose
    a structured ``validation.errors`` entry.
    """
    if link_kind not in _GATED_KINDS:
        return True, None
    if anchor in branded_pool:
        return True, None
    if row_language not in SUPPORTED_LANGUAGES:
        return True, None
    rule = _LANGUAGE_RULES[row_language]
    return rule(anchor)
