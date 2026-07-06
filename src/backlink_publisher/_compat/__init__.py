"""Platform compatibility layer.

Provides drop-in replacements for Unix-only modules when running on Windows.
Auto-patches ``sys.modules`` at import time so the rest of the codebase can
write ``import fcntl`` without conditional imports.
"""

from __future__ import annotations

import sys

__all__: list[str] = []

# ---- Patch fcntl on Windows ----
if sys.platform == "win32":
    from backlink_publisher._compat import fcntl as _fcntl_compat

    sys.modules["fcntl"] = _fcntl_compat
