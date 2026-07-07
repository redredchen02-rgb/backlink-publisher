"""fcntl compatibility shim for Windows.

Provides a drop-in replacement for the Unix ``fcntl`` module's ``flock()``
function and its associated constants (LOCK_EX, LOCK_NB, LOCK_UN).

On Windows, true POSIX ``flock`` is not available. This shim implements
cross-process file locking using ``msvcrt.locking()`` (available on all
modern Windows builds). For ``LOCK_UN`` we use ``msvcrt.locking(LK_UNLCK)``.

This shim is imported automatically if the real ``fcntl`` is unavailable
(Windows). All other ``fcntl`` functions (e.g. ``ioctl``, ``fnctl``) are
not provided — if you need them, use a conditional import and handle
``ImportError`` explicitly.

Usage in production code:
    try:
        import fcntl
    except ImportError:
        import backlink_publisher._compat.fcntl as fcntl
"""

from __future__ import annotations

import errno
import msvcrt
from typing import IO

# ---- Constants ----
LOCK_EX = 1  # We map to msvcrt.LK_NBLCK / LK_LOCK internally
LOCK_NB = 2  # Non-blocking modifier
LOCK_UN = 8  # Unlock


def flock(fd: int | IO, operation: int) -> None:
    """Perform a file lock operation, compatible with ``fcntl.flock``.

    Parameters
    ----------
    fd : int | IO
        File descriptor (int) or a file-like object with a ``fileno()`` method.
    operation : int
        One of:
        - ``LOCK_EX`` — exclusive lock (blocking)
        - ``LOCK_EX | LOCK_NB`` — exclusive lock, non-blocking
        - ``LOCK_UN`` — unlock

    Raises
    ------
    IOError / OSError
        If the lock cannot be acquired (``errno.EAGAIN`` / ``EWOULDBLOCK``
        for non-blocking attempts).
    """
    if hasattr(fd, "fileno"):
        fd = fd.fileno()

    if operation & LOCK_UN:
        # Unlock
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]  # Windows-only
        return

    exclusive = operation & LOCK_EX
    non_blocking = operation & LOCK_NB

    if exclusive:
        if non_blocking:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]  # Windows-only
            except OSError as e:
                if e.winerror in (33,):  # type: ignore[attr-defined]  # Windows-only  # 33 = ERROR_LOCK_VIOLATION
                    raise OSError(errno.EAGAIN, "Resource temporarily unavailable")
                raise
        else:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]  # Windows-only
