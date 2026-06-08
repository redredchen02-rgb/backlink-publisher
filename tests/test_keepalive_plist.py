"""Schema validation tests for keepalive-run launchd plist (plan 2026-06-05-004 Unit 6)."""
from __future__ import annotations

import plistlib
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
KEEPALIVE_PLIST = SCRIPTS_DIR / "com.dex.bp-keepalive.plist"
RECHECK_PLIST = SCRIPTS_DIR / "com.dex.bp-recheck.plist"

REQUIRED_KEYS = {
    "Label",
    "ProgramArguments",
    "StartCalendarInterval",
    "StandardOutPath",
    "WorkingDirectory",
}


def _load(path: Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


# ── com.dex.bp-keepalive.plist ─────────────────────────────────────────────────


def test_keepalive_plist_exists():
    assert KEEPALIVE_PLIST.exists(), f"Missing: {KEEPALIVE_PLIST}"


def test_keepalive_plist_required_keys():
    data = _load(KEEPALIVE_PLIST)
    missing = REQUIRED_KEYS - set(data)
    assert not missing, f"Missing required keys: {missing}"


def test_keepalive_plist_label():
    data = _load(KEEPALIVE_PLIST)
    assert data["Label"] == "com.dex.bp-keepalive"


def test_keepalive_plist_program_arguments_non_empty():
    data = _load(KEEPALIVE_PLIST)
    args = data["ProgramArguments"]
    assert isinstance(args, list) and len(args) >= 1


def test_keepalive_plist_schedule_has_hour_and_minute():
    data = _load(KEEPALIVE_PLIST)
    schedule = data["StartCalendarInterval"]
    assert "Hour" in schedule
    assert "Minute" in schedule


def test_keepalive_plist_working_directory_is_absolute():
    data = _load(KEEPALIVE_PLIST)
    wd = Path(data["WorkingDirectory"])
    assert wd.is_absolute(), f"WorkingDirectory must be absolute: {wd}"


def test_keepalive_plist_working_directory_exists():
    data = _load(KEEPALIVE_PLIST)
    wd = Path(data["WorkingDirectory"])
    assert wd.exists(), f"WorkingDirectory does not exist: {wd}"


def test_keepalive_plist_standard_out_path_defined():
    data = _load(KEEPALIVE_PLIST)
    assert data.get("StandardOutPath"), "StandardOutPath must be non-empty"


def test_keepalive_plist_run_at_load_false():
    data = _load(KEEPALIVE_PLIST)
    # RunAtLoad absent or explicitly False — never run on every boot load
    assert data.get("RunAtLoad", False) is False


def test_keepalive_plist_pythonhashseed_set():
    data = _load(KEEPALIVE_PLIST)
    env = data.get("EnvironmentVariables", {})
    assert env.get("PYTHONHASHSEED") == "0", "PYTHONHASHSEED=0 required for deterministic footprint tests"


# ── com.dex.bp-recheck.plist still valid ──────────────────────────────────────


def test_recheck_plist_still_valid():
    """Existing recheck plist must remain schema-valid after U6 changes."""
    assert RECHECK_PLIST.exists(), f"Missing: {RECHECK_PLIST}"
    data = _load(RECHECK_PLIST)
    missing = REQUIRED_KEYS - {"StandardOutPath"} - set(data)  # recheck may omit stdout
    assert not missing, f"recheck plist missing required keys: {missing}"


def test_recheck_plist_label():
    data = _load(RECHECK_PLIST)
    assert data["Label"] == "com.dex.bp-recheck"
