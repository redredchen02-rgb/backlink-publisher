"""Per-row publish timing telemetry (Plan 2026-07-09-001 C2 measurement gate).

``_run_publish_loop`` must emit one ``row_timing`` diagnostic per row plus a
``row_timing_summary`` aggregate — the evidence base for the parallel-publish
(H1) decision. Diagnostics-only: stdout JSONL is untouched by these lines.
"""
from __future__ import annotations

__tier__ = "unit"

from types import SimpleNamespace
from unittest.mock import patch

from backlink_publisher.cli.publish_backlinks import _engine


def _run(rows, one_row_result=None):
    """Drive _run_publish_loop with _publish_one_row stubbed; capture logger."""
    calls: list[tuple[str, dict]] = []

    class _FakeLog:
        def info(self, msg, **extra):
            calls.append((msg, extra))

    state = SimpleNamespace(
        auth_aborted=False, dependency_aborted=False, conflict_aborted=False,
    )
    with patch.object(_engine, "_publish_one_row", return_value=one_row_result), patch(
        "backlink_publisher._util.logger.publish_logger", _FakeLog()
    ):
        _engine.run_publish_loop(
            rows, args=SimpleNamespace(), config=None, state=state, ts="t",
            banner_emit=lambda *a, **k: None, forced_keys=set(),
            throttle_min=0, throttle_max=0, initial_token_revs={},
        )
    return calls, state


def test_emits_one_row_timing_per_row_plus_summary():
    rows = [{"platform": "blogger"}, {"platform": "medium"}]
    calls, _ = _run(rows)
    row_lines = [e for m, e in calls if m == "row_timing"]
    summaries = [e for m, e in calls if m == "row_timing_summary"]
    assert len(row_lines) == 2
    assert row_lines[0]["row"] == 0 and row_lines[0]["platform"] == "blogger"
    assert row_lines[1]["row"] == 1 and row_lines[1]["platform"] == "medium"
    assert all(e["elapsed_s"] >= 0 for e in row_lines)
    assert len(summaries) == 1
    s = summaries[0]
    assert s["n_rows"] == 2
    assert s["total_s"] >= 0 and s["max_s"] >= s["mean_s"] >= 0


def test_summary_still_emitted_on_abort():
    rows = [{"platform": "blogger"}, {"platform": "medium"}]
    calls, state = _run(rows, one_row_result=_engine._AUTH_ABORT)
    assert state.auth_aborted is True
    row_lines = [e for m, e in calls if m == "row_timing"]
    summaries = [e for m, e in calls if m == "row_timing_summary"]
    assert len(row_lines) == 1  # aborted after the first row
    assert len(summaries) == 1
    assert summaries[0]["n_rows"] == 1


def test_empty_rows_emit_no_summary():
    calls, _ = _run([])
    assert calls == []
