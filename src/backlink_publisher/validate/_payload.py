"""Payload enhancement helpers — pure validation compute.

Moved from ``cli/_validate_payload.py`` to resolve a layer violation
(``validate/engine.py`` was importing from ``cli/``). All functions are
pure validators: they never touch stdin/stdout, argparse, or sys.argv.

Contains ``_enhance_payload`` and all its exclusive helper functions:
``_HrefCollector``, ``_extract_hrefs_from_html``, ``_check_main_domain_in_html``,
``_resolve_branded_pool``, ``_nfc_normalize_in_place``, ``_detect_row_body_language``.

cli/_validate_payload.py is a thin re-export shim for backward-compat (tests
that patch backlink_publisher.cli._validate_payload.X still work because the
shim re-imports from here at module load time).

(Plan 2026-06-24-002 U5)
"""

from __future__ import annotations

from datetime import datetime, UTC
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast
import unicodedata
from urllib.parse import urlsplit

from backlink_publisher._util.logger import validate_logger
from backlink_publisher.anchor.lang import check_anchor_language
from backlink_publisher.config import _config_dir, Config, get_anchor_pool_v2
from backlink_publisher.linkcheck.language import (
    detect_language_from_html,
    detect_language_from_markdown,
    language_matches,
    SUPPORTED_LANGUAGES,
)
from ..schema import _is_field_present


def _resolve_branded_pool(row: dict[str, Any], config: Config | None) -> list[str]:
    """Return the branded_pool to use for R4 exemption checks.

    Resolution order (per plan 2026-05-14-001):
    1. ``row.metadata.branded_pool`` snapshot emitted by plan-backlinks.
       Closes the validate→publish TOCTOU window — the snapshot is what
       plan-time considered branded.
    2. Live ``get_anchor_pool_v2`` lookup against the loaded config.
       Fallback for older JSONL produced before this PR shipped.
    3. Empty list. The gate proceeds with no exemption; legitimate Latin
       brand-name anchors will fail R4. Surfaced via a one-time WARN per
       row so the operator notices.
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
    """Stdlib HTML parser subclass that collects ``<a href>`` attribute values.

    Plan 2026-05-18-006 Unit 6 R3 host-parse + Threat Model anti-injection:
    extract real href values from ``content_html`` so the main_domain check
    cannot be bypassed by placing ``main_domain`` inside ``data-*`` attributes,
    HTML comments, or non-linking text nodes.
    """

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
    """Return a list of all ``<a href>`` attribute values in ``html``.

    Stdlib ``html.parser`` is permissive about malformed HTML; the validate
    gate's job is to inspect the hrefs the parser actually finds, not to
    validate HTML well-formedness.
    """
    if not isinstance(html, str) or not html.strip():
        return []
    collector = _HrefCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:
        return collector.hrefs
    return collector.hrefs


def _check_main_domain_in_html(html: str, main_domain_normalized: str) -> bool:
    """Plan 2026-05-18-006 Unit 6 R3: verify ``main_domain_normalized`` is the
    host of at least one ``<a href>`` link in ``html``. Closes the
    subdomain-spoof / userinfo-injection / javascript-href / data-href /
    Punycode-spoof attack surface.

    Implementation contract (R3 6-step):
    1. Parse hrefs via stdlib :class:`HTMLParser` (collected in
       :class:`_HrefCollector`).
    2. ``urlsplit`` each href; ValueError → treat as non-matching.
    3. Pre-IDN-encode rejects: scheme.lower() not in {http, https};
       userinfo (username / password) set; hostname None or empty;
       hostname contains ``:`` (IPv6 literals — out of v1); whitespace
       or control codepoints in hostname.
    4. IDN-encode hostname to ASCII punycode via stdlib ``encodings.idna``
       (the encode-failure-on-overflow safety net for label > 63 octets).
    5. Match rule: ``hostname_ascii == main_domain_normalized`` OR
       ``hostname_ascii.endswith("." + main_domain_normalized)``. The
       leading dot prevents ``evil-main-domain.com`` matching
       ``main-domain.com`` as a suffix.
    6. Return True if any href matches; else False.

    ``main_domain_normalized`` is the punycode-form host produced by
    :func:`backlink_publisher.schema._normalize_main_domain` at Unit 1
    schema-time, stored on the row as ``main_domain_normalized``.
    """
    if not main_domain_normalized:
        return False
    target_host = main_domain_normalized.strip().lower()
    target_suffix = "." + target_host

    for href in _extract_hrefs_from_html(html):
        try:
            parsed = urlsplit(href.strip())
        except ValueError:
            continue

        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            continue

        # Userinfo (username/password) reject — closes
        # `https://main-domain.com@evil.com/` injection
        if parsed.username or parsed.password:
            continue

        host = parsed.hostname
        if host is None or host == "":
            continue

        # IPv6 detection — urlsplit strips brackets, so check for colon
        if ":" in host:
            continue

        # Whitespace / control codepoints in host
        if any(c.isspace() or unicodedata.category(c).startswith("C") for c in host):
            continue

        try:
            hostname_ascii = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            # Label-length overflow / reserved chars — treat as non-matching
            continue

        if hostname_ascii == target_host or hostname_ascii.endswith(target_suffix):
            return True

    return False


def _nfc_normalize_in_place(row: dict[str, Any]) -> None:
    """Plan 2026-05-18-006 Unit 6 R13 + Hangul Jamo deferred-question
    resolution: apply NFC normalization to row-resident string fields at
    validate-time entry.

    Closes the macOS-NFD risk that splits Hangul Syllables into Jamo
    codepoints outside ``U+AC00..U+D7AF`` and defeats the ko codepoint
    short-circuit. ``zh-CN`` / ``en`` / ``ru`` paths unaffected because
    their codepoint ranges don't decompose.

    Row-level fields normalized: ``content_markdown``, ``content_html``,
    and each ``link["anchor"]``. ``branded_pool`` / ``anchor_keywords``
    are config-resident (not on the row) and get NFC at Unit 7 config-load.
    """
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
    """Plan 2026-05-18-006 Unit 6 R15: dispatch body-language detection by
    source-field presence. Returns ``(detected, source_used)`` where
    ``source_used`` is one of ``"markdown"``, ``"html"``, ``"both-match"``,
    ``"both-mismatch:<md>/<html>"``, or ``"absent"``.

    Field-presence semantics: a field is present iff non-empty + non-whitespace
    string (see ``schema._is_field_present``). Whitespace-only strings are
    treated as absent for dispatch.

    Both-present rule (R3 / R15 strict mode): run both detectors; if they
    disagree, return ``"unknown"`` and a mismatch tag so the caller can emit
    a clear validation error. If they agree, return the agreed language.
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
        # Disagreement: surface as "unknown" so language_matches's escape
        # valve doesn't accidentally pass; the caller separately emits the
        # mismatch error using the explicit tag.
        return "unknown", f"both-mismatch:md={md_lang}/html={html_lang}"

    if md_present:
        return detect_language_from_markdown(cast(str, md)), "markdown"
    if html_present:
        return detect_language_from_html(cast(str, html)), "html"
    return "unknown", "absent"


