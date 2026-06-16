"""Tests for keepalive-status CLI (plan 2026-06-05-004 Unit 5)."""
from __future__ import annotations

__tier__ = "integration"


import json

import pytest

from backlink_publisher.cli.keepalive_status import _build_status
from backlink_publisher.keepalive.run_state import KeepaliveRunState
from backlink_publisher.optimization.state import OptimizationState


@pytest.fixture
def d(tmp_path):
    return tmp_path


# ── _build_status ──────────────────────────────────────────────────────────────


def test_no_state_file_returns_nulls(d):
    status = _build_status(data_dir=d)
    assert status["last_run_at"] is None
    assert status["last_cycle"] == {}
    assert status["platform_health"] == []
    assert status["exhausted_targets"] == []


def test_with_cycle_data_returns_correct_stats(d):
    rs = KeepaliveRunState(data_dir=d)
    rs.update_cycle_summary({
        "gaps_found": 3, "published": 2,
        "reverified_alive": 1, "reverified_dead": 1, "exhausted_skipped": 0
    })
    status = _build_status(data_dir=d)
    assert status["last_run_at"] is not None
    assert status["last_cycle"]["gaps_found"] == 3
    assert status["last_cycle"]["published"] == 2


def test_platform_health_circuit_broken_badge(d):
    opt = OptimizationState(data_dir=d)
    opt.set_weight("blogger", 0.0, rule="test", reason="circuit break test for status badge display")
    status = _build_status(data_dir=d)
    blogger = next((h for h in status["platform_health"] if h["platform"] == "blogger"), None)
    assert blogger is not None
    assert blogger["circuit_broken"] is True


def test_platform_health_normal_weight(d):
    opt = OptimizationState(data_dir=d)
    opt.set_weight("blogger", 1.2, rule="test", reason="boosted weight for status display test")
    status = _build_status(data_dir=d)
    blogger = next(h for h in status["platform_health"] if h["platform"] == "blogger")
    assert not blogger["circuit_broken"]
    assert blogger["weight"] == pytest.approx(1.2, abs=0.01)


def test_exhausted_target_listed(d):
    rs = KeepaliveRunState(data_dir=d)
    for _ in range(3):
        rs.record_attempt("https://dead.example.com/page", "blogger", "reverify_dead")
    status = _build_status(data_dir=d)
    assert len(status["exhausted_targets"]) == 1
    assert status["exhausted_targets"][0]["url"] == "https://dead.example.com/page"
    assert status["exhausted_targets"][0]["attempts"] == 3


def test_non_exhausted_not_listed(d):
    rs = KeepaliveRunState(data_dir=d)
    rs.record_attempt("https://partial.example.com/page", "blogger", "reverify_dead")
    status = _build_status(data_dir=d)
    assert len(status["exhausted_targets"]) == 0


# ── CLI output tests ───────────────────────────────────────────────────────────


def test_no_state_shows_no_cycle_message(d, monkeypatch, capsys):
    monkeypatch.setattr(
        "backlink_publisher.cli.keepalive_status._build_status",
        lambda: _build_status(data_dir=d),
    )
    from backlink_publisher.cli.keepalive_status import main
    main([])
    captured = capsys.readouterr()
    assert "No keepalive cycle has run yet" in captured.out


def test_json_output_valid(d, monkeypatch, capsys):
    rs = KeepaliveRunState(data_dir=d)
    rs.update_cycle_summary({"gaps_found": 1, "published": 1})
    monkeypatch.setattr(
        "backlink_publisher.cli.keepalive_status._build_status",
        lambda: _build_status(data_dir=d),
    )
    from backlink_publisher.cli.keepalive_status import main
    main(["--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "last_run_at" in data
    assert "last_cycle" in data
    assert "platform_health" in data
    assert "exhausted_targets" in data


def test_reset_exhausted_removes_entry(d, monkeypatch, capsys):
    rs = KeepaliveRunState(data_dir=d)
    for _ in range(3):
        rs.record_attempt("https://ex.example.com/pg", "blogger", "reverify_dead")
    assert rs.is_exhausted("https://ex.example.com/pg")

    monkeypatch.setattr(
        "backlink_publisher.cli.keepalive_status._build_status",
        lambda: _build_status(data_dir=d),
    )
    # Patch KeepaliveRunState() in keepalive_status to use our tmp dir
    from backlink_publisher.keepalive import run_state as _rs_mod
    original_init = KeepaliveRunState.__init__

    def _patched_init(self, data_dir=None):
        original_init(self, data_dir=d)  # always use test dir

    monkeypatch.setattr(KeepaliveRunState, "__init__", _patched_init)

    from backlink_publisher.cli.keepalive_status import main
    main(["--reset-exhausted", "https://ex.example.com/pg"])

    rs2 = KeepaliveRunState(data_dir=d)
    assert not rs2.is_exhausted("https://ex.example.com/pg")
