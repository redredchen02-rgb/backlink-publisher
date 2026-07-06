"""Tests: publish-backlinks --tier-1 / --dofollow-only tier dispatch."""
from __future__ import annotations

__tier__ = "unit"
from io import StringIO
import json
import sys
from unittest.mock import patch

import pytest

from backlink_publisher.cli.publish_backlinks import main
from backlink_publisher.publishing.adapters.base import AdapterResult

# Unique stub platform slugs per dofollow status
_T1_DOFULL = "t1_test_full"       # dofollow=True  (Tier 1)
_T1_UNCERTAIN = "t1_test_uncertain"  # dofollow="uncertain" (Tier 2)
_T1_FALSE = "t1_test_false"       # dofollow=False (Tier 3)
_T1_STUB_RATIONALE = (
    f"Stub platform for tier U5 testing — will never be used in "
    f"production. {'x' * 80}"
)


def _run_publish(
    input_data: str,
    argv: list[str] | None = None,
) -> tuple[str, str, int]:
    loggers = _all_loggers() if _LOGGERS_SET else []
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    try:
        for lg in loggers:
            lg.setLevel(60)
        sys.stdin = StringIO(input_data)
        out, err = StringIO(), StringIO()
        sys.stdout, sys.stderr = out, err
        try:
            main(argv or [])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return out.getvalue(), err.getvalue(), code
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
        for lg in loggers:
            lg.setLevel(30)


# Lazy logger collection so test collection doesn't trigger early import
_LOGGERS_SET = False
_loggers_cache: list = []


def _all_loggers():
    global _LOGGERS_SET, _loggers_cache
    if not _LOGGERS_SET:
        from backlink_publisher._util.logger import (
            opencli_logger,
            plan_logger,
            publish_logger,
            validate_logger,
        )
        _loggers_cache = [opencli_logger, plan_logger, publish_logger, validate_logger]
        _LOGGERS_SET = True
    return _loggers_cache


def _make_payload(platform: str) -> str:
    return json.dumps({
        "id": f"tier-test-{platform}",
        "platform": platform,
        "language": "en",
        "publish_mode": "draft",
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "url_mode": "A",
        "title": "Tier Test",
        "slug": "tier-test",
        "excerpt": "Tier test.",
        "tags": ["test"],
        "content_markdown": "Test content https://example.com.",
        "links": [
            {"url": "https://example.com", "anchor": "Example",
             "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article",
             "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki",
             "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN",
             "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO",
             "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GH",
             "kind": "supporting", "required": False},
        ],
        "seo": {
            "title": "Test SEO",
            "description": "SEO desc",
            "canonical_url": "https://example.com/article",
        },
    })


# ── Fixture: register two stub platforms per test ─────────────────────────────


@pytest.fixture(autouse=True)
def _stub_tier_platforms():
    """Register one platform per dofollow tier before each test.

    Cleans up all three slugs on teardown.
    """
    from backlink_publisher.publishing.registry import (
        _REGISTRY,
        Publisher,
        register,
    )

    class StubAdapter(Publisher):
        @classmethod
        def available(cls, config) -> bool:
            return True

        def publish(self, payload, mode, config) -> AdapterResult:
            plat = payload.get("platform", "unknown")
            return AdapterResult(
                status="drafted",
                adapter=plat,
                platform=plat,
                draft_url=f"https://{plat}.example/p/1",
            )

    saved = {
        slug: _REGISTRY.get(slug)
        for slug in (_T1_DOFULL, _T1_UNCERTAIN, _T1_FALSE)
    }
    register(_T1_DOFULL, StubAdapter(), dofollow=True)
    register(_T1_UNCERTAIN, StubAdapter(), dofollow="uncertain",
             rationale=_T1_STUB_RATIONALE, referral_value="low")
    register(_T1_FALSE, StubAdapter(), dofollow=False,
             rationale=_T1_STUB_RATIONALE, referral_value="low")
    try:
        yield
    finally:
        for slug in (_T1_DOFULL, _T1_UNCERTAIN, _T1_FALSE):
            prev = saved[slug]
            if prev is None:
                _REGISTRY.pop(slug, None)
            else:
                _REGISTRY[slug] = prev


