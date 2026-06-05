"""Tests for the ``weights`` CLI dispatcher (plan 008 R2)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from backlink_publisher.cli.weights import main


class TestWeightsCLIDispatcher:
    def test_help_exit0(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "collect" in result.stdout
        assert "optimize" in result.stdout
        assert "show" in result.stdout

    def test_collect_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights", "collect", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout

    def test_optimize_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights", "optimize", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_show_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights", "show", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_collect_dry_run_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights",
             "collect", "--dry-run", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "raw" in data
        assert "merged" in data

    def test_optimize_dry_run_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights",
             "optimize", "--dry-run", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_show_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights", "show", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "platforms" in data

    def test_optimize_rule_aggregated_stats(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights",
             "optimize", "--dry-run", "--rule", "aggregated_stats"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_bad_subcommand_nonzero(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights", "badsub"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_collect_bad_source_exit2(self):
        result = subprocess.run(
            [sys.executable, "-m", "backlink_publisher.cli.weights",
             "collect", "--source", "bogus"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_main_returns_int(self):
        rc = main(["show", "--json"])
        assert rc == 0
