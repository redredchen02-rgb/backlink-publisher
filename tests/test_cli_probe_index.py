"""Tests for probe-index CLI (Plan 2026-06-16-003 Unit 3)."""

from __future__ import annotations

__tier__ = "integration"

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher.cli import probe_index as cli
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import GSC_PAGE_SIGNAL, PUBLISH_CONFIRMED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(*, with_gsc: bool = False, credential_path: str = "/fake/sa.json"):
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


def _seed_published(store: EventStore, urls: list[str]) -> None:
    """Insert PUBLISH_CONFIRMED events so they appear as candidates."""
    for url in urls:
        store.append(PUBLISH_CONFIRMED, {"live_url": url}, target_url=url)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dry_run_no_gsc_exits_cleanly(tmp_path: Path) -> None:
    store = EventStore(path=tmp_path / "events.db")
    _seed_published(store, ["https://example.com/page-a"])

    cfg = _make_cfg()
    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch("backlink_publisher.cli.probe_index.Path", side_effect=lambda p: tmp_path / Path(p).name if "lock" in str(p) else Path(p)),
    ):
        cli.main([])  # --dry-run is default, should not raise


def test_dry_run_prints_candidates(tmp_path: Path, capsys) -> None:
    store = EventStore(path=tmp_path / "events.db")
    _seed_published(store, ["https://a.com/p1", "https://b.com/p2"])

    cfg = _make_cfg()
    cfg_dir = tmp_path
    object.__setattr__(cfg, "_config_dir_override", str(tmp_path))

    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
    ):
        cli.main([])

    out = capsys.readouterr().out
    rows = [json.loads(l) for l in out.strip().splitlines() if l.strip()]
    assert all(r["type"] == "dry_run" for r in rows)
    assert {r["page_url"] for r in rows} == {"https://a.com/p1", "https://b.com/p2"}


def test_probe_no_gsc_config_exits_3(tmp_path: Path) -> None:
    store = EventStore(path=tmp_path / "events.db")
    _seed_published(store, ["https://example.com/x"])

    cfg = _make_cfg()  # no gsc
    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main(["--probe"])

    assert exc_info.value.code == 3


def test_probe_writes_gsc_page_signal_events(tmp_path: Path, capsys) -> None:
    store = EventStore(path=tmp_path / "events.db")
    _seed_published(
        store,
        ["https://example.com/indexed", "https://example.com/not-indexed"],
    )

    sa_json = tmp_path / "sa.json"
    sa_json.write_text('{"type":"service_account"}')
    sa_json.chmod(0o600)
    cfg = _make_cfg(with_gsc=True, credential_path=str(sa_json))

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
        cli.main(["--probe"])

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


def test_no_candidates_exits_cleanly(tmp_path: Path) -> None:
    store = EventStore(path=tmp_path / "events.db")
    # No published URLs seeded
    cfg = _make_cfg()
    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
    ):
        cli.main([])  # should exit 0 with nothing to do


def test_select_candidates_deduplicates_recently_probed(tmp_path: Path) -> None:
    """URLs with a recent GSC_PAGE_SIGNAL event are excluded from candidates."""
    store = EventStore(path=tmp_path / "events.db")
    _seed_published(store, ["https://example.com/page"])

    # Seed a recent probe event (within 30 days)
    store.append(
        GSC_PAGE_SIGNAL,
        {"page_url": "https://example.com/page", "has_impressions": True},
        target_url="https://example.com/page",
    )

    candidates = cli._select_candidates(store, 200)
    assert candidates == [], "recently probed URL should be excluded"


def test_select_candidates_includes_stale_probed(tmp_path: Path) -> None:
    """URLs whose last probe is >30 days old re-enter the candidate queue."""
    from datetime import datetime, timedelta, timezone

    store = EventStore(path=tmp_path / "events.db")
    _seed_published(store, ["https://example.com/old"])

    # Seed a probe event older than 30 days
    old_ts = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    store.append(
        GSC_PAGE_SIGNAL,
        {"page_url": "https://example.com/old", "has_impressions": False},
        target_url="https://example.com/old",
        ts_utc=old_ts,
    )

    candidates = cli._select_candidates(store, 200)
    assert "https://example.com/old" in candidates, "stale-probed URL should re-enter queue"


def test_probe_flock_blocked_exits_6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When flock is already held, probe-index exits with code 6."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))

    store = EventStore(path=tmp_path / "events.db")
    _seed_published(store, ["https://example.com/x"])

    cfg = _make_cfg(with_gsc=True, credential_path=str(tmp_path / "sa.json"))

    with (
        patch("backlink_publisher.cli.probe_index.load_config", return_value=cfg),
        patch("backlink_publisher.cli.probe_index.EventStore", return_value=store),
        patch.object(type(cfg), "config_dir", property(lambda self: tmp_path)),
        patch("fcntl.flock", side_effect=BlockingIOError),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main(["--probe"])

    assert exc_info.value.code == 6