# ── Tests: --tier-1 filters non-T1 rows ───────────────────────────────────────


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli.publish._publish_helpers.verify_published")
def test_tier1_filters_uncertain_and_false(mock_vp, mock_pub, mock_verify):
    """--tier-1 dispatches only dofollow=True rows, skips uncertain+false."""
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="stub", platform="stub",
        draft_url="https://stub.example/p/1",
    )

    rows = [
        _make_payload(_T1_DOFULL),
        _make_payload(_T1_UNCERTAIN),
        _make_payload(_T1_FALSE),
    ]
    stdout, stderr, code = _run_publish(
        "\n".join(rows), ["--tier-1", "--dry-run"]
    )
    assert code == 0, f"exit {code}: {stderr}"
    # stderr should mention skipped platforms
    assert "tier-filter" in stderr
    assert _T1_UNCERTAIN in stderr
    assert _T1_FALSE in stderr


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli.publish._publish_helpers.verify_published")
def test_tier1_passes_dofollow_true(mock_vp, mock_pub, mock_verify):
    """--tier-1 passes through dofollow=True rows unchanged."""
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="stub", platform="stub",
        draft_url="https://stub.example/p/1",
    )

    rows = [_make_payload(_T1_DOFULL)]
    stdout, stderr, code = _run_publish(
        "\n".join(rows), ["--tier-1", "--dry-run"]
    )
    assert code == 0, f"exit {code}: {stderr}"
    assert "tier-filter" not in stderr


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli.publish._publish_helpers.verify_published")
def test_tier1_all_filtered_exit_0(mock_vp, mock_pub, mock_verify):
    """When all rows filtered, --tier-1 exits 0 with info message."""
    rows = [_make_payload(_T1_FALSE)]
    stdout, stderr, code = _run_publish(
        "\n".join(rows), ["--tier-1", "--dry-run"]
    )
    assert code == 0, f"exit {code}: {stderr}"
    assert "tier-filter" in stderr
    assert "all-filtered" in stderr


# ── Tests: --dofollow-only alias parity ────────────────────────────────────────


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli.publish._publish_helpers.verify_published")
def test_dofollow_only_alias_parity(mock_vp, mock_pub, mock_verify):
    """--dofollow-only behaves identically to --tier-1."""
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="stub", platform="stub",
        draft_url="https://stub.example/p/1",
    )

    rows = [
        _make_payload(_T1_DOFULL),
        _make_payload(_T1_UNCERTAIN),
    ]
    stdout, stderr, code = _run_publish(
        "\n".join(rows), ["--dofollow-only", "--dry-run"]
    )
    assert code == 0, f"exit {code}: {stderr}"
    assert "tier-filter" in stderr
    assert _T1_UNCERTAIN in stderr


# ── Tests: no-flag behavior unchanged ──────────────────────────────────────────


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli.publish._publish_helpers.verify_published")
def test_no_flag_passes_all_tiers(mock_vp, mock_pub, mock_verify):
    """Without --tier-1, all rows pass through unchanged."""
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="stub", platform="stub",
        draft_url="https://stub.example/p/1",
    )

    rows = [
        _make_payload(_T1_DOFULL),
        _make_payload(_T1_UNCERTAIN),
        _make_payload(_T1_FALSE),
    ]
    stdout, stderr, code = _run_publish(
        "\n".join(rows), ["--dry-run"]
    )
    assert code == 0, f"exit {code}: {stderr}"
    assert "tier-filter" not in stderr


# ── Test: --tier-1 appears in --help ───────────────────────────────────────────


def test_tier1_in_help():
    """--tier-1 and --dofollow-only appear in publish-backlinks --help."""
    from backlink_publisher.cli._publish_helpers import _build_parser
    parser = _build_parser()
    help_text = parser.format_help()
    assert "--tier-1" in help_text
    assert "--dofollow-only" in help_text
