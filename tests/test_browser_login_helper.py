"""Unit tests for webui_app.services.browser_login.spawn_browser_login.

The helper is the template every future platform binding (medium, etc.) will
reuse. It must:

- Report ok=True when subprocess survives probe_seconds.
- Report ok=False with tailed log when subprocess exits before probe_seconds.
- Tee subprocess output to a log file in the cache dir.
- Honour BACKLINK_PUBLISHER_CACHE_DIR for log placement.
- Truncate prior log content so stale crashes don't pollute new error tails.
- Not deadlock when subprocess produces large output (the pipe bug this
  helper was created to avoid).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure webui_app is importable from repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from webui_app.services.browser_login import SpawnResult, spawn_browser_login  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path))
    # The helper prepends "src" to PYTHONPATH for the spawned subprocess.
    # Append tmp_path so the test stub_pkg.* module under tmp_path is also
    # importable from within the subprocess.
    existing = os.environ.get("PYTHONPATH", "")
    extra = str(tmp_path)
    monkeypatch.setenv(
        "PYTHONPATH",
        extra + (os.pathsep + existing if existing else ""),
    )
    yield


def _write_stub(tmp_path: Path, name: str, body: str) -> str:
    """Write a python file under tmp_path and return its dotted module name."""
    pkg = tmp_path / "stub_pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / f"{name}.py").write_text(body)
    return f"stub_pkg.{name}"


def test_returns_ok_when_subprocess_survives_probe(tmp_path, monkeypatch):
    module = _write_stub(
        tmp_path,
        "alive",
        "import time, sys\n"
        "print('opening browser', flush=True)\n"
        "time.sleep(5)\n",
    )
    monkeypatch.chdir(tmp_path)

    result = spawn_browser_login(module, probe_seconds=0.5)
    try:
        assert result.ok is True
        assert result.error is None
        assert result.log_path.exists()
        assert result.log_path.name == "alive.log"
    finally:
        # Reap the orphan stub subprocess so it doesn't outlive the test.
        _kill_descendants_of_module(module)


def test_returns_error_when_subprocess_exits_fast(tmp_path, monkeypatch):
    module = _write_stub(
        tmp_path,
        "fast_crash",
        "import sys\n"
        "print('about to crash', flush=True)\n"
        "sys.stderr.write('TypeError: fake crash from log API mismatch\\n')\n"
        "sys.exit(1)\n",
    )
    monkeypatch.chdir(tmp_path)

    result = spawn_browser_login(module, probe_seconds=2.0)
    assert result.ok is False
    assert "TypeError" in result.error
    assert "fake crash" in result.error
    assert result.log_path.exists()


def test_log_path_lives_under_configured_cache_dir(tmp_path, monkeypatch):
    module = _write_stub(tmp_path, "fast2", "import sys; sys.exit(0)\n")
    monkeypatch.chdir(tmp_path)

    result = spawn_browser_login(module, probe_seconds=2.0)
    assert result.log_path.is_relative_to(tmp_path / "browser-login-logs")


def test_truncates_stale_log_between_runs(tmp_path, monkeypatch):
    module = _write_stub(
        tmp_path,
        "fast3",
        "import sys\nsys.stderr.write('current-run-error\\n')\nsys.exit(2)\n",
    )
    monkeypatch.chdir(tmp_path)

    log_dir = tmp_path / "browser-login-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stale = log_dir / "fast3.log"
    stale.write_text("STALE-CRASH-FROM-PREVIOUS-RUN\n" * 50)

    result = spawn_browser_login(module, probe_seconds=2.0)
    body = result.log_path.read_text("utf-8", errors="replace")
    assert "STALE-CRASH-FROM-PREVIOUS-RUN" not in body
    assert "current-run-error" in body


def test_survives_large_subprocess_output_no_deadlock(tmp_path, monkeypatch):
    """Regression: previous PIPE-based endpoint deadlocked once subprocess
    output exceeded the ~64KB pipe buffer. Helper tees to a file, so a noisy
    subprocess that survives probe_seconds must still report ok=True."""
    module = _write_stub(
        tmp_path,
        "noisy",
        "import time\n"
        "for i in range(2000):\n"
        "    print('x' * 100, flush=True)\n"
        "time.sleep(5)\n",
    )
    monkeypatch.chdir(tmp_path)

    result = spawn_browser_login(module, probe_seconds=1.0)
    try:
        assert result.ok is True
        assert result.log_path.stat().st_size > 50_000
    finally:
        _kill_descendants_of_module(module)


def test_spawn_result_is_frozen_dataclass():
    r = SpawnResult(ok=True, error=None, log_path=Path("/tmp/x"))
    with pytest.raises(Exception):
        r.ok = False  # type: ignore[misc]


def _kill_descendants_of_module(module: str) -> None:
    """Best-effort reap of stub subprocesses still running after a test."""
    import subprocess

    short = module.rsplit(".", 1)[-1]
    try:
        subprocess.run(
            ["pkill", "-f", f"stub_pkg.{short}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except Exception:
        pass
