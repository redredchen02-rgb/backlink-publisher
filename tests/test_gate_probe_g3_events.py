"""g3 gate consumes in-product referral.observed events (Plan 2026-06-15-004 U4)."""
from __future__ import annotations

__tier__ = "integration"
import json

import pytest

from backlink_publisher.cli import gate_probe
from backlink_publisher.events import EventStore
from backlink_publisher.referral.store import append_referral_observed


def _verdict(capsys):
    out, _ = capsys.readouterr()
    rows = [json.loads(l) for l in out.strip().split("\n") if l.startswith("{")]
    return rows[0]


def _store_with_referral(tmp_path, sessions):
    store = EventStore(path=tmp_path / "events.db")
    append_referral_observed(
        store,
        target_site="site.com",
        channel="medium",
        sessions=sessions,
        window_start="2026-06-01",
        window_end="2026-06-08",
    )
    return store


def test_g3_reads_events_referral_go(capsys, mocker, tmp_path):
    """Referral sessions in events.db → GO without --referral-sessions."""
    store = _store_with_referral(tmp_path, 12)
    mocker.patch("backlink_publisher.events.EventStore", return_value=store)
    gate_probe.main(["--gate", "g3", "--strip-threshold", "0.9"])
    assert _verdict(capsys)["verdict"] == "GO"


def test_g3_zero_sessions_kills(capsys, mocker, tmp_path):
    """A referral event with zero sessions → KILL (assess_g3 invariant)."""
    store = _store_with_referral(tmp_path, 0)
    mocker.patch("backlink_publisher.events.EventStore", return_value=store)
    gate_probe.main(["--gate", "g3", "--strip-threshold", "0.9"])
    assert _verdict(capsys)["verdict"] == "KILL"


def test_g3_no_events_stays_inconclusive(capsys, mocker, tmp_path):
    """Empty events.db → no referral evidence → INCONCLUSIVE (original semantics)."""
    store = EventStore(path=tmp_path / "events.db")
    mocker.patch("backlink_publisher.events.EventStore", return_value=store)
    gate_probe.main(["--gate", "g3", "--strip-threshold", "0.9"])
    assert _verdict(capsys)["verdict"] == "INCONCLUSIVE"


def test_g3_manual_override_wins(capsys, mocker, tmp_path):
    """--referral-sessions still overrides the events.db source (back-compat)."""
    store = _store_with_referral(tmp_path, 0)  # events say zero
    mocker.patch("backlink_publisher.events.EventStore", return_value=store)
    gate_probe.main(
        [
            "--gate", "g3", "--strip-threshold", "0.9",
            "--referral-sessions", "5", "--referral-window", "2026-06",
        ]
    )
    # operator-supplied 5 > 0 → GO despite events showing zero
    assert _verdict(capsys)["verdict"] == "GO"
