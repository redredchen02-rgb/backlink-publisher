"""Pre-publish pause gate — Plan 2026-06-03-004 Phase 2 U8.

A platform an operator paused via /ce:health is skipped before lease
acquisition and dispatch. Covers the pure partition helper plus an
integration test through main() proving a paused platform never reaches
adapter_publish.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from backlink_publisher.cli.publish_backlinks import _partition_paused, main
from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path, monkeypatch):
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(fake_config_dir))
    with patch(
        "backlink_publisher.config._config_dir", return_value=fake_config_dir,
    ), patch(
        "backlink_publisher.checkpoint._cache_dir", return_value=tmp_path / "cache",
    ):
        from webui_store.channel_status import channel_status_store as _store
        _store.path = fake_config_dir / "channel-status.json"
        yield fake_config_dir


@pytest.fixture(autouse=True)
def _mock_verify_pass():
    with patch(
        "backlink_publisher.cli.publish._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    ):
        yield


@pytest.fixture
def cfg():
    from backlink_publisher.config import load_config
    return load_config()


# ── _partition_paused (unit) ───────────────────────────────────────────────────

def test_partition_no_paused_returns_rows_unchanged(cfg):
    rows = [{"platform": "medium"}, {"platform": "blogger"}]
    kept, paused = _partition_paused(rows, None, cfg)
    assert kept == rows
    assert paused == []


def test_partition_drops_paused_platform(cfg):
    from backlink_publisher.health.persistence import locked_store
    locked_store.set_paused("medium", True, cfg)

    rows = [{"platform": "medium", "id": "a"}, {"platform": "blogger", "id": "b"}]
    kept, paused = _partition_paused(rows, None, cfg)
    assert paused == ["medium"]
    assert [r["id"] for r in kept] == ["b"]


def test_partition_honors_platform_override(cfg):
    # When --platform forces one platform, the per-row platform field is ignored.
    from backlink_publisher.health.persistence import locked_store
    locked_store.set_paused("medium", True, cfg)

    rows = [{"platform": "blogger", "id": "a"}]
    kept, paused = _partition_paused(rows, "medium", cfg)
    assert paused == ["medium"]
    assert kept == []


# ── integration through main() ─────────────────────────────────────────────────

def _payload(platform="blogger", row_id="g-1"):
    return {
        "id": row_id, "platform": platform, "language": "en", "publish_mode": "draft",
        "target_url": "https://example.com/article", "main_domain": "https://example.com",
        "url_mode": "A", "title": "Test Article", "slug": "test-article",
        "excerpt": "An excerpt.", "tags": ["tag1"],
        "content_markdown": "Content about https://example.com page.",
        "links": [
            {"url": "https://example.com", "anchor": "Example", "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article", "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki", "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN", "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO", "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GH", "kind": "supporting", "required": False},
        ],
        "seo": {"title": "T", "description": "D", "canonical_url": "https://example.com/article"},
    }


def _run_publish(input_data, argv=None):
    old = (sys.stdin, sys.stdout, sys.stderr)
    try:
        sys.stdin, sys.stdout, sys.stderr = StringIO(input_data), StringIO(), StringIO()
        try:
            main(argv or [])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return sys.stdout.getvalue(), sys.stderr.getvalue(), code
    finally:
        sys.stdin, sys.stdout, sys.stderr = old


@patch("backlink_publisher.cli.publish_backlinks._publish_epilogue")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_paused_platform_skips_dispatch_exits_0(mock_pub, mock_verify, mock_epilogue, cfg):
    from backlink_publisher.health.persistence import locked_store
    locked_store.set_paused("medium", True, cfg)

    _, _, code = _run_publish(
        json.dumps(_payload(platform="medium")),
        ["--platform", "medium", "--mode", "draft", "--skip-publish-time-check"],
    )
    assert code == 0  # all targets paused → nothing to publish, clean exit
    mock_pub.assert_not_called()  # the load-bearing invariant: no dispatch


@patch("backlink_publisher.cli.publish_backlinks._publish_epilogue")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_unpaused_platform_still_publishes(mock_pub, mock_verify, mock_epilogue, cfg):
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="blogger-api", platform="blogger",
        draft_url="https://blogger.example.com/p/1",
    )
    # medium paused, but this run targets blogger → unaffected.
    from backlink_publisher.health.persistence import locked_store
    locked_store.set_paused("medium", True, cfg)

    _run_publish(json.dumps(_payload(platform="blogger")),
                 ["--mode", "draft", "--skip-publish-time-check"])
    mock_pub.assert_called_once()
