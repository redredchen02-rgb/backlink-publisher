"""Shared CLI formatting utilities — JSONL emit, RECON format, progress reporting.

Extracted from ``recheck-backlinks``, ``equity-ledger``, ``click-track``, and
``referral-attribute`` CLIs which all share nearly identical stdout JSONL
emit patterns. Consolidating here keeps each CLI entry point focused on its
business logic rather than output plumbing.
"""

from __future__ import annotations

import json
import sys
from typing import Any, IO


def emit_jsonl(rows: list[dict[str, Any]], file: IO[str] = sys.stdout) -> None:
    """Emit ``rows`` as JSONL to *file* (default stdout), one JSON object per
    line. Handles stdout encoding on Windows transparently.

    Centralises the ``json.dumps(row, ensure_ascii=False) + file.write``
    pattern that 4 CLI modules repeat verbatim.
    """
    for row in rows:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def emit_jsonl_stream(rows: list[dict[str, Any]], file: IO[str] = sys.stdout) -> None:
    """Same as ``emit_jsonl`` but flushes after each row (for streaming
    outputs where the consumer reads line-by-line, e.g. pipeline pipes).
    """
    for row in rows:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")
        file.flush()


def emit_progress(summary: dict[str, Any], file: IO[str] = sys.stderr) -> None:
    """Emit a human-readable progress/recon summary to *file* (default stderr).

    Follows the project convention: stdout = clean machine-readable JSONL,
    stderr = human-readable diagnostics.
    """
    parts: list[str] = []
    for key, value in summary.items():
        parts.append(f"{key}={value}")
    file.write("  ".join(parts) + "\n")


def emit_error(msg: str, file: IO[str] = sys.stderr) -> None:
    """Emit a formatted error message to *file* (default stderr)."""
    file.write(f"error: {msg}\n")
