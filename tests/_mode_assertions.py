"""Windows-aware file-mode assertion helper.

POSIX permission bits (0o600, 0o700, 0o644, ...) are not representable by
``os.chmod``/``os.stat`` on Windows -- see
``src/backlink_publisher/_util/permissions.py``'s own module docstring, which
documents that permission enforcement is an intentional no-op on ``win32``.
Tests that hardcode ``stat.S_IMODE(path.stat().st_mode) == 0o600`` fail on
Windows for that reason alone, with no bearing on whether the code under test
is correct -- this is documented, pre-existing, known noise (see
``docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md``).

CI runs exclusively on Linux (``ubuntu-latest``), so real enforcement stays
fully checked there; this helper only changes what a *local Windows* run
asserts.

Import (tests/ is not a package -- flat import):

    from _mode_assertions import assert_file_mode
"""
from __future__ import annotations

from pathlib import Path
import stat
import sys


def assert_file_mode(path: str | Path, expected_octal: int) -> None:
    """Assert *path* has ``expected_octal`` permission bits.

    On POSIX, asserts the exact mode -- unchanged behavior, still fully
    enforced by CI. On ``win32``, asserts only that the path exists: real
    permission bits are not representable by ``os.chmod`` there by design,
    so a mode comparison would be asserting an OS capability gap, not a
    product defect.
    """
    p = Path(path)
    if sys.platform == "win32":
        assert p.exists(), f"{p} does not exist"
        return
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == expected_octal, f"{p} is {oct(mode)}, expected {oct(expected_octal)}"
