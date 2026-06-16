"""Integration tests for the referral-attribute CLI verb (Plan 2026-06-15-004 U2).

Covers:
* Dry-run: zero GA4 calls, zero store writes, JSONL output.
* --probe with query success → store has per-channel ``referral.observed`` events.
* --probe with query error → no referral events, error surfaced in JSONL.
* Unknown source is attributed to the ``unknown`` channel, not dropped.
"""
from __future__ import annotations

__tier__ = "integration"
import json
import sqlite3
from pathlib import Path

import pytest

from backlink_publisher.click_track.engine import ClickQueryResult, ClickStats


def _stat(source: str, sessions: int) -> ClickStats:
    return ClickStats(
        target_site="t1.example",
        source_domain=source,
        sessions=sessions,
        users=0,
        pageviews=0,
        window_start="2026-06-01",
        window_end="2026-06-08",
    )


@pytest.fixture
def mock_handle_site_success(mocker):
    def fake(target_site, property_id, *, config, opts, existing=None):
        return ClickQueryResult(
            target_site=target_site,
            stats=[_stat("medium.com", 42), _stat("randomsite.com", 3)],
        )

    mocker.patch("backlink_publisher.referral.engine.handle_site", fake)


@pytest.fixture
def mock_handle_site_error(mocker):
    def fake(target_site, property_id, *, config, opts, existing=None):
        return ClickQueryResult(
            target_site=target_site,
            error_class="ga4_api_error",
            error_reason="GA4 API unavailable",
        )

    mocker.patch("backlink_publisher.referral.engine.handle_site", fake)


def _run_cli(argv: list[str]) -> None:
    from backlink_publisher.cli.referral_attribute import main

    main(argv)


def _count_store_events(db_path: Path, kind: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind = ?", (kind,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


class TestDryRun:
    def test_dry_run_outputs_jsonl(self, capsys):
        _run_cli(["--property", "123", "t1.example", "t2.example"])
        out, _ = capsys.readouterr()
        lines = [l for l in out.strip().split("\n") if l.startswith('{"type"')]
        assert len(lines) == 2
        for line in lines:
            assert json.loads(line)["type"] == "referral_attribution"

    def test_dry_run_no_store_writes(self, capsys, tmp_path):
        db_path = tmp_path / "events.db"
        _run_cli(["--property", "123", "--store-path", str(db_path), "t1.example"])
        capsys.readouterr()
        assert not db_path.exists()

    def test_no_targets_prints_usage(self, capsys):
        _run_cli(["--property", "123"])
        _, err = capsys.readouterr()
        assert "no targets specified" in err

    def test_non_positive_window_days_is_usage_error(self):
        with pytest.raises(SystemExit):
            _run_cli(["--property", "123", "--window-days", "0", "t.com"])

    def test_missing_property_is_usage_error(self):
        with pytest.raises(SystemExit):
            _run_cli(["t.com"])  # no --property, no config default


class TestProbeSuccess:
    def test_probe_emits_channel_jsonl(self, capsys, mock_handle_site_success):
        _run_cli(["--probe", "--property", "123", "t1.example"])
        out, _ = capsys.readouterr()
        rows = [
            json.loads(l)
            for l in out.strip().split("\n")
            if '"type": "referral_attribution"' in l
        ]
        assert len(rows) >= 1
        channels = {c["channel"]: c["sessions"] for c in rows[0]["channels"]}
        assert channels["medium"] == 42
        # unknown source kept, not dropped
        assert channels["unknown"] == 3

    def test_probe_writes_referral_events(
        self, capsys, mock_handle_site_success, tmp_path
    ):
        db_path = tmp_path / "events.db"
        _run_cli(
            ["--probe", "--property", "123", "--store-path", str(db_path), "t1.example"]
        )
        capsys.readouterr()
        assert db_path.exists()
        # two channels (medium + unknown) → two referral.observed events
        assert _count_store_events(db_path, "referral.observed") == 2


class TestProbeError:
    def test_probe_emits_error_row(self, capsys, mock_handle_site_error):
        _run_cli(["--probe", "--property", "123", "t1.example"])
        out, _ = capsys.readouterr()
        rows = [
            json.loads(l)
            for l in out.strip().split("\n")
            if '"type": "referral_attribution"' in l
        ]
        assert rows[0]["error_class"] == "ga4_api_error"

    def test_probe_error_writes_no_events(
        self, capsys, mock_handle_site_error, tmp_path
    ):
        db_path = tmp_path / "events.db"
        _run_cli(
            ["--probe", "--property", "123", "--store-path", str(db_path), "t1.example"]
        )
        capsys.readouterr()
        if db_path.exists():
            assert _count_store_events(db_path, "referral.observed") == 0