def _resolve_banner_path(banner: dict[str, Any]) -> str | None:
    """Resolve and validate the banner ``path`` field.

    Returns ``None`` (pass) or an error message string.

    Extracted from ``_enhance_payload`` (Plan 2026-06-24-002 U5).
    """
    banner_path = banner.get("path")
    if not isinstance(banner_path, str) or not banner_path:
        return None  # absent or status-only dicts pass through

    banner_resolved = Path(banner_path).resolve()
    allowed = (_config_dir() / "banners").resolve()
    if not banner_resolved.is_relative_to(allowed):
        return f"banner_path outside allowed directory: {banner_path}"
    if not banner_resolved.exists():
        return f"banner.path points to a file that does not exist: {banner_path}"
    return None


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
                    validate_logger.warning(
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
    ``validation.warnings`` is preserved as an empty list for back-compat
    (test_validate_backlinks.py:189 asserts shape).
    """
    errors_list: list[str] = []
    warnings_list: list[str] = []

    # Plan 2026-05-18-006 Unit 6: NFC-normalize row-resident string fields
    # before any codepoint-dependent gate runs. Closes the macOS-NFD risk
    # that splits Hangul Syllables outside U+AC00..U+D7AF.
    _nfc_normalize_in_place(row)

    requested = row.get("language", "")

    # R3 enum guard — non-enum row.language skips R2/R4 with a WARN.
    if requested not in SUPPORTED_LANGUAGES:
        validate_logger.warning(
            f"row {row.get('id', '?')}: language '{requested}' outside enum "
            f"{sorted(SUPPORTED_LANGUAGES)}; skipping language and anchor gates"
        )
    else:
        # R2 / R15: body-language match.
        detected, source_used = _detect_row_body_language(row)
        _check_body_language_gate(row, detected, source_used, requested, errors_list, warnings_list)

        # R4/R5: per-anchor codepoint check for kind in {main_domain, target}.
        branded_pool = _resolve_branded_pool(row, config)
        for idx, link in enumerate(row.get("links", [])):
            anchor = link.get("anchor", "") if isinstance(link, dict) else ""
            kind = link.get("kind", "") if isinstance(link, dict) else ""
            ok, reason = check_anchor_language(anchor, requested, kind, branded_pool)
            if not ok:
                errors_list.append(
                    f"link[{idx}] anchor {anchor!r} failed: {reason}"
                )

    # Plan 2026-05-18-006 Unit 6 R3: HTML host-parse main_domain check.
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

    # Plan 2026-05-20-001 Unit 4: validate optional banner field.
    banner = row.get("banner")
    if isinstance(banner, dict):
        err = _resolve_banner_path(banner)
        if err is not None:
            errors_list.append(err)

    row["validation"] = {
        "status": "failed" if errors_list else "passed",
        "checked_at": datetime.now(UTC).isoformat(),
        "warnings": warnings_list,
        "errors": errors_list,
    }
    return row
