"""Tests for the EN_HINTS regex pre-compilation cache (Lane L4).

``_score_language`` used to recompile ``\\b{hint}\\b`` for each of the ~49
EN_HINTS on every call. The patterns are static, so they are now compiled once
into a module-level dict (``_EN_HINT_PATTERNS``) at import. These tests pin:

  (a) EN/ZH/RU/KO detection verdicts stay byte-identical (golden) — perf-only
      change, no behavior change;
  (b) the compiled-pattern dict is the same object across detect calls (built
      once at module load, not per call);
  (c) empty / degenerate markdown still returns ``"unknown"``.
"""
from __future__ import annotations

__tier__ = "unit"

import re

import pytest

from backlink_publisher.linkcheck import language as language_mod
from backlink_publisher.linkcheck.language import (
    EN_HINTS,
    detect_language_from_markdown,
)


# --- (a) Golden detection verdicts — unchanged by the caching refactor -------


@pytest.mark.parametrize(
    "text, expected",
    [
        # English prose
        (
            "This is a test article about machine learning and we discuss "
            "some details here.",
            "en",
        ),
        # Chinese (zh-CN)
        ("这是一个关于人工智能的文章，我们在这里讨论一些技术细节。", "zh-CN"),
        # Russian
        ("Это статья о машинном обучении, и мы обсуждаем здесь некоторые детали.", "ru"),
        # Korean
        ("안녕하세요 오늘은 한국어 기사를 작성합니다.", "ko"),
    ],
)
def test_detection_verdicts_are_golden(text: str, expected: str) -> None:
    assert detect_language_from_markdown(text) == expected


def test_keyword_fallthrough_en_still_detects_en() -> None:
    """Exercise the word-boundary EN path directly: a short Latin text below
    the codepoint short-circuit's effect where keyword scoring decides. The
    cached patterns must yield the same en verdict as before."""
    # Latin-script prose with multiple real English stopwords.
    text = "The cat is on the mat and it will go out."
    assert detect_language_from_markdown(text) == "en"


def test_zh_body_with_latin_urls_stays_zh() -> None:
    """Regression-shaped: zh body whose only Latin content is URLs / anchors
    must not inflate en-score via the (now cached) word-boundary matcher."""
    text = (
        '在论坛上看到有人推荐 <a href="https://51acgs.com/animate/14529" '
        'target="_blank" rel="noopener">51漫畫</a>，自己跟着看了一阵子。\n\n'
        '<a href="https://51acgs.com/animate" target="_blank" rel="noopener">'
        "51acgs</a> 是日常会扫一眼的页面。"
    )
    assert detect_language_from_markdown(text) == "zh-CN"


# --- (b) Compiled-pattern dict is built once (object identity stable) --------


def test_en_hint_patterns_object_is_stable_across_calls() -> None:
    """The module-level cache must be the SAME object before and after detect
    calls — proof it is not rebuilt per invocation."""
    cache_before = language_mod._EN_HINT_PATTERNS
    detect_language_from_markdown("The quick brown fox jumps over the lazy dog.")
    detect_language_from_markdown("안녕하세요 한국어 기사입니다.")
    cache_after = language_mod._EN_HINT_PATTERNS
    assert cache_before is cache_after


def test_en_hint_patterns_covers_every_en_hint() -> None:
    """Every EN_HINTS entry (lowercased) has a pre-compiled pattern, so the
    hot path never falls back to an ad-hoc compile for the real hint set."""
    cache = language_mod._EN_HINT_PATTERNS
    for hint in EN_HINTS:
        assert hint.lower() in cache


def test_en_hint_patterns_values_are_compiled_word_boundary_regexes() -> None:
    """Each cached value is a compiled regex anchored with word boundaries —
    behaviorally identical to the old inline ``\\b{hint}\\b`` compile."""
    cache = language_mod._EN_HINT_PATTERNS
    for hint, pattern in cache.items():
        assert isinstance(pattern, re.Pattern)
        # Same pattern string the old code produced.
        assert pattern.pattern == rf"\b{re.escape(hint)}\b"


# --- (c) Empty / degenerate input still resolves to unknown ------------------


def test_empty_markdown_is_unknown() -> None:
    assert detect_language_from_markdown("") == "unknown"


def test_pure_punctuation_is_unknown() -> None:
    assert detect_language_from_markdown("```\n    \n  ===\n```") == "unknown"


def test_two_letter_degenerate_input_is_unknown() -> None:
    # Below the codepoint short-circuit minimum-denom guard; no multi-char
    # EN/ZH/RU/KO hint matches → unknown.
    assert detect_language_from_markdown("x y") == "unknown"
