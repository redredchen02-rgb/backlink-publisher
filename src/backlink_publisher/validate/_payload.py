"""Payload enhancement for the validate-backlinks pipeline.

Canonical home for _enhance_payload and its helpers.  All helpers live here
so that validate/engine.py can import them without crossing the domain→cli
layer boundary.  cli/_validate_payload.py is a thin re-export shim for
backward-compat (tests that patch backlink_publisher.cli._validate_payload.X
still work because the shim re-imports from here at module load time).
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urlsplit

from backlink_publisher.anchor.lang import check_anchor_language
from backlink_publisher.config import Config, get_anchor_pool_v2
from backlink_publisher.linkcheck.language import (
    SUPPORTED_LANGUAGES,
    detect_language_from_html,
    detect_language_from_markdown,
    language_matches,
)
from backlink_publisher._util.logger import validate_logger
from ..schema import _is_field_present


def _resolve_branded_pool(row: dict[str, Any], config: Config | None) -> list[str]:
    """Return the branded_pool to use for R4 exemption checks.

    Resolution order (per plan 2026-05-14-001):
    1. ``row.metadata.branded_pool`` snapshot emitted by plan-backlinks.
    2. Live ``get_anchor_pool_v2`` lookup against the loaded config.
    3. Empty list.
    """
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        snap = metadata.get("branded_pool")
        if isinstance(snap, list):
            return [str(x) for x in snap]
    if config is None:
        return []
    main_domain = row.get("main_domain", "")
    if not main_domain:
        return []
    return list(get_anchor_pool_v2(config, main_domain, "home", "branded"))


class _HrefCollector(HTMLParser):
    """Stdlib HTML parser subclass that collects ``<a href>`` attribute values."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value is not None:
                self.hrefs.append(value)


def _extract_hrefs_from_html(html: str) -> list[str]:
    """Return a list of all ``<a href>`` attribute values in ``html``."""
    if not isinstance(html, str) or not html.strip():
        return []
    collector = _HrefCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:  # noqa: BLE001 — parser may raise on extreme inputs
        return collector.hrefs
    return collector.hrefs


def _check_main_domain_in_html(html: str, main_domain_normalized: str) -> bool:
    """Plan 2026-05-18-006 Unit 6 R3: verify ``main_domain_normalized`` is the
    host of at least one ``<a href>`` link in ``html``.

    Accepts exact host match OR subdomain suffix (e.g. ``blog.example.com``
    matches ``example.com``).
    """
    hrefs = _extract_hrefs_from_html(html)
    domain_lower = main_domain_normalized.lower()
    for href in hrefs:
        try:
            parsed = urlsplit(href)
            host = (parsed.hostname or "").lower()
            if host == domain_lower or host.endswith("." + domain_lower):
                return True
        except ValueError:
            continue
    return False


def _nfc_normalize_in_place(row: dict[str, Any]) -> None:
    """Apply NFC normalization to row-resident string fields at validate-time."""
    for field in ("content_markdown", "content_html"):
        value = row.get(field)
        if isinstance(value, str):
            row[field] = unicodedata.normalize("NFC", value)

    links = row.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and isinstance(link.get("anchor"), str):
                link["anchor"] = unicodedata.normalize("NFC", link["anchor"])


def _detect_row_body_language(row: dict[str, Any]) -> tuple[str, str]:
    """Dispatch body-language detection by source-field presence.

    Returns ``(detected, source_used)`` where ``source_used`` is one of
    ``"markdown"``, ``"html"``, ``"both-match"``, ``"both-mismatch:<md>/<html>"``,
    or ``"absent"``.
    """
    md = row.get("content_markdown")
    html = row.get("content_html")
    md_present = _is_field_present(md)
    html_present = _is_field_present(html)

    if md_present and html_present:
        md_lang = detect_language_from_markdown(cast(str, md))
        html_lang = detect_language_from_html(cast(str, html))
        if md_lang == html_lang:
            return md_lang, "both-match"
        return "unknown", f"both-mismatch:md={md_lang}/html={html_lang}"

    if md_present:
        return detect_language_from_markdown(cast(str, md)), "markdown"
    if html_present:
        return detect_language_from_html(cast(str, html)), "html"
    return "unknown", "absent"


