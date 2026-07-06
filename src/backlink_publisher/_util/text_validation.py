"""Generic text/string validation utilities — P14 A4 extraction.

Extracted from ``anchor.resolver`` so ``_util`` modules can validate anchor
text without importing from a domain package. Contains the baseline checks
(length, deny-list, unsafe characters) and the ``_passes_filters_with_rule``
combinator. Domain-specific ratio rules (zh-CN CJK ratio, ko Hangul ratio)
remain in ``anchor.resolver`` and are passed in as callbacks.

``anchor.resolver`` re-exports these for backward compat.
"""

from __future__ import annotations

from collections.abc import Callable
import re

# ── Baseline constants ───────────────────────────────────────────────────────

#: Hard limits from brainstorm R25: anchors shorter than 2 chars are not
#: semantically useful; anchors longer than 8 chars wrap badly in sidebar
#: widgets.
_MIN_ANCHOR_LEN: int = 2
_MAX_ANCHOR_LEN: int = 8

#: Chinese anchor text that adds zero SEO value — placeholder phrases the
#: resolver must never emit. A strict deny-list (no substring matching) so
#: legitimate long-tail phrases containing a denied word are not blocked.
FORBIDDEN_ANCHOR_TEXTS: frozenset[str] = frozenset({
    "点击这里",
    "看这里",
    "更多",
    "官网",
    "入口",
    "这个网站",
    "相关页面",
    "了解更多",
})

#: Character classes rejected from any anchor text — a stricter superset of
#: the legacy ``config._UNSAFE_IN_ANCHOR`` regex. Blocks HTML/Markdown
#: breakage, security-relevant inputs (bidi reorder attacks, control chars).
_UNSAFE_ANCHOR_CHARS = re.compile(
    "["
    "\x00-\x1f\x7f"
    "\u200b-\u200f"
    "\u202a-\u202e"
    "\u2066-\u2069"
    "<>\"'`\\[\\]()\\\\"
    "\n\r"
    "]"
)


def _passes_filters_with_rule(
    text: str, ratio_check: Callable[[str], bool] | None
) -> bool:
    """Baseline anchor checks + a pre-resolved ratio rule.

    ``ratio_check`` is an already-resolved rule callable (``None`` skips the
    ratio check). The caller resolves the rule once per batch and passes it
    in, avoiding repeated dict lookups.
    """
    if not isinstance(text, str):
        return False  # type: ignore[unreachable]
    length = len(text)
    if length < _MIN_ANCHOR_LEN or length > _MAX_ANCHOR_LEN:
        return False
    if text in FORBIDDEN_ANCHOR_TEXTS:
        return False
    if _UNSAFE_ANCHOR_CHARS.search(text):
        return False
    if ratio_check is not None and not ratio_check(text):
        return False
    return True
