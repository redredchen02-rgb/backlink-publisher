"""bp-report-bug --wrap must capture non-ASCII child stderr (audit cp950 [14]).

_run_wrapped runs an arbitrary command and iterates its stderr line-by-line. The
Popen used text=True with NO encoding=, so on zh-TW Windows (cp950) a child that
emits Chinese / em-dash / emoji on stderr (pytest tracebacks, git/gh output —
exactly what bug-capture exists to record) crashed the wrapper with
UnicodeDecodeError. The fix pins encoding="utf-8", errors="replace".
"""
from __future__ import annotations

__tier__ = "unit"

import sys

from backlink_publisher.cli.report_bug.main import _run_wrapped


def test_wrap_captures_non_ascii_stderr_without_crash(tmp_path):
    marker = "测试 café — \U0001f680 stderr-line"  # 测试 café — 🚀
    child = tmp_path / "emit.py"
    # Emit raw UTF-8 BYTES (as a real UTF-8-emitting child does), bypassing the
    # child's own locale stderr encoding so this test isolates _run_wrapped's
    # decode: with the fix it reads UTF-8 correctly; the old cp950 text=True
    # decode would raise UnicodeDecodeError on these multibyte sequences.
    child.write_text(
        "import sys\n"
        "marker = " + repr(marker) + "\n"
        "sys.stderr.buffer.write(marker.encode('utf-8') + b'\\n')\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    # shell=True with quoted paths avoids shlex-quoting differences and works on
    # both cmd.exe and /bin/sh; the child's UTF-8 stderr is decoded by the Popen.
    rc, captured = _run_wrapped(f'"{sys.executable}" "{child}"', shell=True)

    assert rc == 3
    assert marker in captured, f"non-ASCII stderr not captured intact: {captured!r}"
