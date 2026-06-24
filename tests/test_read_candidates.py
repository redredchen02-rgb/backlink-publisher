"""Tests for _read_candidates / _validate_candidate — Plan 2026-05-27-006 Unit 1.

Unit 1 test scenarios (this file covers):
- Happy path: a 3-record JSONL stream parses to 3 internal records.
- Happy path: JSON object and JSON array parse the same as equivalent JSONL.
- Edge case: empty stdin / empty file → exit 0, empty stdout, stderr summary "0".
- Edge case: record count = --max-records passes; count+1 → InputValidationError exit 2.
- Edge case: raw input > --max-input-bytes → exit 2 before parse.
- Error path: record missing target_url/anchor_text → rejected row, batch continues.
"""
from __future__ import annotations

__tier__ = "unit"
import json

import pytest


# ── _read_candidates unit tests ───────────────────────────────────────────────


def test_read_candidates_jsonl_three_records():
    """3-record JSONL stream parses to 3 dicts."""
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    jsonl = "\n".join([
        '{"target_url": "https://a.com/", "anchor_text": "A", "mode": "comment"}',
        '{"target_url": "https://b.com/", "anchor_text": "B", "mode": "article"}',
        '{"target_url": "https://c.com/", "anchor_text": "C", "mode": "comment"}',
    ])
    result = _read_candidates(jsonl)
    assert len(result) == 3
    assert result[0]["anchor_text"] == "A"
    assert result[2]["target_url"] == "https://c.com/"


def test_read_candidates_json_object_wraps_to_list():
    """Single JSON object parses identically to a 1-record JSONL."""
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    obj = {"target_url": "https://x.com/", "anchor_text": "x", "mode": "comment"}
    result_obj = _read_candidates(json.dumps(obj))
    result_jsonl = _read_candidates(json.dumps(obj))
    assert len(result_obj) == 1
    assert result_obj[0] == result_jsonl[0]


def test_read_candidates_json_array():
    """JSON array parses to same record list as equivalent JSONL."""
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    records = [
        {"target_url": "https://a.com/", "anchor_text": "A", "mode": "comment"},
        {"target_url": "https://b.com/", "anchor_text": "B", "mode": "article"},
    ]
    from_array = _read_candidates(json.dumps(records))
    from_jsonl = _read_candidates(
        '{"target_url": "https://a.com/", "anchor_text": "A", "mode": "comment"}\n'
        '{"target_url": "https://b.com/", "anchor_text": "B", "mode": "article"}'
    )
    assert from_array == from_jsonl


def test_read_candidates_empty_input_returns_empty_list():
    """Empty input → empty list (R5b)."""
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    assert _read_candidates("") == []
    assert _read_candidates("   \n  ") == []


def test_read_candidates_max_input_bytes_exceeded_raises():
    """Raw input > max_input_bytes → InputValidationError (exit 2)."""
    from backlink_publisher._util.errors import InputValidationError
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    big_text = "x" * 100
    with pytest.raises(InputValidationError, match="max-input-bytes"):
        _read_candidates(big_text, max_input_bytes=50)


def test_read_candidates_exactly_max_records_passes():
    """Record count == max_records: no error."""
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    lines = [
        '{"target_url": "https://x.com/", "anchor_text": "a", "mode": "comment"}'
    ] * 5
    result = _read_candidates("\n".join(lines), max_records=5)
    assert len(result) == 5


def test_read_candidates_max_records_exceeded_raises():
    """Record count > max_records → InputValidationError (exit 2)."""
    from backlink_publisher._util.errors import InputValidationError
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    lines = [
        '{"target_url": "https://x.com/", "anchor_text": "a", "mode": "comment"}'
    ] * 6
    with pytest.raises(InputValidationError, match="max-records"):
        _read_candidates("\n".join(lines), max_records=5)


def test_read_candidates_skips_malformed_jsonl_lines():
    """Malformed JSONL lines are silently skipped (strict=False semantics)."""
    from backlink_publisher.cli.generate_backlink_text import _read_candidates

    text = (
        '{"target_url": "https://a.com/", "anchor_text": "A", "mode": "comment"}\n'
        'NOT JSON !!!\n'
        '{"target_url": "https://b.com/", "anchor_text": "B", "mode": "article"}'
    )
    result = _read_candidates(text)
    assert len(result) == 2


# ── _validate_candidate unit tests ────────────────────────────────────────────


def test_validate_candidate_valid_record_normalises():
    """Valid record with all required fields is normalised (no status key = not rejected)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_candidate

    rec = {"target_url": "https://example.com/page", "anchor_text": "click me", "mode": "comment"}
    result = _validate_candidate(rec)
    # Valid records carry the normalised fields, no "status" or "rejection_reason".
    assert result.get("status") != "rejected"
    assert "rejection_reason" not in result
    assert result["target_url"] == "https://example.com/page"
    assert result["anchor_text"] == "click me"
    assert result["mode"] == "comment"


def test_validate_candidate_missing_target_url_rejected():
    """Missing target_url → rejected with invalid_record."""
    from backlink_publisher.cli.generate_backlink_text import _validate_candidate

    rec = {"anchor_text": "anchor", "mode": "comment"}
    result = _validate_candidate(rec)
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "invalid_record"


def test_validate_candidate_missing_anchor_text_rejected():
    """Missing anchor_text → rejected with invalid_record."""
    from backlink_publisher.cli.generate_backlink_text import _validate_candidate

    rec = {"target_url": "https://example.com/", "mode": "comment"}
    result = _validate_candidate(rec)
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "invalid_record"


def test_validate_candidate_http_url_rejected():
    """Non-https target_url → rejected with bad_target_url_scheme."""
    from backlink_publisher.cli.generate_backlink_text import _validate_candidate

    rec = {"target_url": "http://example.com/", "anchor_text": "a", "mode": "comment"}
    result = _validate_candidate(rec)
    assert result["status"] == "rejected"
    assert "scheme" in result["rejection_reason"]


def test_validate_candidate_malformed_ipv6_url_rejected():
    """Malformed IPv6 target_url → rejected (urlparse ValueError guarded)."""
    from backlink_publisher.cli.generate_backlink_text import _validate_candidate

    rec = {"target_url": "https://[invalid", "anchor_text": "a", "mode": "comment"}
    result = _validate_candidate(rec)
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "invalid_record"


def test_validate_candidate_extra_fields_preserved():
    """Extra fields in the record are preserved in the normalised output."""
    from backlink_publisher.cli.generate_backlink_text import _validate_candidate

    rec = {
        "target_url": "https://example.com/",
        "anchor_text": "anchor",
        "mode": "comment",
        "language": "zh-CN",
        "extra_field": "foo",
    }
    result = _validate_candidate(rec)
    assert result.get("language") == "zh-CN"
    assert result.get("extra_field") == "foo"
