"""Tests for platform-health CLI — Plan 2026-06-03-004 Unit 3."""
from __future__ import annotations

__tier__ = "unit"
import json

import pytest

from backlink_publisher.cli.platform_health import main
from backlink_publisher.health.aggregate import PlatformHealthRecord


def _make_record(platform: str, **kwargs) -> PlatformHealthRecord:
    return PlatformHealthRecord(
        platform=platform,
        last_success_at=kwargs.get("last_success_at"),
        last_failure_at=kwargs.get("last_failure_at"),
        last_error_msg=kwargs.get("last_error_msg"),
        consecutive_failures=kwargs.get("consecutive_failures", 0),
        circuit_tripped=kwargs.get("circuit_tripped", False),
        paused=kwargs.get("paused", False),
    )


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.config import load_config
    return load_config()


@pytest.fixture
def two_platforms(monkeypatch):
    records = {
        "medium": _make_record("medium", last_success_at="2026-06-03T10:00:00+00:00",
                               consecutive_failures=0),
        "blogger": _make_record("blogger", last_failure_at="2026-06-02T08:00:00+00:00",
                                consecutive_failures=3, circuit_tripped=True),
    }
    monkeypatch.setattr(
        "backlink_publisher.cli.platform_health.build_platform_health",
        lambda cfg: records,
    )
    return records


def test_table_output_has_two_rows(two_platforms, cfg, monkeypatch, capsys):
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", lambda: cfg)
    main([])
    out = capsys.readouterr().out
    assert "medium" in out
    assert "blogger" in out


def test_json_flag_emits_valid_jsonl(two_platforms, cfg, monkeypatch, capsys):
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", lambda: cfg)
    main(["--json"])
    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l]
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "platform" in obj
        assert "circuit_tripped" in obj


def test_platform_filter(two_platforms, cfg, monkeypatch, capsys):
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", lambda: cfg)
    main(["--platform", "medium"])
    out = capsys.readouterr().out
    assert "medium" in out
    assert "blogger" not in out


def test_unknown_platform_filter_prints_nothing_to_stdout(two_platforms, cfg, monkeypatch, capsys):
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", lambda: cfg)
    main(["--platform", "nonexistent"])
    out = capsys.readouterr().out
    # Table header may still appear but no data rows for nonexistent platform
    assert "nonexistent" not in out


def test_config_error_exits_1(monkeypatch):
    def _fail():
        raise RuntimeError("no config")
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", _fail)
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 1


def test_circuit_open_shown_in_table(two_platforms, cfg, monkeypatch, capsys):
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", lambda: cfg)
    main([])
    out = capsys.readouterr().out
    assert "OPEN" in out


def test_json_platform_filter(two_platforms, cfg, monkeypatch, capsys):
    monkeypatch.setattr("backlink_publisher.cli.platform_health.load_config", lambda: cfg)
    main(["--json", "--platform", "blogger"])
    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["platform"] == "blogger"
