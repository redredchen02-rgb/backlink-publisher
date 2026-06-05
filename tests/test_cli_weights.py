"""Tests for the consolidated ``weights`` CLI dispatcher (R2).

`weights` replaces the three former console scripts (collect-signals,
optimize-weights, show-optimization-state) with subcommands collect/optimize/
show, delegating to the underlying modules' ``main()`` (which keep their own
argparse, so ``--source``/``--rule`` choices and ``--help`` behave as before).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backlink_publisher.cli import weights

_MOD = "backlink_publisher.cli.weights"


def _run(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", _MOD, *args], capture_output=True, text=True, **kw
    )


class TestWeightsHelp:
    def test_top_level_help_lists_subcommands(self):
        r = _run("--help")
        assert r.returncode == 0
        for sub in ("collect", "optimize", "show"):
            assert sub in r.stdout

    @pytest.mark.parametrize("sub", ["collect", "optimize", "show"])
    def test_subcommand_help_exits_zero(self, sub: str):
        r = _run(sub, "--help")
        assert r.returncode == 0
        assert "usage:" in r.stdout


class TestWeightsCollect:
    def test_collect_dry_run_json_emits_raw_and_merged(self, tmp_path: Path):
        r = _run("collect", "--dry-run", "--json", env=_env(tmp_path))
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "raw" in data and "merged" in data

    def test_collect_bad_source_exits_2(self):
        # argparse choices= on the underlying module → exit 2
        r = _run("collect", "--source", "bogus")
        assert r.returncode == 2


class TestWeightsOptimize:
    def test_optimize_dry_run_json_emits_list(self, tmp_path: Path):
        r = _run("optimize", "--dry-run", "--json", env=_env(tmp_path))
        assert r.returncode == 0
        assert isinstance(json.loads(r.stdout), list)

    def test_optimize_rule_aggregated_stats_accepted(self, tmp_path: Path):
        # R3 added aggregated_stats to the --rule choices.
        r = _run("optimize", "--dry-run", "--rule", "aggregated_stats", env=_env(tmp_path))
        assert r.returncode == 0


class TestWeightsShow:
    def test_show_json_emits_platforms(self, tmp_path: Path):
        r = _run("show", "--json", env=_env(tmp_path))
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "platforms" in data


class TestWeightsDispatch:
    def test_unknown_subcommand_nonzero(self):
        r = _run("badsub")
        assert r.returncode != 0

    def test_missing_subcommand_nonzero(self):
        r = _run()
        assert r.returncode != 0

    def test_main_in_process_returns_int(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        rc = weights.main(["show", "--json"])
        assert rc == 0


def _env(tmp_path: Path) -> dict:
    import os

    return {**os.environ, "BACKLINK_PUBLISHER_CONFIG_DIR": str(tmp_path), "PYTHONPATH": "src"}
