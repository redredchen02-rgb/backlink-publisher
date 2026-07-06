"""Tests for plan-backlinks — core pipeline, URL modes, languages, output integrity.

Split refactoring: helpers moved to ``_plan_test_helpers.py``; content-gate,
SEO anchor-keywords, CSV/sitemap input, prefetch/stats, and config-echo tests
live in their own files.
"""
from __future__ import annotations

__tier__ = "unit"

import json
import re

import pytest

from _plan_test_helpers import _run_plan, _stderr_without_warnings, _make_seed


def test_plan_three_rows():
    """plan-backlinks can read 3 JSONL rows and output 3 planned payload rows."""
    seeds = [
        _make_seed(
            target_url="https://example.com/article",
            main_domain="https://example.com",
            language="en",
            platform="medium",
            url_mode="A",
            topic="Test Topic",
        ),
        _make_seed(
            target_url="https://blog.example.org/post",
            main_domain="https://blog.example.org",
            language="zh-CN",
            platform="blogger",
            url_mode="C",
        ),
        _make_seed(
            target_url="https://tech.ru/overview",
            main_domain="https://tech.ru",
            language="ru",
            platform="medium",
            url_mode="B",
        ),
    ]
    input_data = "\n".join(json.dumps(s) for s in seeds)
    stdout, stderr, code = _run_plan(input_data)
    assert code == 0, f"Expected exit 0, got {code}. stderr: {stderr}"
    assert _stderr_without_warnings(stderr) == "", (
        f"Expected only WARN lines on stderr, got: {stderr}"
    )
    lines = stdout.strip().split("\n")
    assert len(lines) == 3, f"Expected 3 output rows, got {len(lines)}"
    for line in lines:
        payload = json.loads(line)
        assert "id" in payload
        assert "title" in payload
        assert "content_markdown" in payload
        assert "links" in payload
        assert 5 <= len(payload["links"]) <= 8
        assert payload["main_domain"] in payload["content_markdown"]


def test_plan_emits_preflight_nudge_on_success():
    """Plan 2026-05-26-008 R3a: a successful run emits a RECON preflight_nudge."""
    seed = _make_seed(topic="Test Topic")
    input_data = "\n".join(json.dumps(s) for s in [seed])
    stdout, stderr, code = _run_plan(input_data)
    assert code == 0, f"stderr: {stderr}"
    assert '"msg": "preflight_nudge"' in stderr
    assert '"level": "RECON"' in stderr
    assert "preflight-targets" in stderr
    assert _stderr_without_warnings(stderr) == ""
    for line in stdout.strip().split("\n"):
        json.loads(line)
    assert "preflight_nudge" not in stdout


def test_plan_failure_path_no_preflight_nudge():
    """Nudge fires only on success; a run that fails before write_jsonl must not emit it."""
    stdout, stderr, code = _run_plan("{not valid json")
    assert code != 0
    assert "preflight_nudge" not in stderr


def test_plan_empty_input():
    """Empty input must produce an error on stderr and non-zero exit."""
    stdout, stderr, code = _run_plan("")
    assert code == 2
    assert "empty input" in stderr.lower()
    assert stdout == ""


def test_plan_malformed_json():
    """Malformed JSON in input must produce error."""
    stdout, stderr, code = _run_plan("{broken\n")
    assert code == 2
    assert "malformed" in stderr.lower()
    assert stdout == ""


def test_plan_unsupported_platform():
    """platform=xyznonexistent rejected with exit code 2."""
    seed = _make_seed(platform="xyznonexistent")
    stdout, stderr, code = _run_plan(json.dumps(seed))
    assert code == 2
    assert "xyznonexistent" in stderr.lower()
    assert stdout == ""


def test_plan_missing_required_field():
    """Missing required field must produce error."""
    seed = _make_seed(main_domain="")  # empty = missing
    del seed["main_domain"]
    stdout, stderr, code = _run_plan(json.dumps(seed))
    assert code == 2
    assert stdout == ""


def test_plan_invalid_url_mode():
    """Invalid url_mode must produce error."""
    seed = _make_seed(url_mode="Z")
    stdout, stderr, code = _run_plan(json.dumps(seed))
    assert code == 2
    assert "url_mode" in stderr.lower()
    assert stdout == ""


def test_plan_all_url_modes():
    """All URL modes (A, B, C) must produce valid output."""
    for mode in ("A", "B", "C"):
        seed = _make_seed(url_mode=mode)
        stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 0, f"Mode {mode} failed: {stderr}"
        payload = json.loads(stdout.strip())
        assert payload["url_mode"] == mode
        assert 5 <= len(payload["links"]) <= 8
        assert payload["main_domain"] in payload["content_markdown"]