def _check_body_language_gate(
    row: dict[str, Any],
    detected: str,
    source_used: str,
    requested: str,
    errors_list: list[str],
    warnings_list: list[str],
) -> None:
    """Validate body language matches the requested language; append to errors/warnings."""
    if source_used.startswith("both-mismatch:"):
        tag = source_used.removeprefix("both-mismatch:")
        errors_list.append(
            f"body language mismatch between content_markdown and "
            f"content_html ({tag}); operator must use single-source "
            f"workflow or update both fields"
        )
        return

    if not language_matches(detected, requested):
        if requested == "zh-CN":
            body_text = (
                row.get("content_markdown")
                or row.get("content_html")
                or ""
            )
            cjk_count = sum(
                1 for c in body_text
                if 0x4E00 <= ord(c) <= 0x9FFF
            )
            hangul_count = sum(
                1 for c in body_text
                if 0xAC00 <= ord(c) <= 0xD7AF
            )
            latin_count = sum(
                1 for c in body_text
                if ("A" <= c <= "Z") or ("a" <= c <= "z")
            )
            total_latin_plus_cjk = latin_count + cjk_count + hangul_count
            if total_latin_plus_cjk > 0:
                cjk_ratio = (cjk_count + hangul_count) / total_latin_plus_cjk
                if cjk_ratio >= 0.30:
                    validate_logger.warn(
                        f"body language '{detected}' != requested '{requested}', "
                        f"but CJK ratio ({cjk_ratio:.0%}) suggests zh-CN content; "
                        f"downgraded from error to warning"
                    )
                    warnings_list.append(
                        f"body language '{detected}' != requested 'zh-CN', "
                        f"but CJK ratio ({cjk_ratio:.0%}) suggests zh-CN content; "
                        f"downgraded from error. Best practice: ensure ≥30% of "
                        f"the body text uses CJK codepoints."
                    )
                    row.setdefault("validation", {})["body_language_relaxed"] = True
                    return
            errors_list.append(
                f"body language '{detected}' does not match requested '{requested}'"
            )
        else:
            errors_list.append(
                f"body language '{detected}' does not match requested '{requested}'"
            )


def _enhance_payload(row: dict[str, Any], config: Config | None = None) -> dict[str, Any]:
    """Attach a ``validation`` block; populate errors[] on R2/R4/R5 failure.

    Contract (R11): ``validation.status`` is ``"failed"`` if any error fired,
    else ``"passed"``. ``validation.errors`` is the structured failure list.
    ``validation.warnings`` is preserved as an empty list for back-compat.
    """
    errors_list: list[str] = []
    warnings_list: list[str] = []

    _nfc_normalize_in_place(row)

    requested = row.get("language", "")

    if requested not in SUPPORTED_LANGUAGES:
        validate_logger.warn(
            f"row {row.get('id', '?')}: language '{requested}' outside enum "
            f"{sorted(SUPPORTED_LANGUAGES)}; skipping language and anchor gates"
        )
    else:
        detected, source_used = _detect_row_body_language(row)
        _check_body_language_gate(row, detected, source_used, requested, errors_list, warnings_list)

        branded_pool = _resolve_branded_pool(row, config)
        for idx, link in enumerate(row.get("links", [])):
            anchor = link.get("anchor", "") if isinstance(link, dict) else ""
            kind = link.get("kind", "") if isinstance(link, dict) else ""
            ok, reason = check_anchor_language(anchor, requested, kind, branded_pool)
            if not ok:
                errors_list.append(f"link[{idx}] anchor {anchor!r} failed: {reason}")

    html_present = _is_field_present(row.get("content_html"))
    if html_present:
        main_domain_normalized = row.get("main_domain_normalized", "")
        if not isinstance(main_domain_normalized, str) or not main_domain_normalized:
            errors_list.append(
                "content_html present but main_domain_normalized missing — "
                "schema-time normalization should have populated it"
            )
        else:
            host_part_match = _check_main_domain_in_html(
                row["content_html"], main_domain_normalized
            )
            if not host_part_match:
                errors_list.append(
                    f"main_domain '{main_domain_normalized}' is not the host "
                    f"of any <a href> in content_html (substring matches in "
                    f"comments / attributes do not count)"
                )

    banner = row.get("banner")
    if isinstance(banner, dict):
        banner_path = banner.get("path")
        if isinstance(banner_path, str) and banner_path:
            from pathlib import Path as _P
            from backlink_publisher.config import _config_dir as _cfg_dir_module
            banner_resolved = _P(banner_path).resolve()
            allowed = (_cfg_dir_module() / "banners").resolve()
            if not banner_resolved.is_relative_to(allowed):
                errors_list.append(
                    f"banner_path outside allowed directory: {banner_path}"
                )
            elif not banner_resolved.exists():
                errors_list.append(
                    f"banner.path points to a file that does not exist: {banner_path}"
                )
            elif not banner.exists():  # type: ignore[attr-defined]
                errors_list.append(
                    f"banner.path points to a file that does not exist: {banner_path}"
                )

    row["validation"] = {
        "status": "failed" if errors_list else "passed",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings_list,
        "errors": errors_list,
    }
    return row
