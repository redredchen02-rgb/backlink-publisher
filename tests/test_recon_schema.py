"""Schema + round-trip tests for the RECON line contract.

Locks the previously-implicit text RECON format (debt ``no-recon-schema``)
so downstream string-match consumers stop being fragile. See
``src/backlink_publisher/_util/recon.py`` for the contract.
"""
from __future__ import annotations

__tier__ = "unit"

import io
import sys

import pytest

from backlink_publisher._util.recon import (
    emit_recon,
    format_recon_line,
    iter_recon_lines,
    parse_recon_line,
    RECONLine,
    ReconSchemaError,
)

# ── format_recon_line: canonical shape ────────────────────────────────────────

def test_minimal_line_is_recon_level_only() -> None:
    line = RECONLine(level="info", fields={})
    assert format_recon_line(line) == "RECON info"


@pytest.mark.parametrize("level", ["info", "warn", "error"])
def test_level_is_second_token(level: str) -> None:
    out = format_recon_line(RECONLine(level=level, fields={"k": "v"}))  # type: ignore[arg-type]
    assert out.split(" ")[:2] == ["RECON", level]


def test_fields_are_key_value_whitespace_splittable() -> None:
    out = format_recon_line(
        RECONLine(level="info", fields={"fetch_head_age_seconds": "12", "host": "x"})
    )
    tokens = out.split(" ")
    assert tokens[0] == "RECON"
    assert all("=" in t for t in tokens[2:])


def test_reason_field_always_emitted_last() -> None:
    out = format_recon_line(
        RECONLine(
            level="warn",
            fields={"fetch_skipped": "1", "reason": "host_gone", "age": "5"},
        )
    )
    assert out.endswith("reason=host_gone")
    # 'reason' must appear exactly once and be the final key=value token.
    tokens = out.split(" ")
    assert tokens[-1] == "reason=host_gone"


# ── value encoding ────────────────────────────────────────────────────────────

def test_value_with_space_is_percent_encoded() -> None:
    out = format_recon_line(RECONLine(level="warn", fields={"reason": "host gone"}))
    assert " " not in out.split(" ", 2)[2]  # no spaces inside the payload
    assert out.endswith("reason=host%20gone")
    assert parse_recon_line(out).fields["reason"] == "host gone"


def test_value_with_equals_is_percent_encoded() -> None:
    out = format_recon_line(RECONLine(level="info", fields={"expr": "a=b"}))
    tokens = out.split(" ")
    # exactly one '=' per field token (the key/value separator)
    assert all(t.count("=") == 1 for t in tokens[2:])
    assert parse_recon_line(out).fields["expr"] == "a=b"


def test_common_punctuation_stays_readable() -> None:
    """Operator-facing values (URLs, snake_case, dotted names) stay unescaped."""
    out = format_recon_line(
        RECONLine(level="info", fields={"endpoint": "https://x.y/p_q-r"})
    )
    assert "endpoint=https://x.y/p_q-r" in out


def test_multiline_value_rejected() -> None:
    with pytest.raises(ReconSchemaError, match="newline"):
        RECONLine(level="info", fields={"reason": "line1\nline2"})


# ── round-trip ────────────────────────────────────────────────────────────────

def test_round_trip_preserves_fields() -> None:
    original = RECONLine(
        level="warn",
        fields={"fetch_skipped": "1", "fetch_head_age_seconds": "300", "reason": "x"},
    )
    rendered = format_recon_line(original)
    parsed = parse_recon_line(rendered)
    assert parsed.level == original.level
    assert parsed.fields == original.fields


def test_round_trip_reason_last_invariant() -> None:
    for fields in [
        {"reason": "r", "a": "1"},
        {"a": "1", "reason": "r", "b": "2"},
        {"reason": "r"},
    ]:
        rendered = format_recon_line(RECONLine(level="error", fields=fields))
        parsed = parse_recon_line(rendered)
        assert list(parsed.fields.keys())[-1] == "reason"


# ── parse_recon_line: rejection cases ─────────────────────────────────────────

@pytest.mark.parametrize(
    "bad",
    [
        "not a recon line",
        "RECON",          # no level
        "RECON ",         # no level (trailing space stripped)
        "RECON debug x=1",  # unknown level
        "RECON info =v",     # empty key before '='
    ],
)
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(ReconSchemaError):
        parse_recon_line(bad)


