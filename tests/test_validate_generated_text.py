"""Tests for _validate_generated_text — Plan 2026-05-27-006 Unit 4.

Unit 4 test scenarios:
- Happy path: text with anchor in the link to target_url → ok, generated_text carried.
- Edge case: anchor only in body (not in <a> text) → rejected missing_anchor.
- Edge case: anchor differs by case/whitespace → ok (normalized match).
- Error path: no link to target_url → missing_link.
- Edge case: extra link to another domain → stripped, stripped_extra_links set, record ok.
- Edge case: target.com@evil.com confusion link → host canonicalized, stripped.
- Error path: article body > 400 words → length_out_of_bounds.
- Error path: comment under 30 words → length_out_of_bounds.
- Error path: output contains bidi override char → unsafe_chars.
- Error path: refusal phrase in output → llm_refusal.
- Edge case: zh output for en request → ok + language_flag set (NOT rejected).
- Edge case: long (>200 char) target_url → output target_url is full URL, not truncated.
"""
from __future__ import annotations

__tier__ = "unit"
import pytest


# Helpers for building word-count-appropriate texts.

def _make_comment_text(link_url: str, link_text: str) -> str:
    """Build ~45-word comment containing exactly one Markdown link (within 30-80 bound)."""
    # 39-word filler + link_text (variable) + 5-word suffix ≈ 44+ words
    filler = (
        "This article provides excellent insights into digital marketing and "
        "modern SEO practices. The content is well-researched and thoughtfully "
        "written, offering practical advice for professionals who want to improve "
        "their online presence and drive more organic traffic to their websites."
    )
    return f"{filler} [{link_text}]({link_url}) is an excellent resource."


def _make_article_text(link_url: str, link_text: str) -> str:
    """Build ~210-word article body containing exactly one Markdown link."""
    para = (
        "Digital marketing has evolved significantly over the past decade with "
        "search engine optimization becoming a critical component of any successful "
        "online strategy. Businesses must adapt to changing algorithms and user "
        "behavior patterns to maintain their competitive edge in the marketplace. "
    )
    return para * 4 + f"[{link_text}]({link_url}) is an excellent resource. " + para


def test_validate_generated_text_happy_path_comment():
    """Comment with anchor in link → ok, text carried, no advisory flags."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = _make_comment_text("https://example.com/", "example anchor")
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
    )
    assert result["ok"] is True
    assert "example anchor" in result["text"]
    assert result["stripped_extra_links"] == 0
    assert result["language_flag"] is None


def test_validate_generated_text_happy_path_article():
    """Article-length text with anchor in link → ok."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = _make_article_text("https://example.com/page", "example anchor")
    result = _validate_generated_text(
        text,
        target_url="https://example.com/page",
        anchor_text="example anchor",
        mode="article",
    )
    assert result["ok"] is True


def test_validate_generated_text_missing_link():
    """No Markdown link in text → rejected missing_link."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = "This article has no links at all. Just plain text content here."
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="anchor", mode="comment"
    )
    assert result == {"ok": False, "reason": "missing_link"}


def test_validate_generated_text_missing_anchor():
    """Link to correct URL but anchor text absent from link text → missing_anchor."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = _make_comment_text("https://example.com/", "completely wrong text")
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="example anchor", mode="comment"
    )
    assert result == {"ok": False, "reason": "missing_anchor"}


def test_validate_generated_text_case_whitespace_normalized():
    """Anchor in link text with different case/whitespace → ok (normalized match)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # "EXAMPLE  ANCHOR" should match anchor_text="example anchor" after normalization
    text = _make_comment_text("https://example.com/", "EXAMPLE  ANCHOR")
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="example anchor", mode="comment"
    )
    assert result["ok"] is True


def test_validate_generated_text_extra_link_stripped():
    """Extra link to a different domain → stripped; stripped_extra_links=1; ok if target survives."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    base_text = _make_comment_text("https://example.com/", "example anchor")
    # Insert an extra link to a different host
    text = base_text.replace("is an excellent", "[extra](https://evil.com/page) is an excellent")
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="example anchor", mode="comment"
    )
    assert result["ok"] is True
    assert result["stripped_extra_links"] == 1
    # The stripped text should not contain the evil.com link syntax
    assert "evil.com" not in result["text"]


def test_validate_generated_text_userinfo_confusion_link_stripped():
    """target.com@evil.com link → urlparse gives evil.com as host → stripped."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # This is a confused link: target.com@evil.com has evil.com as its hostname
    text = _make_comment_text("https://target.com@evil.com/page", "example anchor")
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="example anchor", mode="comment"
    )
    # evil.com's host != example.com's host → stripped → no target link → missing_link
    assert result == {"ok": False, "reason": "missing_link"}


def test_validate_generated_text_length_out_of_bounds_article_too_short():
    """Article with fewer than 200 words → length_out_of_bounds."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # Use a very short article (well under 200 words)
    text = "Short article. [anchor](https://example.com/) is great."
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="anchor", mode="article"
    )
    assert result == {"ok": False, "reason": "length_out_of_bounds"}


