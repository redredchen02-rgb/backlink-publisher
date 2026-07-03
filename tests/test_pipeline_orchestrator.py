"""Tests for backlink_publisher.cli.pipeline_orchestrator (Plan U2.1 + U2.3)."""


from __future__ import annotations
__tier__ = "integration"

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from backlink_publisher.cli.pipeline_orchestrator import (
    _read_scheduler_state,
    _run_pipe_step,
    _run_step,
    _write_scheduler_state,
    build_parser,
    PipelineConfig,
    PipelineResult,
    should_run_now,
    StepResult,
)


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class TestSubprocessUtf8Encoding:
    """_run_step / _run_pipe_step must force UTF-8 text I/O on both sides of
    the pipe so a Windows non-UTF-8 locale doesn't crash the child."""

    def test_run_step_passes_utf8_encoding_and_pythonioencoding_env(self) -> None:
        fake = _FakeCompleted(stdout="ok\n")
        with patch("subprocess.run", return_value=fake) as mock_run:
            _run_step(["echo", "hi"], "some-step")

        _args, kwargs = mock_run.call_args
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"

    def test_run_pipe_step_passes_utf8_encoding_and_pythonioencoding_env(self) -> None:
        fake = _FakeCompleted(stdout="ok\n")
        with patch("subprocess.run", return_value=fake) as mock_run:
            _run_pipe_step(["echo", "hi"], "input\n", "some-step")

        _args, kwargs = mock_run.call_args
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"


class TestStepResult:
    def test_defaults(self) -> None:
        sr = StepResult(name="test-step")
        assert sr.name == "test-step"
        assert sr.success is False
        assert sr.fatal is False
        assert sr.duration_s == 0.0
        assert sr.exit_code == 0

    def test_full_construction(self) -> None:
        sr = StepResult(name="pub", success=True, fatal=False, duration_s=12.5, exit_code=0)
        assert sr.name == "pub"
        assert sr.success is True
        assert sr.exit_code == 0


class TestPipelineResult:
    def test_defaults(self) -> None:
        pr = PipelineResult(started_at="2026-01-01T00:00:00")
        assert pr.result == "unknown"
        assert pr.steps == []

    def test_to_dict(self) -> None:
        pr = PipelineResult(started_at="2026-06-10T00:00:00")
        pr.steps.append(StepResult(name="step1", success=True, fatal=False, duration_s=1.0, exit_code=0))
        pr.result = "success"
        pr.completed_at = "2026-06-10T01:00:00"
        d = pr.to_dict()
        assert d["result"] == "success"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["name"] == "step1"
        assert d["steps"][0]["duration_s"] == 1.0


class TestPipelineConfig:
    def test_from_env_defaults(self) -> None:
        # Ensure env vars are clean
        for k in ("BP_LANG", "BP_DESIRED", "BP_URL_MODE", "BP_PUBLISH_MODE",
                  "BP_PLATFORM", "BP_OPTIMIZE", "BP_DRY_RUN", "BP_MAX_ROWS"):
            os.environ.pop(k, None)
        cfg = PipelineConfig.from_env()
        assert cfg.lang == "zh-CN"
        assert cfg.desired == 3
        assert cfg.url_mode == "A"
        assert cfg.dry_run is False
        assert cfg.optimize is True

    def test_from_env_overrides(self) -> None:
        os.environ["BP_LANG"] = "en"
        os.environ["BP_DESIRED"] = "5"
        os.environ["BP_DRY_RUN"] = "1"
        os.environ["BP_OPTIMIZE"] = "0"
        try:
            cfg = PipelineConfig.from_env()
            assert cfg.lang == "en"
            assert cfg.desired == 5
            assert cfg.dry_run is True
            assert cfg.optimize is False
        finally:
            for k in ("BP_LANG", "BP_DESIRED", "BP_DRY_RUN", "BP_OPTIMIZE"):
                os.environ.pop(k, None)


class TestBuildParser:
    def test_default_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.check is False
        assert args.step is None
        assert args.dry_run is False

    def test_check_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--check"])
        assert args.check is True

    def test_step_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--step", "equity-ledger,plan-gap"])
        assert args.step == "equity-ledger,plan-gap"

    def test_dry_run_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True


class TestShouldRun:
    def test_no_gaps_with_mock(self, monkeypatch) -> None:
        """When equity-ledger returns no output, should_run_now skips."""
        from backlink_publisher.cli import pipeline_orchestrator as po

        def mock_gaps(cfg):
            return 0
        monkeypatch.setattr(po, "_count_gaps", mock_gaps)
        cfg = PipelineConfig(dry_run=True)
        should, reason = should_run_now(cfg)
        assert should is False
        assert "gap" in reason.lower()

    def test_scheduler_state_rw(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state_file = Path(td) / ".scheduler-state.json"
            # Temporarily redirect SCHEDULER_STATE_FILE
            import backlink_publisher.cli.pipeline_orchestrator as po
            original = po.SCHEDULER_STATE_FILE
            try:
                po.SCHEDULER_STATE_FILE = state_file
                _write_scheduler_state({"last_run_ts": 1234567890, "last_run_at": "2026-01-01T00:00:00"})
                assert state_file.exists()
                loaded = _read_scheduler_state()
                assert loaded["last_run_ts"] == 1234567890
            finally:
                po.SCHEDULER_STATE_FILE = original


class TestStepConstants:
    """STEPS_GAP / STEPS_ALL maintain expected ordering."""

    def test_steps_gap_order(self) -> None:
        from backlink_publisher.cli.pipeline_orchestrator import STEPS_GAP
        assert STEPS_GAP == [
            "equity-ledger",
            "plan-gap",
            "plan-backlinks",
            "validate-backlinks",
            "publish-backlinks",
        ]

    def test_steps_all_order(self) -> None:
        from backlink_publisher.cli.pipeline_orchestrator import STEPS_ALL
        # STEPS_ALL extends STEPS_GAP with recheck + optimize
        assert STEPS_ALL[:5] == [
            "equity-ledger",
            "plan-gap",
            "plan-backlinks",
            "validate-backlinks",
            "publish-backlinks",
        ]
        assert STEPS_ALL[5:] == ["recheck-backlinks", "optimize-weights"]
