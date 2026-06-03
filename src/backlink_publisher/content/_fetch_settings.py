"""Env-var overridable constants for :mod:`content.fetch`.

Extracted from ``fetch.py`` (2026-06-03) for monolith-budget headroom.
Re-exported by ``fetch.py``; tests and downstream code import via
``content.fetch.<name>``.
"""

from __future__ import annotations

import os


FETCH_TIMEOUT: int = 10
"""Wall-clock budget per single GET attempt."""

MAX_RETRIES: int = 2
"""Retries on transient failures (timeout / 5xx / network)."""

HEAD_SCAN_BYTES: int = 256_000
"""Soft head-window cap for title extraction."""

MAX_BODY_BYTES: int = 1_000_000
"""Defensive hard cap passed down to readers."""

BODY_TOO_SMALL_BYTES: int = 2048
"""Below this count a 200 with no title is rejected as body_too_small."""


def _fetch_timeout() -> int:
    try:
        return int(os.environ.get("BACKLINK_FETCH_TIMEOUT", FETCH_TIMEOUT))
    except (ValueError, TypeError):
        return FETCH_TIMEOUT


def _max_retries() -> int:
    try:
        return int(os.environ.get("BACKLINK_FETCH_MAX_RETRIES", MAX_RETRIES))
    except (ValueError, TypeError):
        return MAX_RETRIES


def _head_scan_bytes() -> int:
    try:
        return int(os.environ.get("BACKLINK_FETCH_HEAD_SCAN_BYTES", HEAD_SCAN_BYTES))
    except (ValueError, TypeError):
        return HEAD_SCAN_BYTES


def _max_body_bytes() -> int:
    try:
        return int(os.environ.get("BACKLINK_FETCH_MAX_BODY_BYTES", MAX_BODY_BYTES))
    except (ValueError, TypeError):
        return MAX_BODY_BYTES


def _body_too_small_bytes() -> int:
    try:
        return int(os.environ.get("BACKLINK_FETCH_BODY_TOO_SMALL", BODY_TOO_SMALL_BYTES))
    except (ValueError, TypeError):
        return BODY_TOO_SMALL_BYTES