def test_validate_generated_text_length_out_of_bounds_comment_too_short():
    """Comment with fewer than 30 words → length_out_of_bounds."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = "Great post! [anchor](https://example.com/) — very helpful."
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="anchor", mode="comment"
    )
    assert result == {"ok": False, "reason": "length_out_of_bounds"}


def test_validate_generated_text_unsafe_chars():
    """Bidi override char (U+202E) in output → unsafe_chars."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    evil_text = _make_comment_text("https://example.com/", "anchor") + "\u202e"
    result = _validate_generated_text(
        evil_text, target_url="https://example.com/", anchor_text="anchor", mode="comment"
    )
    assert result == {"ok": False, "reason": "unsafe_chars"}


def test_validate_generated_text_llm_refusal():
    """LLM refusal phrase in output → llm_refusal."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = "I cannot assist with this request as it involves SEO link building."
    result = _validate_generated_text(
        text, target_url="https://example.com/", anchor_text="anchor", mode="comment"
    )
    assert result == {"ok": False, "reason": "llm_refusal"}


def test_validate_generated_text_language_flag_mismatch():
    """zh-CN output for en request → ok + language_flag set (never rejected)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # ~80 CJK chars → ~40 "words" (within comment 30-80 bound).
    # Language detection: zh-CN codepoints dominate → language_flag = "zh-CN".
    zh_text = (
        "这篇文章提供了关于数字营销和搜索引擎优化的深刻见解，帮助读者更好地理解现代SEO策略和技术。"
        "[example anchor](https://example.com/) 是一个非常优质的资源，内容翔实，非常值得推荐阅读。"
        "文章深入浅出，适合所有希望提升网站排名和在线影响力的读者阅读学习参考。"
    )
    result = _validate_generated_text(
        zh_text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
        language="en",
    )
    assert result["ok"] is True, f"Expected ok=True, got: {result}"
    assert result["language_flag"] is not None, "language_flag should be set for zh→en mismatch"
    assert result["language_flag"] != "en"


def test_validate_generated_text_language_match_no_flag():
    """en output for en request → ok, language_flag is None."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    text = _make_comment_text("https://example.com/", "example anchor")
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
        language="en",
    )
    assert result["ok"] is True
    assert result["language_flag"] is None


def test_validate_generated_text_long_target_url():
    """Long (>200 char) target_url: host matching still works on full URL."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # URL longer than 200 chars; the model may truncate in the link
    long_path = "a" * 180
    target_url = f"https://example.com/{long_path}"
    # Model embeds the same URL in the link
    text = _make_comment_text(target_url, "example anchor")
    result = _validate_generated_text(
        text,
        target_url=target_url,
        anchor_text="example anchor",
        mode="comment",
    )
    assert result["ok"] is True
    # output target_url field (assembled by _run_generate) is the full URL
    # (validated here indirectly — validation passes so assembler uses rec["target_url"])


def test_validate_generated_text_length_out_of_bounds_article_too_long():
    """Article body > 400 words → length_out_of_bounds (TST-001)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # Build >400-word article with exactly one Markdown link.
    filler_word = "word"
    # 420 words of filler around the required link
    filler = (" ".join([filler_word] * 210) + " ")
    link = "[example anchor](https://example.com/)"
    text = filler + link + " " + filler
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="article",
    )
    assert result == {"ok": False, "reason": "length_out_of_bounds"}


def test_validate_generated_text_length_out_of_bounds_comment_too_long():
    """Comment body > 80 words → length_out_of_bounds (TST-002)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    # Build 90-word comment with exactly one Markdown link.
    filler_word = "word"
    filler = " ".join([filler_word] * 44)
    link = "[example anchor](https://example.com/)"
    # filler (44) + link (counted as ~3 words) + filler (44) ≈ 91 words
    text = filler + " " + link + " " + filler
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
    )
    assert result == {"ok": False, "reason": "length_out_of_bounds"}


def test_validate_generated_text_multiple_extra_links_stripped():
    """Multiple extra links to different domains → all stripped; stripped_extra_links counts them (TST-004)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_generated_text

    base_text = _make_comment_text("https://example.com/", "example anchor")
    # Insert two extra links to different hosts
    extra1 = "[spam1](https://spam1.com/a)"
    extra2 = "[spam2](https://spam2.net/b)"
    text = extra1 + " " + base_text + " " + extra2
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
    )
    assert result["ok"] is True
    assert result["stripped_extra_links"] == 2
    assert "spam1.com" not in result["text"]
    assert "spam2.net" not in result["text"]
    # The real link must survive
    assert "example.com" in result["text"]
