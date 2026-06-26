"""Unit 3 — spray-backlinks per-shot LLM rewrite + row assembly.

The LLM is always injected (a fake ``rewrite_fn``) so no test hits the network.
Covers: distinct bodies per shot, salted ids, validation, empty-body rejection,
and the R4a hard-abort when no LLM is configured.
"""
from __future__ import annotations

__tier__ = "unit"
import pytest

from backlink_publisher._util.errors import InputValidationError
from backlink_publisher.cli.spray_backlinks._draft import (
    _default_rewrite_fn,
    _salt_id,
    draft_row,
    LLMNotConfiguredError,
)
from backlink_publisher.config import load_config


def _seed() -> dict:
    return {
        "target_url": "https://example.com/post",
        "main_domain": "https://example.com",
        "language": "zh-CN",
        "platform": "telegraph",
        "url_mode": "A",
        "publish_mode": "draft",
    }


def _fake_rewrite(platform, shot_idx, domain_label, main_domain, anchors, topic, language):
    return f"# Article for {platform} (variant {shot_idx})\n\nDistinct body text for {platform}."


def test_draft_row_uses_llm_body_and_validates():
    cfg = load_config()
    row = draft_row(
        _seed(), "telegraph", 0, cfg,
        rewrite_fn=_fake_rewrite, fetch_verify_enabled=False,
    )
    assert "telegraph" in row["content_markdown"]
    assert "content_html" not in row
    assert row["platform"] == "telegraph"


def test_bodies_are_mutually_distinct_across_shots():
    cfg = load_config()
    r0 = draft_row(_seed(), "telegraph", 0, cfg, rewrite_fn=_fake_rewrite, fetch_verify_enabled=False)
    r1 = draft_row(_seed(), "rentry", 1, cfg, rewrite_fn=_fake_rewrite, fetch_verify_enabled=False)
    assert r0["content_markdown"] != r1["content_markdown"]
    assert r0["id"] != r1["id"]  # salted per platform+shot


def test_salt_id_is_deterministic_and_shot_specific():
    a = _salt_id("base", "telegraph", 0)
    b = _salt_id("base", "telegraph", 0)
    c = _salt_id("base", "telegraph", 1)
    assert a == b and a != c and len(a) == 16


def test_empty_llm_body_is_rejected():
    cfg = load_config()
    with pytest.raises(InputValidationError):
        draft_row(
            _seed(), "telegraph", 0, cfg,
            rewrite_fn=lambda *a, **k: "   ",  # blank
            fetch_verify_enabled=False,
        )


def test_no_llm_configured_hard_aborts_no_fallback():
    cfg = load_config()  # sandbox: llm_anchor_provider is None
    assert getattr(cfg, "llm_anchor_provider", None) is None
    with pytest.raises(LLMNotConfiguredError) as exc:
        _default_rewrite_fn(cfg)
    assert exc.value.exit_code == 3