def test_bare_flag_token_parses_to_empty_value() -> None:
    """Real-world contract: ``fetch_skipped`` (no =value) is a valid flag.

    plan-check emits ``RECON warn fetch_skipped reason=...`` — bare flag
    tokens are part of the contract, not malformed.
    """
    parsed = parse_recon_line("RECON warn fetch_skipped reason=offline")
    assert parsed.fields["fetch_skipped"] == ""
    assert parsed.fields["reason"] == "offline"
    # Round-trips: the bare flag renders back without '=value'.
    assert format_recon_line(parsed) == "RECON warn fetch_skipped reason=offline"


def test_construct_and_emit_bare_flag() -> None:
    """A field with FLAG_VALUE ('') emits as a bare token."""
    line = RECONLine(level="warn", fields={"fetch_skipped": "", "reason": "x"})
    assert format_recon_line(line) == "RECON warn fetch_skipped reason=x"


def test_construct_rejects_bad_level() -> None:
    with pytest.raises(ReconSchemaError, match="level"):
        RECONLine(level="debug", fields={})  # type: ignore[arg-type]


def test_construct_rejects_bad_key() -> None:
    with pytest.raises(ReconSchemaError, match="key"):
        RECONLine(level="info", fields={"bad key": "v"})
    with pytest.raises(ReconSchemaError, match="key"):
        RECONLine(level="info", fields={"k=v": "x"})


# ── emit_recon: side effect ───────────────────────────────────────────────────

def test_emit_recon_writes_canonical_line_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    emit_recon("info", fetch_head_age_seconds="12")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.rstrip() == "RECON info fetch_head_age_seconds=12"


def test_emit_recon_reason_last(capsys: pytest.CaptureFixture[str]) -> None:
    emit_recon("warn", fetch_skipped="1", reason="offline")
    captured = capsys.readouterr()
    assert captured.err.rstrip() == "RECON warn fetch_skipped=1 reason=offline"


def test_emit_recon_rejects_bad_level(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ReconSchemaError):
        emit_recon("trace", x="1")  # type: ignore[arg-type]
    assert capsys.readouterr().err == ""  # nothing emitted on rejection


# ── iter_recon_lines: streaming consumer ──────────────────────────────────────

def test_iter_skips_non_recon_lines() -> None:
    mixed = [
        "some banner line",
        "RECON info a=1",
        "another non-recon",
        "RECON warn b=2 reason=x",
    ]
    parsed = list(iter_recon_lines(mixed))
    assert len(parsed) == 2
    assert parsed[0].level == "info"
    assert parsed[1].fields["reason"] == "x"


def test_iter_skips_malformed_recon_line() -> None:
    # A malformed RECON line (unknown level) should not crash the consumer.
    # Note: 'RECON info bare' is now VALID (bare flag token) after the
    # contract accepted flag tokens — use an unknown level to get malformation.
    mixed = ["RECON info a=1", "RECON trace b=2", "RECON warn c=3"]
    parsed = list(iter_recon_lines(mixed))
    assert len(parsed) == 2  # the 'trace' line (unknown level) is skipped


# ── contract vs real-world lines already in the repo ──────────────────────────
# These are the actual RECON shapes emitted by plan-check and publish-backlinks.
# If the contract can't parse them, the schema diverges from reality.

REAL_RECON_LINES = [
    "RECON info fetch_head_age_seconds=12",
    "RECON info fetch_head_age_seconds=null",
    "RECON warn fetch_skipped reason=offline fetch_head_age_seconds=300",
    "RECON info command=publish-backlinks row_count=5 mode=draft",
    "RECON info command=publish-backlinks phase=complete published=3 failed=0",
]


@pytest.mark.parametrize("line", REAL_RECON_LINES)
def test_real_repo_recon_lines_parse(line: str) -> None:
    """Every real RECON line shape currently emitted must parse under the schema.

    If this fails, the contract has drifted from what the CLI actually emits —
    either fix the contract or fix the emitter, but do not let them diverge
    silently (that is exactly the ``no-recon-schema`` failure mode).
    """
    parsed = parse_recon_line(line)
    assert parsed.level in {"info", "warn", "error"}
    # Render-parse round-trip is field-order-insensitive because format_recon
    # canonicalises order; compare as dicts.
    re_rendered = format_recon_line(parsed)
    re_parsed = parse_recon_line(re_rendered)
    assert re_parsed.fields == parsed.fields
