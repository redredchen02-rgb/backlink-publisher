"""Unit tests for the ``bp-report-bug`` CLI entrypoint.

Covers the three capture paths (--wrap / --stderr-file / -), the --json flag,
the --no-redact escape hatch, and the exit-code contract (0 on success, 2 on
insufficient input).
"""

from __future__ import annotations

__tier__ = "unit"

import json
from pathlib import Path
import sys

import pytest

from backlink_publisher.cli.report_bug import main


def _write_failing_script(tmp_path: Path, exit_code: int = 3) -> Path:
    """A script that emits a typed-error envelope to stderr and exits."""
    script = tmp_path / "fail.py"
    script.write_text(
        "import sys\n"
        'sys.stderr.write(\'__BLP_ERR__ {"error_class": "AuthExpiredError", '
        '"exit_code": 3, "message": "channel velog credentials expired token=abc123"}\\n\')'
        "\nsys.exit(3)\n"
        if exit_code == 3
        else "import sys\nsys.exit(0)\n",
        encoding="utf-8",
    )
    return script


def _parse_stdout(out: str) -> dict:
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {}


# ── --wrap ───────────────────────────────────────────────────────────────────


class TestWrap:
    def test_wrap_failure_builds_report(self, tmp_path, capsys) -> None:
        script = _write_failing_script(tmp_path, exit_code=3)
        with pytest.raises(SystemExit) as exc:
            main(["--wrap", f"{sys.executable} {script}"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        record = _parse_stdout(captured.out)
        assert "report_path" in record
        assert Path(record["report_path"]).exists()
        # The secret token must not appear in the written report.
        md = Path(record["report_path"]).read_text(encoding="utf-8")
        assert "abc123" not in md

    def test_wrap_success_exits_zero_no_report(self, tmp_path, capsys) -> None:
        script = _write_failing_script(tmp_path, exit_code=0)
        with pytest.raises(SystemExit) as exc:
            main(["--wrap", f"{sys.executable} {script}"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "exited 0" in captured.err
        record = _parse_stdout(captured.out)
        # No report_path line is emitted on a clean wrap.
        assert "report_path" not in record


# ── --stderr-file ────────────────────────────────────────────────────────────


class TestStderrFile:
    def test_stderr_file_builds_report(self, tmp_path, capsys) -> None:
        err_file = tmp_path / "err.txt"
        err_file.write_text(
            '__BLP_ERR__ {"error_class": "DependencyError", "exit_code": 3, '
            '"message": "rebind channel token=xyz789"}\nsome context line\n',
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            main(["--stderr-file", str(err_file)])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        record = _parse_stdout(captured.out)
        assert Path(record["report_path"]).exists()
        md = Path(record["report_path"]).read_text(encoding="utf-8")
        assert "xyz789" not in md
        assert "DependencyError" in md

    def test_missing_stderr_file_exits_2(self, tmp_path, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--stderr-file", str(tmp_path / "nope.txt")])
        assert exc.value.code == 2


# ── --json / --no-redact ─────────────────────────────────────────────────────


class TestFlags:
    def test_json_includes_report(self, tmp_path, capsys) -> None:
        err_file = tmp_path / "err.txt"
        err_file.write_text(
            '__BLP_ERR__ {"error_class": "AuthExpiredError", "exit_code": 3, '
            '"message": "expired"}\n',
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            main(["--stderr-file", str(err_file), "--json"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        record = _parse_stdout(captured.out)
        assert "report" in record
        assert record["report"]["error"]["error_class"] == "AuthExpiredError"

    def test_no_redact_warns_and_leaks(self, tmp_path, capsys) -> None:
        err_file = tmp_path / "err.txt"
        err_file.write_text(
            '__BLP_ERR__ {"error_class": "AuthExpiredError", "exit_code": 3, '
            '"message": "expired token=leakme"}\n',
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            main(["--stderr-file", str(err_file), "--no-redact"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "no-redact" in captured.err.lower()
        record = _parse_stdout(captured.out)
        md = Path(record["report_path"]).read_text(encoding="utf-8")
        assert "leakme" in md


# ── insufficient input ───────────────────────────────────────────────────────


class TestInsufficientInput:
    def test_no_source_exits_2(self, capsys) -> None:
        # In pytest, stdin is not a tty, so the interactive prompt is skipped
        # and an empty invocation with no capture source exits 2.
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2
