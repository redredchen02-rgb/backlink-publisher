"""Cross-platform file permission utilities.

On POSIX systems, credential and token files must be 0o600 to prevent
accidental group/world read. Windows does not enforce Unix permission
semantics (os.chmod is a no-op for many operations, and the default
st_mode is always 0o100666), so permission checks are skipped on Windows.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from backlink_publisher._util.errors import DependencyError


def check_0600(
    path: str | Path,
    *,
    label: str | None = None,
    extra: str = "",
) -> None:
    """Raise ``DependencyError`` if *path* exists and is NOT 0o600 on POSIX.

    On Windows this is a no-op — the OS does not enforce Unix permission bits.

    Args:
        path: File path to check.
        label: Human-readable label for error messages (defaults to the file name).
        extra: Additional advice appended after the ``chmod`` line.

    Raises:
        DependencyError: On POSIX when the file has non-0o600 permissions.
    """
    if sys.platform == "win32":
        return
    mode = os.stat(path).st_mode & 0o777
    if mode != 0o600:
        name = label or os.path.basename(str(path))
        # Wording is contract-tested from both lineages: adapters assert the
        # plain "must be 0600" phrasing, medium_browser asserts "0o600".
        msg = f"{name} must be 0600 (0o600; found {oct(mode)})\nRun: chmod 0600 {path}"
        if extra:
            msg += f"\n{extra}"
        raise DependencyError(msg)
