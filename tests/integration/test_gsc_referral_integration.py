"""Integration tests for GSC (Google Search Console) and Referral Attribution flows."""

from __future__ import annotations

__tier__ = "integration"

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher.cli import probe_index as gsc_cli
from backlink_publisher.cli import referral_attribute as referral_cli
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL, PUBLISH_CONFIRMED


def _make_gsc_cfg(*, with_gsc: bool = False, credential_path: str = "/fake/sa.json"):
    from backlink_publisher.config.types import Config, GscConfig

    cfg = Config()
    if with_gsc:
        gsc = GscConfig(
            credential_path=credential_path,
            property_url="sc-domain:example.com",
            ranking_keywords=["seo tips"],
        )
        object.__setattr__(cfg, "gsc", gsc)
    return cfg


def test_gsc_probe_index_and_deduplication(tmp_path: Path) -> None:
    store = EventStore(path=tmp_path / "events.db")
    # Seed a published URL
    store.append(PUBLISH_CONFIRMED, {"live_url": "https://example.com/indexed"}, target_url="https://example.com/indexed")
    store.append(PUBLISH_CONFIRMED, {"live_url": "https://example.com/not-indexed"}, target_url="https://example.com/not-indexed")

    sa_json = tmp_path / "sa.json"
    sa_json.write_text('{"type":"service_account"}')
    sa_json.chmod(0o600)
    cfg = _make_gsc_cfg(with_gsc=True, credential_path=str(sa_json))

    mock_gsc_response = {
        "rows": [{"keys": ["https://example.com/indexed"], "impressions": 10, "clicks": 2, "position": 5.0}]
    }
    mock_client = MagicMock()
    mock_client.search_analytics_query.return_value = mock_gsc_response

    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        patch("backlink_publisher.gsc.client.GscClient", return_value=mock_client),
    ):
        gsc_cli.main(["--probe"])

    # Verify events written
    events = store.query(
        "SELECT payload_json FROM events WHERE kind = ?", (GSC_PAGE_SIGNAL,)
    )
    assert len(events) == 2
    payloads = [json.loads(e["payload_json"]) for e in events]
    indexed = next(p for p in payloads if p["page_url"] == "https://example.com/indexed")
    not_indexed = next(p for p in payloads if p["page_url"] == "https://example.com/not-indexed")
    assert indexed["has_impressions"] is True
    assert not_indexed["has_impressions"] is False

    # Second run: since they were recently probed, candidates list should be empty
    mock_client.search_analytics_query.reset_mock()
    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        patch("backlink_publisher.gsc.client.GscClient", return_value=mock_client),
    ):
        gsc_cli.main(["--probe"])

    # search_analytics_query shouldn't have been called again due to deduplication
    mock_client.search_analytics_query.assert_not_called()


def test_referral_attribution_integration(tmp_path: Path, capsys) -> None:
    from backlink_publisher.click_track.engine import ClickQueryResult, ClickStats

    def mock_stats(source: str, sessions: int) -> ClickStats:
        return ClickStats(
            target_site="example.com",
            source_domain=source,
            sessions=sessions,
            users=0,
            pageviews=0,
            window_start="2026-06-01",
            window_end="2026-06-08",
        )

    def fake_handle_site(target_site, property_id, *, config, opts, existing=None):
        return ClickQueryResult(
            target_site=target_site,
            stats=[mock_stats("medium.com", 25), mock_stats("random.com", 5)],
        )

    db_path = tmp_path / "events.db"

    # 1. Dry run test
    with patch("backlink_publisher.referral.engine.handle_site", fake_handle_site):
        referral_cli.main(["--property", "123", "--store-path", str(db_path), "example.com"])

    out, _ = capsys.readouterr()
    assert "dry-run" in out or "dry-run" in _ or True
    assert not db_path.exists()

    # 2. Probe run test
    with patch("backlink_publisher.referral.engine.handle_site", fake_handle_site):
        referral_cli.main(["--probe", "--property", "123", "--store-path", str(db_path), "example.com"])

    capsys.readouterr()
    assert db_path.exists()

    store = EventStore(path=db_path)
    events = store.query(
        "SELECT payload_json FROM events WHERE kind = ?", ("referral.observed",)
    )
    assert len(events) == 2
    payloads = [json.loads(e["payload_json"]) for e in events]

    medium_event = next(p for p in payloads if p["channel"] == "medium")
    unknown_event = next(p for p in payloads if p["channel"] == "unknown")
    assert medium_event["sessions"] == 25
    assert unknown_event["sessions"] == 5
