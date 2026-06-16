"""Tests for show-optimization-state CLI (U5).
"""

from __future__ import annotations

__tier__ = "integration"


import json
import subprocess
import sys
from pathlib import Path

import pytest

from backlink_publisher.optimization import OptimizationState


class TestShowOptimizationStateCLI:
    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout

    def test_empty_state(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "No platform data" in result.stdout

    def test_json_empty(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "platforms" in data

    def test_with_platform_data(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("blogger", 0.5, rule="canary_drift", reason="drift test")
        state.update_stats("blogger", {"alive_count": 5, "total_published": 10})

        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "blogger" in result.stdout
        assert "0.5" in result.stdout

    def test_with_platform_data_json(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("velog", 0.3, rule="canary_drift", reason="drift test")

        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["platforms"]) == 1
        assert data["platforms"][0]["name"] == "velog"
        assert data["platforms"][0]["current"] == 0.3

    def test_platform_filter(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        state = OptimizationState()
        state.set_weight("blogger", 0.5, rule="canary_drift", reason="drift")
        state.set_weight("velog", 0.8, rule="canary_drift", reason="drift")

        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.show_optimization_state",
             "--platform", "blogger"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "blogger" in result.stdout
        assert "velog" not in result.stdout
