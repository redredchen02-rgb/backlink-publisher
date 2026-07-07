"""Unit 1 of the thin-WebUI Phase 1 contract (plan 2026-05-27-004): operator
error fidelity. Covers the two pure helpers added to ``cli_runner``:

* ``surface_cli_error`` — banner-stripped, length-bounded error text that
  replaces the old ``stderr[:200]`` truncation.
* ``run_pipe_capture`` — the non-raising sibling of ``run_pipe`` that returns
  ``{stdout, stderr, returncode}`` so callers can branch on the exit code with
  stdout intact (publish exit-4, checkpoint resume).
"""
from __future__ import annotations

__tier__ = "unit"
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# cli_runner imports only stdlib + project utils; no Flask needed.
from webui_app.helpers.cli_runner import (  # noqa: E402
    _MAX_SURFACED_ERROR,
    run_pipe_capture,
    surface_cli_error,
)

_BANNER = (
    "[validate-backlinks] effective config:\n"
    "  config:    /tmp/x.toml\n"
    "  env:       (none)\n"
    "  platforms: blogger\n"
    "  sha:       0123456789abcdef\n"
)


# ── surface_cli_error ────────────────────────────────────────────────────────

def test_surface_strips_banner_and_keeps_full_error():
    real = "AuthExpiredError: token for blogger expired, re-bind in settings"
    out = surface_cli_error(_BANNER + real)
    assert real in out
    assert "effective config:" not in out  # banner gone


def test_surface_keeps_error_longer_than_old_200_cap():
    real = "validation error: " + ("Z" * 500) + " TAIL"
    out = surface_cli_error(_BANNER + real)
    # The whole error survives — the old [:200] slice would have dropped "TAIL".
    assert "TAIL" in out
    assert len(out) > 200


def test_surface_bounds_runaway_stderr():
    huge = "x" * (_MAX_SURFACED_ERROR + 5000)
    out = surface_cli_error(huge)
    assert len(out) <= _MAX_SURFACED_ERROR + len(" …(truncated)")
    assert out.endswith("…(truncated)")


def test_surface_handles_none_and_empty():
    assert surface_cli_error(None) == ""
    assert surface_cli_error("") == ""


def test_surface_respects_custom_limit():
    out = surface_cli_error("abcdefghij", limit=4)
    assert out == "abcd …(truncated)"


# ── run_pipe_capture ─────────────────────────────────────────────────────────

class _FakeCompleted:
    def __init__(self, stdout, stderr, returncode):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_capture_returns_dict_with_returncode_nonzero_no_raise():
    """The whole point vs run_pipe: a non-zero exit returns stdout+code, never raises."""
    fake = _FakeCompleted(stdout="row1\nrow2\n", stderr="item failed", returncode=4)
    with patch("backlink_publisher.sdk._cli_runner.subprocess.run", return_value=fake):
        result = run_pipe_capture(["publish-backlinks", "--resume", "rid"], "")
    assert result == {"stdout": "row1\nrow2\n", "stderr": "item failed", "returncode": 4}


def test_capture_returns_dict_on_success():
    fake = _FakeCompleted(stdout="ok\n", stderr="", returncode=0)
    with patch("backlink_publisher.sdk._cli_runner.subprocess.run", return_value=fake):
        result = run_pipe_capture(["validate-backlinks"], "{}\n")
    assert result["returncode"] == 0
    assert result["stdout"] == "ok\n"


def test_run_pipe_still_raises_on_nonzero():
    """run_pipe (the raising sibling) keeps its contract — capture is the opt-in."""
    from webui_app.helpers.cli_runner import run_pipe
    fake = _FakeCompleted(stdout="", stderr="boom", returncode=4)
    with patch("backlink_publisher.sdk._cli_runner.subprocess.run", return_value=fake):
        with pytest.raises(Exception, match="boom"):
            run_pipe(["validate-backlinks"], "{}\n")


def test_run_pipe_silent_failure_raises_diagnostic():
    """run_pipe's silent-failure guard survives the run_pipe_capture refactor:
    exit 0 + empty stdout/stderr + non-empty stdin = a broken entry-point
    (missing __main__.py / __name__ guard), which must raise a real diagnostic
    rather than be consumed as success."""
    from webui_app.helpers.cli_runner import run_pipe
    fake = _FakeCompleted(stdout="", stderr="", returncode=0)
    with patch("backlink_publisher.sdk._cli_runner.subprocess.run", return_value=fake):
        with pytest.raises(Exception, match="produced no output"):
            run_pipe(["validate-backlinks"], "{}\n")


# ── UTF-8 subprocess encoding (Windows ANSI-codepage crash fix) ─────────────

def test_capture_passes_utf8_encoding_and_pythonioencoding_env():
    """run_pipe_capture must force UTF-8 text I/O on both sides of the pipe:
    encoding="utf-8" for the parent's decode of the child's bytes, and
    PYTHONIOENCODING=utf-8 in the child's own env so its internal print/log
    calls don't fall back to the Windows ANSI codepage."""
    fake = _FakeCompleted(stdout="ok\n", stderr="", returncode=0)
    with patch("backlink_publisher.sdk._cli_runner.subprocess.run", return_value=fake) as mock_run:
        run_pipe_capture(["publish-backlinks"], "{}\n")

    _args, kwargs = mock_run.call_args
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"


def test_child_subprocess_survives_non_big5_cjk_with_utf8_child_env():
    """Reproduces the actual Windows failure mode in an OS-independent way:
    Python's ``cp950`` (Big5) codec is a stdlib codec, not an OS setting, so
    forcing a child's ``PYTHONIOENCODING`` to ``cp950`` reproduces the crash
    on any platform (including this repo's ubuntu-only CI). Without the fix,
    printing a Simplified Chinese character outside Big5's repertoire (关,
    U+5173) crashes the child; ``utf8_child_env()`` prevents it."""
    from backlink_publisher._util.subprocess_env import utf8_child_env

    script = "print('義关')"  # 義 (Big5-representable) + 关 (not)

    unfixed_env = dict(os.environ, PYTHONIOENCODING="cp950")
    unfixed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=unfixed_env,
    )
    assert unfixed.returncode != 0
    assert "UnicodeEncodeError" in unfixed.stderr

    fixed_env = utf8_child_env(dict(os.environ, PYTHONIOENCODING="cp950"))
    fixed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=fixed_env,
    )
    assert fixed.returncode == 0
    assert "UnicodeEncodeError" not in (fixed.stderr or "")
