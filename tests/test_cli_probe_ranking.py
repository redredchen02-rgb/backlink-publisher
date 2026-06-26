"""Tests for probe-ranking CLI (Plan 2026-06-16-003 Unit 4)."""

from __future__ import annotations

__tier__ = "integration"

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher.cli import probe_ranking as cli
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import RANKING_SNAPSHOT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(*, keywords: list[str] | None = None, credential_path: str = "/fake/sa.json"):
    from backlink_publisher.config.types import Config, GscConfig

    cfg = Config()
    if keywords is not None:
        gsc = GscConfig(
            credential_path=credential_path,
            property_url="sc-domain:example.com",
            ranking_keywords=keywords,
        )
        object.__setattr__(cfg, "gsc", gsc)
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_no_keywords_exits_cleanly() -> None:
    cfg = _make_cfg(keywords=[])
    with patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg):
        cli.main([])  # Should return cleanly with "no keywords" recon


def test_dry_run_prints_keywords(capsys) -> None:
    cfg = _make_cfg(keywords=["seo tips", "backlinks guide"])
    with patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg):
        cli.main([])

    out = capsys.readouterr().out
    rows = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert len(rows) == 2
    assert {r["keyword"] for r in rows} == {"seo tips", "backlinks guide"}
    assert all(r["type"] == "dry_run" for r in rows)


def test_no_gsc_config_exits_cleanly() -> None:
    cfg = _make_cfg()  # gsc=None
    with patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg):
        cli.main([])  # no keywords → early return


def test_probe_no_gsc_section_exits_cleanly() -> None:
    # No [gsc] section → no keywords → early return (exit 0, not exit 3)
    cfg = _make_cfg()  # gsc=None
    with patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg):
        cli.main(["--probe"])  # should exit cleanly


def test_probe_missing_property_url_exits_3(tmp_path: Path) -> None:
    from backlink_publisher.config.types import Config, GscConfig

    cfg = Config()
    gsc = GscConfig(
        credential_path="/fake/sa.json",
        property_url=None,  # missing!
        ranking_keywords=["seo tips"],
    )
    object.__setattr__(cfg, "gsc", gsc)

    with (
        patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main(["--probe"])

    assert exc_info.value.code == 3


def test_probe_writes_ranking_snapshot_events(tmp_path: Path, capsys) -> None:
    store = EventStore(path=tmp_path / "events.db")
    sa_json = tmp_path / "sa.json"
    sa_json.write_text('{"type":"service_account"}')
    sa_json.chmod(0o600)

    cfg = _make_cfg(keywords=["seo tips", "link building"], credential_path=str(sa_json))
    mock_gsc_response = {
        "rows": [
            {"keys": ["seo tips"], "position": 12.5, "impressions": 100, "clicks": 5},
            {"keys": ["link building"], "position": 8.0, "impressions": 50, "clicks": 3},
        ]
    }
    mock_client = MagicMock()
    mock_client.search_analytics_query.return_value = mock_gsc_response

    with (
        patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_ranking.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        patch("backlink_publisher.gsc.client.GscClient", return_value=mock_client),
    ):
        cli.main(["--probe"])

    events = store.query("SELECT payload_json FROM events WHERE kind = ?", (RANKING_SNAPSHOT,))
    assert len(events) == 2
    payloads = [json.loads(e["payload_json"]) for e in events]
    seo_tips = next(p for p in payloads if p["keyword"] == "seo tips")
    assert seo_tips["avg_position"] == 12.5
    assert seo_tips["impressions"] == 100


def test_probe_keyword_absent_in_gsc_writes_none_position(tmp_path: Path) -> None:
    store = EventStore(path=tmp_path / "events.db")
    sa_json = tmp_path / "sa.json"
    sa_json.write_text('{"type":"service_account"}')
    sa_json.chmod(0o600)

    cfg = _make_cfg(keywords=["rare keyword"], credential_path=str(sa_json))
    mock_client = MagicMock()
    mock_client.search_analytics_query.return_value = {"rows": []}  # no data

    with (
        patch("backlink_publisher.cli.probe_ranking.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_ranking.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        patch("backlink_publisher.gsc.client.GscClient", return_value=mock_client),
    ):
        cli.main(["--probe"])

    events = store.query("SELECT payload_json FROM events WHERE kind = ?", (RANKING_SNAPSHOT,))
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload["avg_position"] is None
    assert payload["impressions"] == 0
