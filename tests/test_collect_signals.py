"""Tests for Signal Collector (U2 — collect-signals).

Covers:
  - offline fallback (no data sources reachable)
  - collector merges empty sources gracefully
  - ``--dry-run`` does NOT write to state
  - ``--source`` filter selects a single source
"""

from __future__ import annotations

__tier__ = "integration"


import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from backlink_publisher.optimization import OptimizationState
from backlink_publisher.optimization.collector import (
    _merge_signals,
    collect_all_signals,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(tmp_path: Path) -> OptimizationState:
    """Return an OptimizationState that writes to *tmp_path*."""
    return OptimizationState(data_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# _merge_signals  — unit-level
# ---------------------------------------------------------------------------


class TestMergeSignals:
    def test_merge_empty(self):
        merged = _merge_signals({})
        assert merged == {}

    def test_merge_recheck_only(self):
        signals = {
            "recheck": {
                "platforms": {
                    "blogger": {"alive_count": 5, "dofollow_count": 3, "total_published": 10},
                },
            },
            "canary": {"status": "unavailable"},
            "equity": {"status": "unavailable"},
        }
        merged = _merge_signals(signals)
        assert merged["blogger"]["alive_count"] == 5
        assert merged["blogger"]["dofollow_count"] == 3
        assert merged["blogger"]["total_published"] == 10

    def test_merge_canary_drift_added(self):
        signals = {
            "recheck": {
                "platforms": {
                    "velog": {"alive_count": 8, "dofollow_count": 8, "total_published": 8},
                },
            },
            "canary": {
                "platforms": {
                    "velog": {"drift_count": 2},
                },
            },
            "equity": {"status": "unavailable"},
        }
        merged = _merge_signals(signals)
        assert merged["velog"]["drift_count"] == 2
        assert merged["velog"]["alive_count"] == 8

    def test_merge_equity_enriches(self):
        signals = {
            "recheck": {"status": "unavailable"},
            "canary": {"status": "unavailable"},
            "equity": {
                "platforms": {
                    "medium": {"alive_count": 3, "dofollow_count": 1, "total_published": 5},
                },
            },
        }
        merged = _merge_signals(signals)
        assert merged["medium"]["alive_count"] == 3
        assert merged["medium"]["total_published"] == 5


# ---------------------------------------------------------------------------
# collect_all_signals  — integration-like (offline, no real CLI calls)
# ---------------------------------------------------------------------------


class TestCollectAllSignals:
    def test_collect_offline_dry_run(self, tmp_path):
        """When no CLI is reachable, signals should be empty but not crash."""
        state = _make_state(tmp_path)

        with patch(
            "backlink_publisher.optimization.collector._try_cli_collect",
            return_value=None,
        ):
            with patch(
                "backlink_publisher.optimization.collector._resolve_config_dir",
                return_value=tmp_path,
            ):
                result = collect_all_signals(state, dry_run=True)

        assert "raw" in result
        assert "merged" in result
        # Nothing should be written to state on dry_run
        assert not (tmp_path / "optimization_state.json").exists()

    def test_collect_offline_writes_nothing(self, tmp_path):
        """When offline with no previous state, nothing should be written."""
        state = _make_state(tmp_path)

        with patch(
            "backlink_publisher.optimization.collector._try_cli_collect",
            return_value=None,
        ):
            with patch(
                "backlink_publisher.optimization.collector._resolve_config_dir",
                return_value=tmp_path,
            ):
                result = collect_all_signals(state, dry_run=False)

        assert "merged" in result
        # Without any platforms, merged is empty => nothing to write
        assert not (tmp_path / "optimization_state.json").exists()

    def test_source_filter_recheck_only(self, tmp_path):
        """--source recheck should skip canary and equity."""
        state = _make_state(tmp_path)

        with patch(
            "backlink_publisher.optimization.collector._try_cli_collect",
            return_value=None,
        ) as mock_cli:
            with patch(
                "backlink_publisher.optimization.collector._resolve_config_dir",
                return_value=tmp_path,
            ):
                result = collect_all_signals(state, dry_run=True, source_filter="recheck")

        raw = result["raw"]
        assert "recheck" in raw
        assert raw["canary"]["status"] == "skipped"
        assert raw["equity"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# CLI end-to-end  (via subprocess, same pattern as existing test_cli_*)
# ---------------------------------------------------------------------------


class TestCollectSignalsCLI:
    def test_help(self):
        """--help should print usage and exit 0."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.collect_signals", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout

    def test_dry_run_no_crash(self):
        """--dry-run should run without error even when offline."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.collect_signals", "--dry-run"],
            capture_output=True,
            text=True,
        )
        # Should not crash
        assert result.returncode == 0

    def test_json_output(self):
        """--json should print valid JSON to stdout."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.collect_signals", "--dry-run", "--json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "raw" in data
        assert "merged" in data

    def test_source_recheck(self):
        """--source recheck should work."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.collect_signals",
             "--dry-run", "--source", "recheck"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
