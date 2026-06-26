"""Shim re-export — payload enhancement helpers now live in ``validate._payload``.

Kept for backward compatibility; all callers should import directly from
``backlink_publisher.validate._payload``.

(Plan 2026-06-24-002 U5)
"""

from __future__ import annotations

from backlink_publisher.validate._payload import (  # noqa: F401
    _check_main_domain_in_html,
    _detect_row_body_language,
    _enhance_payload,
    _extract_hrefs_from_html,
    _HrefCollector,
    _nfc_normalize_in_place,
    _resolve_banner_path,
    _resolve_branded_pool,
)
