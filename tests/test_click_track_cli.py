"""Integration tests for the click-track CLI verb (Plan 2026-06-02-001).

Covers:
* Dry-run: zero GA4 calls, zero store writes, JSONL output.
* --probe with query success → store has ``click.observed`` events.
* --probe with query error → store has ``click.query_failed`` events.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backlink_publisher.click_track.engine import (
    ClickQueryResult,
    ClickStats,
)


# ── fixture: mock handle_site ─────────────────────────────────────────────


@pytest.fixture
def mock_handle_site_success(mocker):
    """Patch handle_site to return a successful result with one stat row."""

    def fake(target_site, property_id, *, config, opts, existing=None):
        return ClickQueryResult(
            target_site=target_site,
            stats=[
                ClickStats(
                    target_site=target_site,
                    source_domain="medium.com",
                    sessions=42,
                    users=12,
                    pageviews=156,
                    window_start="2026-05-01",
                    window_end="2026-05-08",
                ),
            ],
        )

    mocker.patch(
        "backlink_publisher.cli.click_track.handle_site",
        fake,
    )


@pytest.fixture
def mock_handle_site_error(mocker):
    """Patch handle_site to return an error result."""

    def fake(target_site, property_id, *, config, opts, existing=None):
        return ClickQueryResult(
            target_site=target_site,
            error_class="ga4_api_error",
            error_reason="GA4 API unavailable",
        )

    mocker.patch(
        "backlink_publisher.cli.click_track.handle_site",
        fake,
    )


# ── helpers ────────────────────────────────────────────────────────────────


def _run_cli(argv: list[str]) -> None:
    """Run ``click-track`` with the given argv (calls main directly)."""
    from backlink_publisher.cli.click_track import main

    main(argv)


def _count_store_events(db_path: Path, kind: str) -> int:
    """Return number of events of *kind* in the store."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind = ?", (kind,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


# ── tests ──────────────────────────────────────────────────────────────────


class TestDryRun:
    """Default mode (no --probe flag)."""

    def test_dry_run_outputs_jsonl(self, capsys, monkeypatch):
        """Two targets → two JSONL rows, error_class is None."""
        _run_cli(["--property", "123", "t1.example", "t2.example"])
        out, _ = capsys.readouterr()
        lines = [
            l for l in out.strip().split("\n") if l and l.startswith('{"type"')
        ]
        assert len(lines) == 2
        for line in lines:
            row = json.loads(line)
            assert row["type"] == "click_query"
            assert row["error_class"] is None

    def test_dry_run_no_store_writes(self, capsys, monkeypatch, tmp_path):
        """Dry-run creates no events.db."""
        db_path = tmp_path / "events.db"
        _run_cli(["--property", "123", "--store-path", str(db_path), "t1.example"])
        capsys.readouterr()  # drain
        assert not db_path.exists(), "store should not be created in dry-run"

    def test_no_targets_prints_usage(self, capsys, monkeypatch):
        """No positional args → stderr message, no JSONL output."""
        _run_cli(["--property", "123"])
        out, err = capsys.readouterr()
        assert "no targets specified" in err


class TestProbeSuccess:
    """--probe with a successful query."""

    def test_probe_emits_jsonl(self, capsys, monkeypatch, mock_handle_site_success):
        _run_cli(["--probe", "--property", "123", "t1.example"])
        out, _ = capsys.readouterr()
        data_lines = [
            l
            for l in out.strip().split("\n")
            if l and '"type": "click_query"' in l
        ]
        assert len(data_lines) >= 1
        row = json.loads(data_lines[0])
        assert row["target_site"] == "t1.example"
        assert row["error_class"] is None
        assert len(row["stats"]) == 1
        assert row["stats"][0]["source_domain"] == "medium.com"
        assert row["stats"][0]["sessions"] == 42

    def test_probe_writes_observed_event(
        self, capsys, monkeypatch, mock_handle_site_success, tmp_path
    ):
        db_path = tmp_path / "events.db"
        _run_cli(
            [
                "--probe",
                "--property",
                "123",
                "--store-path",
                str(db_path),
                "t1.example",
            ],
        )
        capsys.readouterr()  # drain
        assert db_path.exists()
        assert _count_store_events(db_path, "click.observed") == 1
        assert _count_store_events(db_path, "click.query_failed") == 0


class TestProbeError:
    """--probe when the query fails."""

    def test_probe_emits_error_row(
        self, capsys, monkeypatch, mock_handle_site_error
    ):
        _run_cli(["--probe", "--property", "123", "t1.example"])
        out, _ = capsys.readouterr()
        data_lines = [
            l
            for l in out.strip().split("\n")
            if l and '"type": "click_query"' in l
        ]
        assert len(data_lines) >= 1
        row = json.loads(data_lines[0])
        assert row["error_class"] == "ga4_api_error"
        assert row["error_reason"] == "GA4 API unavailable"

    def test_probe_writes_failed_event(
        self, capsys, monkeypatch, mock_handle_site_error, tmp_path
    ):
        db_path = tmp_path / "events.db"
        _run_cli(
            [
                "--probe",
                "--property",
                "123",
                "--store-path",
                str(db_path),
                "t1.example",
            ],
        )
        capsys.readouterr()  # drain
        assert db_path.exists()
        assert _count_store_events(db_path, "click.query_failed") == 1
        assert _count_store_events(db_path, "click.observed") == 0
