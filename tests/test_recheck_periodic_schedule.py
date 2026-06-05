"""R4: the recheck launchd agent runs weekly (calendar) and probes all due links.

Reads the plist + wrapper script as files (no live launchctl) and asserts the
weekly cadence + read-only probe + widened cap, mirroring the in-repo calendar
scheduling convention (com.dex.bp-full-pipeline.plist).
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PLIST = _REPO / "scripts" / "com.dex.bp-recheck.plist"
_SCRIPT = _REPO / "scripts" / "run-recheck-periodic.sh"


@pytest.fixture(scope="module")
def plist() -> dict:
    with _PLIST.open("rb") as fh:
        return plistlib.load(fh)


def test_weekly_calendar_interval_not_daily(plist):
    # Daily StartInterval is gone; weekly StartCalendarInterval drives it.
    assert "StartInterval" not in plist
    cal = plist["StartCalendarInterval"]
    assert "Weekday" in cal  # weekly cadence
    assert isinstance(cal.get("Hour"), int)
    assert isinstance(cal.get("Minute"), int)


def test_program_args_probe_readonly(plist):
    args = plist["ProgramArguments"]
    assert "--probe" in args  # live re-verification (read-only)
    assert args[-2].endswith("run-recheck-periodic.sh") or any(
        a.endswith("run-recheck-periodic.sh") for a in args
    )


def test_env_is_path_only_credential_free(plist):
    # Recheck is credential-free: the plist injects PATH only (no publish creds).
    env = plist.get("EnvironmentVariables", {})
    assert set(env.keys()) <= {"PATH"}


def test_wrapper_passes_probe_and_widened_limit():
    body = _SCRIPT.read_text(encoding="utf-8")
    assert "--probe" in body
    assert "--limit" in body  # widened cap for all-due-links sweep
    assert "RECHECK_LIMIT" in body  # tunable override
