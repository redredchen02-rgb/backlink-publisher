"""UTF-8-safe subprocess child environment — canonical fix for the Windows
ANSI-codepage fallback that crashes CJK text I/O in piped subprocesses.

On Windows, a Python child process whose stdout/stderr is a pipe (not a real
console) falls back to ``locale.getpreferredencoding(False)`` — the system
ANSI codepage — for its own text I/O, unless ``PYTHONIOENCODING`` forces
otherwise. Every subprocess call site that captures text output from a
``backlink_publisher`` CLI module should build its child env through
:func:`utf8_child_env`.
"""

from __future__ import annotations

import os


def utf8_child_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of *base_env* (or ``os.environ`` if ``None``) with
    ``PYTHONIOENCODING`` forced to ``"utf-8"``.

    Forces unconditionally rather than ``setdefault`` — correctness here
    doesn't depend on operator configuration.
    """
    env = dict(base_env) if base_env is not None else os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env
