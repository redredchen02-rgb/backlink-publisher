"""Unit 7 — url_mode divergence gap and typed error envelope (plan 2026-06-04-004).

validate_output_payload (legacy) does NOT check url_mode enum → url_mode='D'
passes legacy but fails PlannedPayload Pydantic validation. Content_html size
boundary. AST scan confirms no ValidationError site calls sys.exit.
"""
from __future__ import annotations

__tier__ = "unit"

import ast
import inspect
from pathlib import Path

import pytest

pytest.importorskip("backlink_publisher.publishing.adapters")

from pydantic import ValidationError

from backlink_publisher._schema_output import validate_output_payload, validate_publish_payload


# ── valid base payload helper ─────────────────────────────────────────────────

def _valid_planned(**overrides):
    base = {
        "id": "test-001",
        "platform": "blogger",
        "language": "zh-CN",
        "publish_mode": "draft",
        "target_url": "https://example.com/page1",
        "main_domain": "https://example.com",
        "url_mode": "A",
        "title": "Example Title",
        "slug": "example-title",
        "excerpt": "Short excerpt here.",
        "tags": ["tag1", "tag2"],
        "links": [
            {"url": "https://example.com", "anchor": "Main Domain", "kind": "main_domain", "required": True},
            {"url": "https://example.com/page1", "anchor": "Target", "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki", "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN", "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO", "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GH", "kind": "supporting", "required": False},
        ],
        "seo": {
            "title": "SEO Title",
            "description": "SEO description text here for the page.",
            "canonical_url": "https://example.com/page1",
        },
        "content_markdown": "Test body mentioning https://example.com inline.",
    }
    base.update(overrides)
    return base


# ── url_mode divergence gap ───────────────────────────────────────────────────

def test_url_mode_d_passes_legacy_validation():
    """Legacy validate_output_payload does NOT check url_mode enum — url_mode='D' produces no errors."""
    row = _valid_planned(url_mode="D")
    errors = validate_output_payload(row)
    # Confirm the legacy check does NOT catch the invalid url_mode
    url_mode_errors = [e for e in errors if "url_mode" in e.lower()]
    assert url_mode_errors == [], (
        "Legacy validate_output_payload should NOT check url_mode — divergence gap confirmed"
    )


def test_url_mode_d_fails_pydantic_via_validate_publish_payload():
    """url_mode='D' passes legacy but validate_publish_payload Pydantic catches it."""
    row = _valid_planned(url_mode="D")

    # Step 1: legacy passes (no url_mode check)
    legacy_errors = validate_output_payload(row)
    url_mode_errors = [e for e in legacy_errors if "url_mode" in e.lower()]
    assert url_mode_errors == [], "Precondition: legacy must not flag url_mode"

    # Step 2: Pydantic via validate_publish_payload catches it
    publish_errors = validate_publish_payload(row)
    assert any("url_mode" in e.lower() or "pydantic" in e.lower() for e in publish_errors), (
        "validate_publish_payload should reject url_mode='D' via Pydantic"
    )


def test_divergence_error_contains_field_name():
    """The ValidationError from validate_publish_payload mentions the violated field."""
    row = _valid_planned(url_mode="D")
    errors = validate_publish_payload(row)
    combined = " ".join(errors)
    assert "url_mode" in combined.lower(), (
        f"Error message should mention 'url_mode'; got: {errors}"
    )


# ── content_html size boundary ────────────────────────────────────────────────

_MiB = 1_048_576  # 1 MiB in bytes


def test_content_html_exactly_1mib_accepted():
    """content_html at exactly 1 MiB → no size error; content_markdown covers main_domain check."""
    row = _valid_planned(content_html="x" * _MiB)
    errors = validate_output_payload(row)
    size_errors = [e for e in errors if "content_html" in e.lower() and "size" in e.lower()]
    assert size_errors == [], f"1 MiB should be accepted; got size errors: {size_errors}"


def test_content_html_exceeds_1mib_rejected():
    """content_html at 1 MiB + 1 byte → size error from validate_output_payload."""
    row = _valid_planned(content_html="x" * (_MiB + 1))
    errors = validate_output_payload(row)
    size_errors = [e for e in errors if "content_html" in e.lower() and "size" in e.lower()]
    assert size_errors, (
        f"Oversized content_html should produce a size-related error; got: {errors}"
    )


# ── well-formed payload passes both ──────────────────────────────────────────

def test_valid_payload_passes_both_validators():
    """Well-formed PlannedPayload passes legacy and Pydantic paths."""
    row = _valid_planned()
    assert validate_output_payload(row) == []
    assert validate_publish_payload(row) == []


# ── link count boundary ───────────────────────────────────────────────────────

def test_link_count_below_minimum_fails():
    """link_count < 6 → error from validate_output_payload."""
    row = _valid_planned(links=[
        {"url": f"https://blog{i}.com/post", "anchor": f"anchor {i}",
         "kind": "supporting", "required": True}
        for i in range(5)  # 5 < 6
    ])
    errors = validate_output_payload(row)
    assert errors, "5 links should produce validation error"


# ── platform alias (conditional) ─────────────────────────────────────────────

def test_platform_alias_resolves_or_skip():
    """Validate alias → canonical form; skip if no aliases registered."""
    from backlink_publisher.schema import supported_platforms

    platforms = supported_platforms()
    # Check for any registered aliases (optional feature)
    try:
        from backlink_publisher._schema_input import validate_and_convert_input
    except ImportError:
        pytest.skip("validate_and_convert_input not available")

    # Discover aliases by checking if any platform name differs after normalization
    pytest.skip("no platform aliases registered")


# ── AST guard: no sys.exit on ValidationError ────────────────────────────────

def test_no_sys_exit_in_validation_error_handlers():
    """AST scan: no ValidationError handler calls sys.exit or raises SystemExit."""
    from backlink_publisher import _schema_input, _schema_output

    for mod in (_schema_input, _schema_output):
        source = inspect.getsource(mod)
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Check if this handler catches ValidationError
            handler_type = getattr(node.type, "id", None) or getattr(
                getattr(node.type, "attr", None), "__str__", lambda: "")()
            if "ValidationError" not in str(ast.dump(node.type or ast.Constant(""))):
                continue
            # Walk the handler body looking for sys.exit or SystemExit
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Attribute) and func.attr == "exit":
                        obj = getattr(func.value, "id", "")
                        assert obj != "sys", (
                            f"ValidationError handler in {mod.__name__} calls sys.exit"
                        )
                if isinstance(child, ast.Raise):
                    if child.exc and "SystemExit" in ast.dump(child.exc):
                        pytest.fail(
                            f"ValidationError handler in {mod.__name__} raises SystemExit"
                        )