def test_plan_no_synthesized_categories_url_without_config():
    """Regression: B/C mode must NOT emit hardcoded URLs when config has no url_categories."""
    for mode in ("B", "C"):
        seed = {
            "target_url": "https://example.com/",
            "main_domain": "https://example.com/",
            "language": "zh-CN",
            "platform": "blogger",
            "url_mode": mode,
            "publish_mode": "publish",
        }
        stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 0, f"Mode {mode} failed: {stderr}"
        payload = json.loads(stdout.strip())
        urls = [link["url"] for link in payload["links"]]
        assert "https://example.com/categories" not in urls, (
            f"Mode {mode} re-introduced hardcoded /categories link: {urls}"
        )
        assert "https://example.com/detail" not in urls
        assert "/categories" not in payload["content_markdown"]
        assert "/detail" not in payload["content_markdown"]


def test_plan_all_languages():
    """All supported languages must produce valid output."""
    for lang in ("en", "zh-CN", "ru", "ko"):
        seed = _make_seed(language=lang)
        stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 0, f"Language {lang} failed: {stderr}"
        payload = json.loads(stdout.strip())
        assert payload["language"] == lang
        assert len(payload["title"]) > 0
        assert len(payload["content_markdown"]) > 20
        if lang == "ko":
            assert any("가" <= c <= "힣" for c in payload["content_markdown"])


def test_plan_stable_deterministic_id():
    """Same seed input must always produce the same id."""
    seed = _make_seed()
    stdout1, _, _ = _run_plan(json.dumps(seed))
    stdout2, _, _ = _run_plan(json.dumps(seed))
    assert stdout1 == stdout2


def test_plan_main_domain_natural_placement():
    """main_domain must appear naturally in content, not at very start or end."""
    seed = _make_seed()
    stdout, stderr, code = _run_plan(json.dumps(seed))
    assert code == 0
    payload = json.loads(stdout.strip())
    content = payload["content_markdown"]
    stripped = content.lstrip("# ")
    assert not stripped.startswith("https://example.com")
    assert not content.rstrip().endswith("https://example.com")


@pytest.mark.parametrize("language,url_mode", [
    ("en", "A"), ("en", "B"), ("en", "C"),
    ("zh-CN", "A"), ("zh-CN", "B"), ("zh-CN", "C"),
    ("ru", "A"), ("ru", "B"), ("ru", "C"),
    ("ko", "A"), ("ko", "B"), ("ko", "C"),
])
def test_all_main_domain_occurrences_are_hyperlinked(language, url_mode):
    """Every main_domain URL in content_markdown must be wrapped as [anchor](url)."""
    seed = _make_seed(language=language, url_mode=url_mode, platform="blogger")
    stdout, _, code = _run_plan(json.dumps(seed))
    assert code == 0
    payload = json.loads(stdout.strip())
    content = payload["content_markdown"]
    bare = re.findall(r'(?<!\]\()https://example\.com[/]?(?!\))', content)
    assert not bare, (
        f"[{language}/{url_mode}] Found {len(bare)} bare URL(s): {bare}"
    )
    links = re.findall(r'\[[^\]]+\]\(https://example\.com[^)]*\)', content)
    assert len(links) >= 2, (
        f"[{language}/{url_mode}] Expected ≥2 markdown links, found {len(links)}"
    )


def test_plan_no_stderr_on_success():
    """On success, stderr must contain no errors (WARN lines are allowed)."""
    seed = _make_seed()
    _, stderr, code = _run_plan(json.dumps(seed))
    assert code == 0
    assert _stderr_without_warnings(stderr) == "", (
        f"Expected only WARN lines on stderr, got: {stderr!r}"
    )


@pytest.mark.parametrize("language,url_mode,same_url", [
    ("en", "A", True), ("en", "A", False),
    ("zh-CN", "A", True), ("zh-CN", "A", False),
    ("ru", "A", True), ("ru", "A", False),
    ("ko", "A", True), ("ko", "A", False),
    ("zh-CN", "B", False), ("zh-CN", "C", False),
])
def test_target_site_link_density(language, url_mode, same_url):
    """Every article must contain ≥ 6 hyperlinks pointing to the target site."""
    main_domain = "https://example.com"
    target_url = main_domain if same_url else "https://example.com/article"
    seed = _make_seed(
        target_url=target_url, main_domain=main_domain,
        language=language, url_mode=url_mode, platform="blogger",
    )
    stdout, _, code = _run_plan(json.dumps(seed))
    assert code == 0
    content = json.loads(stdout.strip())["content_markdown"]
    links = re.findall(r'\[[^\]]+\]\(https://example\.com[^)]*\)', content)
    assert len(links) >= 6, (
        f"[{language}/{url_mode}/same={same_url}] Expected ≥6 target-site links, "
        f"found {len(links)}: {links}"
    )


def test_plan_output_fields():
    """Output must contain all required fields."""
    seed = _make_seed(topic="Test")
    stdout, stderr, code = _run_plan(json.dumps(seed))
    assert code == 0
    payload = json.loads(stdout.strip())
    required = ["id", "platform", "language", "publish_mode", "target_url",
                "main_domain", "url_mode", "title", "slug", "excerpt", "tags",
                "content_markdown", "links", "seo"]
    for field in required:
        assert field in payload, f"Missing field: {field}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
