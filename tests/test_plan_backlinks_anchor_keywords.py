"""Tests for plan-backlinks SEO anchor_keywords integration (R2/R3/R4)."""
from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher.cli.plan_backlinks import _generate_payload
from backlink_publisher.config import Config


def _make_config(main_domain: str, keywords: list[str]) -> Config:
    return Config(target_anchor_keywords={main_domain.rstrip("/"): keywords})


def _seed(url_mode: str = "A", language: str = "en") -> dict:
    return {
        "target_url": "https://target.example.com/post",
        "main_domain": "https://target.example.com",
        "language": language,
        "platform": "medium",
        "url_mode": url_mode,
        "publish_mode": "draft",
        "topic": "Test",
    }


def test_anchor_keywords_used_in_links_main_domain_and_target_kinds():
    cfg = _make_config(
        "https://target.example.com",
        ["BrandWord", "HeadTerm", "LongTailPhrase"],
    )
    payload = _generate_payload(_seed(url_mode="A"), config=cfg)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    target_link = next(l for l in payload["links"] if l["kind"] == "target")
    # url_mode A → offset 0 → anchors[0]=BrandWord, anchors[1]=HeadTerm
    assert main_link["anchor"] == "BrandWord"
    assert target_link["anchor"] == "HeadTerm"


def test_anchor_keywords_url_mode_b_offsets():
    cfg = _make_config(
        "https://target.example.com",
        ["BrandWord", "HeadTerm", "LongTailPhrase"],
    )
    payload = _generate_payload(_seed(url_mode="B"), config=cfg)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    target_link = next(l for l in payload["links"] if l["kind"] == "target")
    # offset 1 → anchors[0]=HeadTerm, anchors[1]=LongTailPhrase
    assert main_link["anchor"] == "HeadTerm"
    assert target_link["anchor"] == "LongTailPhrase"


def test_anchor_keywords_url_mode_c_wraps_around():
    cfg = _make_config(
        "https://target.example.com",
        ["BrandWord", "HeadTerm", "LongTailPhrase"],
    )
    payload = _generate_payload(_seed(url_mode="C"), config=cfg)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    target_link = next(l for l in payload["links"] if l["kind"] == "target")
    # offset 2 → anchors[0]=LongTailPhrase, anchors[1]=BrandWord (wraps)
    assert main_link["anchor"] == "LongTailPhrase"
    assert target_link["anchor"] == "BrandWord"


def test_anchor_keywords_appear_in_body_markdown():
    cfg = _make_config(
        "https://target.example.com",
        ["UniqueAnchorAlpha", "UniqueAnchorBeta"],
    )
    payload = _generate_payload(_seed(url_mode="A", language="en"), config=cfg)
    md = payload["content_markdown"]
    assert "[UniqueAnchorAlpha](https://target.example.com)" in md
    assert "[UniqueAnchorBeta](https://target.example.com)" in md


def test_anchor_keywords_appear_in_excerpt():
    cfg = _make_config(
        "https://target.example.com",
        ["ExcerptKeyword", "AnotherKw"],
    )
    payload = _generate_payload(_seed(url_mode="A"), config=cfg)
    # Excerpt uses anchors[0] in its single anchored slot
    assert "[ExcerptKeyword](https://target.example.com)" in payload["excerpt"]


def test_anchor_keywords_fallback_when_no_pool(caplog):
    cfg = Config()  # no target_anchor_keywords entry
    with caplog.at_level("WARNING"):
        payload = _generate_payload(_seed(url_mode="A"), config=cfg)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    # Falls back to bare-domain label
    assert main_link["anchor"] == "target.example.com"
    # No keyword leakage; the markdown still references the domain
    assert "target.example.com" in payload["content_markdown"]


def test_anchor_keywords_fallback_when_pool_empty():
    cfg = _make_config("https://target.example.com", [])  # explicit empty
    payload = _generate_payload(_seed(url_mode="A"), config=cfg)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    assert main_link["anchor"] == "target.example.com"


def test_anchor_keywords_single_keyword_repeats():
    cfg = _make_config("https://target.example.com", ["OnlyOne"])
    payload = _generate_payload(_seed(url_mode="A"), config=cfg)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    target_link = next(l for l in payload["links"] if l["kind"] == "target")
    # With a 1-element pool both slots get the same keyword (deterministic, OK)
    assert main_link["anchor"] == "OnlyOne"
    assert target_link["anchor"] == "OnlyOne"


@pytest.mark.parametrize("language,url_mode", [
    (lang, mode) for lang in ("en", "zh-CN", "ru", "ko") for mode in ("A", "B", "C")
])
def test_anchor_keywords_all_languages_and_modes(language, url_mode):
    """Body templates for every language+mode combination must wire keywords through."""
    cfg = _make_config(
        "https://target.example.com",
        ["KeywordA", "KeywordB", "KeywordC"],
    )
    payload = _generate_payload(
        _seed(url_mode=url_mode, language=language), config=cfg,
    )
    md = payload["content_markdown"]
    # Both anchor positions must appear inside [<keyword>](main_domain) constructs.
    # The exact two depend on offset, but at least one of the configured
    # keywords must appear in an anchored position.
    assert any(
        f"[{kw}](https://target.example.com)" in md
        for kw in ("KeywordA", "KeywordB", "KeywordC")
    ), f"no SEO anchor keyword present in {language}/{url_mode}: {md[:200]}"
    # Bare-domain anchor must NOT appear inside link brackets pointing to main_domain
    assert "[target.example.com](https://target.example.com)" not in md


def test_anchor_keyword_distribution_across_url_modes():
    """A target site rendered across A+B+C produces ≥3 distinct anchors (R3 spec)."""
    cfg = _make_config(
        "https://target.example.com",
        ["Brand", "Head", "LongTail"],
    )
    distinct_anchors = set()
    for mode in ("A", "B", "C"):
        payload = _generate_payload(_seed(url_mode=mode), config=cfg)
        for link in payload["links"]:
            if link["kind"] in ("main_domain", "target"):
                distinct_anchors.add(link["anchor"])
    assert len(distinct_anchors) >= 3, (
        f"expected ≥3 distinct anchors across A/B/C, got {distinct_anchors}"
    )


def test_anchor_keywords_no_config_uses_fallback_silently_for_payload():
    """Calling _generate_payload with config=None should still succeed (fallback)."""
    payload = _generate_payload(_seed(url_mode="A"), config=None)
    main_link = next(l for l in payload["links"] if l["kind"] == "main_domain")
    assert main_link["anchor"] == "target.example.com"
