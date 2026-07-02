"""Corpus calibration regression guard for the Korean codepoint short-circuit.

Plan reference: ``docs/plans/2026-06-30-001-opt-phase3-post-v050-iteration-plan.md``
Sprint D3 — ``ko-corpus-calibration`` (``debt_registry.toml``).

Background: ``_RATIO_THRESHOLD`` (0.30) gates the Hangul-ratio short-circuit
in :mod:`backlink_publisher.linkcheck.language`. It shipped as an uncalibrated
v1 default — never validated against real Korean text — with a specific
feared failure mode: a Hanja-heavy Korean article (lots of Sino-Korean
glosses in parentheses) could have a Hangul ratio low enough to fall through
the short-circuit into the weaker KO_HINTS keyword-scoring backstop.

This test loads a corpus of genuine, naturally-occurring Korean text
(``tests/fixtures/ko_corpus/positive/`` — see ``MANIFEST.md`` there for
provenance: Korean Wikipedia articles spanning encyclopedia/historical/
legal/technical/pop-culture topics, real news articles, and real blog
posts, several deliberately Hanja-dense) plus a small negative-control set
of non-Korean text (``tests/fixtures/ko_corpus/negative/`` — English,
Japanese, Chinese, Russian) and asserts:

  1. detect_language_from_markdown() identifies >=95% of the positive
     corpus as ``"ko"``.
  2. detect_language_from_markdown() never returns ``"ko"`` for any of the
     negative-control (non-Korean) samples.

Calibration finding (2026-07-02, N=31 positive / 7 negative): the current
0.30 threshold already achieves 100% detection with zero false positives.
The most Hanja-dense real sample collected (a Yi Sun-sin biography excerpt
full of Sino-Korean military-rank glosses in parentheses) still has a
Hangul ratio of ~0.92 — nowhere near the 0.30 boundary. Real Korean web
prose (news/blog/encyclopedia) apparently always carries enough Hangul
grammar (particles, verb endings) to keep the ratio well clear of the
threshold, even when the *vocabulary* is heavily Sino-Korean. No threshold
change was made; this test exists as the calibration record + a permanent
regression guard the plan's action item required.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

import pytest

from backlink_publisher.linkcheck.language import detect_language_from_markdown

_CORPUS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ko_corpus"
_POSITIVE_DIR = _CORPUS_DIR / "positive"
_NEGATIVE_DIR = _CORPUS_DIR / "negative"

#: Plan 2026-06-30-001 Sprint D3 verification bar.
_MIN_DETECTION_RATE = 0.95

_positive_files = sorted(_POSITIVE_DIR.glob("*.txt"))
_negative_files = sorted(_NEGATIVE_DIR.glob("*.txt"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- Corpus sanity (fail loudly if fixtures go missing, not silently pass) --


def test_positive_corpus_has_practical_floor_of_samples() -> None:
    """Plan floor: at least 20 real Korean samples (aimed for ~50, documented
    shortfall in the plan doc / commit message when practical collection
    fell short)."""
    assert len(_positive_files) >= 20, (
        f"expected >=20 ko_corpus positive fixtures, found {len(_positive_files)}"
    )


def test_negative_corpus_is_non_empty() -> None:
    assert len(_negative_files) >= 5


# --- Core calibration assertion ---------------------------------------------


def test_ko_corpus_detection_rate_meets_calibration_bar() -> None:
    """The real-world Korean corpus must be detected as ``ko`` at >=95%."""
    results = {
        path.name: detect_language_from_markdown(_read(path))
        for path in _positive_files
    }
    correct = [name for name, verdict in results.items() if verdict == "ko"]
    rate = len(correct) / len(results)
    failures = {name: verdict for name, verdict in results.items() if verdict != "ko"}
    assert rate >= _MIN_DETECTION_RATE, (
        f"ko detection rate {rate:.1%} on {len(results)} real samples is below "
        f"the {_MIN_DETECTION_RATE:.0%} calibration bar; misdetected: {failures}"
    )


@pytest.mark.parametrize("path", _positive_files, ids=lambda p: p.name)
def test_each_positive_sample_individually(path: Path) -> None:
    """Per-file breakdown so a regression points at the exact fixture that
    broke, rather than only the aggregate rate."""
    verdict = detect_language_from_markdown(_read(path))
    # Individual failures are tolerated in aggregate (the 95% bar above is
    # the real gate) but each failure must at least degrade gracefully to
    # "unknown", never to a *wrong confident* language — a wrong confident
    # verdict would silently defeat the validate-time language gate (R1).
    assert verdict in ("ko", "unknown"), (
        f"{path.name} detected as {verdict!r} — a real Korean sample must "
        "never be confidently misdetected as a different concrete language"
    )


# --- Negative-control false-positive guard ----------------------------------


def test_no_false_positive_ko_on_negative_controls() -> None:
    """Lowering/adjusting the threshold must never cause non-Korean text
    (en/ja/zh/ru) to be misdetected as ko. Guards the exact failure mode the
    plan's verification step calls out: "no false positives"."""
    false_positives = {
        path.name: detect_language_from_markdown(_read(path))
        for path in _negative_files
        if detect_language_from_markdown(_read(path)) == "ko"
    }
    assert not false_positives, f"non-Korean fixtures misdetected as ko: {false_positives}"


@pytest.mark.parametrize("path", _negative_files, ids=lambda p: p.name)
def test_each_negative_sample_is_not_ko(path: Path) -> None:
    assert detect_language_from_markdown(_read(path)) != "ko"
