"""Backward-compat re-export shim for validate._payload.

Implementation moved to backlink_publisher.validate._payload (plan 2026-06-24-002 U5)
to fix the validate/engine.py → cli/ layer violation.  This shim preserves the
original module path so any test patching backlink_publisher.cli._validate_payload.X
and any existing import still works.
"""
from __future__ import annotations

from backlink_publisher.validate._payload import (  # noqa: F401
    _HrefCollector,
    _check_body_language_gate,
    _check_main_domain_in_html,
    _detect_row_body_language,
    _enhance_payload,
    _extract_hrefs_from_html,
    _nfc_normalize_in_place,
    _resolve_branded_pool,
)
