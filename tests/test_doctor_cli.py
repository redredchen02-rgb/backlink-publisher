"""F1 (plan 2026-07-13-004): backlink-doctor preflight.

Pure classification core is unit-tested here; ``main`` wiring is smoke-tested
for exit code + JSON shape.
"""

from __future__ import annotations

import json

import pytest

from backlink_publisher.cli.admin.doctor import build_report


def _view() -> list[dict]:
    return [
        {"platform": "rentry", "dofollow": True, "auth_type": "anon"},
        {"platform": "telegraph", "dofollow": True, "auth_type": "anon"},
        {"platform": "blogger", "dofollow": True, "auth_type": "oauth"},
        {"platform": "ghpages", "dofollow": True, "auth_type": "token"},
        {"platform": "txtfyi", "dofollow": "uncertain", "auth_type": "anon"},
        {"platform": "devto", "dofollow": False, "auth_type": "token"},
    ]


def test_report_surfaces_anon_dofollow_as_ready_now():
    report = build_report(_view())
    assert "rentry" in report["ready_now"]
    assert "telegraph" in report["ready_now"]
    assert "blogger" not in report["ready_now"]


def test_report_classifies_high_value_gaps_and_uncertain_anon():
    report = build_report(_view())
    assert set(report["high_value_gaps"]) == {"blogger", "ghpages"}
    assert report["uncertain_anon"] == ["txtfyi"]  # canary-flip candidate
    assert "devto" not in report["high_value_gaps"]  # nofollow, not a dofollow gap


def test_shortest_path_names_a_zero_credential_platform():
    report = build_report(_view())
    assert "rentry" in report["shortest_path"]
    assert "no account" in report["shortest_path"].lower()


def test_shortest_path_when_no_anon_dofollow():
    report = build_report([{"platform": "blogger", "dofollow": True, "auth_type": "oauth"}])
    assert report["ready_now"] == []
    assert "bind" in report["shortest_path"].lower()


def test_main_exits_zero_and_emits_json(capsys):
    import backlink_publisher.cli.admin.doctor as doctor
    with pytest.raises(SystemExit) as exc:
        doctor.main(["--json"])
    assert exc.value.code == 0
    out = capsys.readouterr().out.strip().splitlines()
    payload = json.loads(out[-1])
    assert "ready_now" in payload and "shortest_path" in payload
