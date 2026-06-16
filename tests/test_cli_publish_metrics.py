"""publish-metrics CLI verb — per-channel success rate + recheck coverage (JSONL).

Fresh config/cache dir per test so the session sandbox doesn't bleed state.
"""
__tier__ = "unit"

import io
import json
import sys

import pytest

from backlink_publisher.cli.publish_metrics import main
from backlink_publisher.events import EventStore, kinds


@pytest.fixture(autouse=True)
def fresh_dirs(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache))


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    code = 0
    try:
        main(argv)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            code = exc.code
        elif exc.code is None:
            code = 0
        else:
            err.write(str(exc.code))
            code = 1
    finally:
        sys.stdout, sys.stderr = saved
    return out.getvalue(), err.getvalue(), code


def _parse(out):
    return [json.loads(ln) for ln in out.splitlines() if ln.strip()]


def _emit(kind, platform, *, live_url=None):
    payload = {"platform": platform}
    if kind in (kinds.PUBLISH_CONFIRMED, kinds.PUBLISH_UNVERIFIED):
        payload["live_url"] = live_url
    else:
        payload.update(error_class="ExternalServiceError", error_message_clean="x")
    EventStore().append(kind, payload)


def test_empty_store_emits_only_summary():
    out, err, code = _run([])
    assert code == 0
    rows = _parse(out)
    assert rows[-1]["_summary"]["overall_attempts"] == 0
    assert rows[-1]["_summary"]["overall_coverage_pct"] is None


def test_per_channel_success_and_summary():
    _emit(kinds.PUBLISH_CONFIRMED, "medium", live_url="https://medium.com/a")
    _emit(kinds.PUBLISH_FAILED, "medium")
    out, err, code = _run([])
    assert code == 0
    rows = _parse(out)
    medium = next(r for r in rows if r.get("channel") == "medium")
    assert medium["attempts"] == 2
    assert medium["successes"] == 1
    assert medium["success_pct"] == 0.5
    summary = rows[-1]["_summary"]
    assert summary["overall_attempts"] == 2
    assert summary["coverage_target_pct"] == 0.5


def test_config_banner_on_stderr_data_on_stdout():
    _emit(kinds.PUBLISH_CONFIRMED, "velog", live_url="https://velog.io/x")
    out, err, code = _run([])
    assert code == 0
    # stdout is clean JSONL; the banner is on stderr.
    for ln in out.splitlines():
        if ln.strip():
            json.loads(ln)  # raises if stdout is polluted
    assert err  # banner present


def test_invalid_window_days_exit_1():
    _out, _err, code = _run(["--window-days", "0"])
    assert code == 1


# ── coverage-freshness alarm (Plan 2026-06-15-007 U1) ─────────────────────────

def _published_link(platform, live_url, target="https://example.com"):
    """A published backlink with no recheck → counts as uncovered (0% fresh).

    Coverage derives from the ``articles`` ledger (build_target_buckets), not raw
    publish events, so the link must be an article row.
    """
    EventStore().add_article(
        {"live_url": live_url, "platform": platform,
         "target_urls_json": json.dumps([target])}
    )


def test_alarm_exits_6_when_below_target():
    _published_link("medium", "https://medium.com/a")  # 0% within-window coverage
    out, err, code = _run(["--alarm"])
    assert code == 6
    # Data is still emitted on stdout; the alarm is the exit code + stderr envelope.
    assert _parse(out)[-1]["_summary"]["overall_coverage_pct"] == 0.0
    assert "below target" in err


def test_no_alarm_flag_stays_advisory_exit_0():
    _published_link("medium", "https://medium.com/a")
    _out, _err, code = _run([])  # default: advisory, no alarm
    assert code == 0


def test_alarm_empty_ledger_no_false_alarm():
    _out, _err, code = _run(["--alarm"])  # no links → coverage None → no alarm
    assert code == 0


def test_alarm_threshold_override_stricter_trips():
    _published_link("medium", "https://medium.com/a")
    _out, _err, code = _run(["--alarm", "--coverage-fail-under", "0.9"])
    assert code == 6


def test_alarm_threshold_override_lenient_passes():
    _published_link("medium", "https://medium.com/a")
    # 0% coverage is NOT below a 0.0 threshold → no alarm (boundary).
    _out, _err, code = _run(["--alarm", "--coverage-fail-under", "0.0"])
    assert code == 0


def test_invalid_coverage_fail_under_exit_1():
    _out, _err, code = _run(["--coverage-fail-under", "1.5"])
    assert code == 1
