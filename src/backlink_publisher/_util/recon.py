"""RECON line schema, emitter, and parser.

Status: formalising the previously-ad-hoc text contract (debt
``no-recon-schema``). Two RECON surfaces coexist in this repo:

1. **JSON recon** — ``PipelineLogger.recon()`` in ``_util/logger.py`` emits a
   full structured record ``{"ts":..., "level":"RECON", "logger":..., "msg":...,
   ...extra}`` to stderr. This is the rich, machine-readable path used by the
   pipeline loggers (plan/validate/publish/opencli).

2. **Text RECON** — CLI tools emit a compact grep-friendly line to stderr:

       RECON <level> <key>=<value> <key>=<value> ...

   ``<level>`` ∈ ``{info, warn, error}``. This is the operator-grep target
   documented across ``plan-check``, ``canary-seed``, ``cull-channels``,
   ``preflight-targets``, ``publish-backlinks``, etc. Until this module landed
   the format was implicit — every call site hand-wrote the f-string, and
   downstream consumers could only string-match.

This module does NOT migrate existing text call sites (that is a tracked,
incremental follow-up). It provides:

- ``RECONLine`` — a typed shape for the text contract.
- ``emit_recon()`` — the canonical emitter; new code uses this instead of
  hand-rolling an f-string, so the level vocabulary and key=value escaping stay
  consistent.
- ``parse_recon_line()`` — the inverse; downstream tooling (alerting,
  aggregation, the future ``debt-report`` freshness pass) parses with this
  instead of bespoke regex, so a drifted field no longer silently breaks
  consumers.
- ``format_recon_line()`` — pure formatter used by both ``emit_recon`` and the
  tests; round-trips with ``parse_recon_line``.

Contract guarantees
-------------------
- The literal token ``RECON`` is always the first whitespace-delimited field.
- Level is always the second field and is one of ``info`` / ``warn`` / ``error``.
- Every subsequent field is either:
  * ``key=value`` (no spaces around ``=``; values containing whitespace or
    ``=`` are percent-encoded so the line is whitespace-splittable), or
  * a bare flag token ``key`` (no ``=``) — parses to ``fields["key"] = ""``.
  Bare flags are part of the real-world contract: ``plan-check`` emits
  ``RECON warn fetch_skipped reason=...`` where ``fetch_skipped`` carries no
  value. Treat an empty string value as "flag present".
- A field named ``reason`` is reserved for human-readable failure context and
  is always emitted last when present (stable grep ordering).
"""
from __future__ import annotations

import sys
import urllib.parse
from dataclasses import dataclass, field
from typing import Iterable, Literal

ReconLevel = Literal["info", "warn", "error"]
_VALID_LEVELS: frozenset[str] = frozenset({"info", "warn", "error"})
# Sentinel: a bare-flag token (no '=') parses to this empty-string value, so
# downstream consumers can treat presence as truthy via ``fields.get(k) is not None``.
FLAG_VALUE = ""


class ReconSchemaError(ValueError):
    """Raised when a RECON line violates the documented contract."""


@dataclass(frozen=True)
class RECONLine:
    """Typed shape of a text RECON line.

    ``fields`` is an ordered mapping — order is preserved on emit so the
    ``reason`` field always lands last (stable grep ordering for operators).
    A bare flag token (e.g. ``fetch_skipped``) is stored with value ``""``.
    """

    level: ReconLevel
    fields: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in _VALID_LEVELS:
            raise ReconSchemaError(
                f"RECON level {self.level!r} is not in {sorted(_VALID_LEVELS)}"
            )
        for k, v in self.fields.items():
            if not k:
                raise ReconSchemaError("RECON field key must be non-empty")
            if "=" in k or " " in k:
                raise ReconSchemaError(
                    f"RECON field key {k!r} must not contain '=' or whitespace"
                )
            if "\n" in v or "\r" in v:
                raise ReconSchemaError(
                    f"RECON field {k!r} value contains a newline — emit one "
                    f"RECON line per event, never multi-line."
                )


def _encode_value(value: str) -> str:
    """Percent-encode ``=`` and whitespace so the field is splittable.

    Keeps common ASCII punctuation readable (``/``, ``:``, ``-``, ``.``, ``_``)
    so operator-facing values like ``fetch_head_age_seconds=12`` and
    ``reason=host_gone`` stay human-grepable; only the structurally ambiguous
    chars (``=``, space, tab, newline) are escaped.
    """
    return urllib.parse.quote(str(value), safe="!\"#$%&'()*+,-./:;<>?@[]^_`{|}~")


def _decode_value(encoded: str) -> str:
    return urllib.parse.unquote(encoded)


def format_recon_line(line: RECONLine) -> str:
    """Render a :class:`RECONLine` to its canonical text form.

    ``reason`` (when present) is emitted last for stable grep ordering; all
    other fields preserve insertion order. A field whose value is the
    ``FLAG_VALUE`` sentinel (empty string) is emitted as a bare flag token
    (``key`` with no ``=value``), matching the real-world contract (e.g.
    ``fetch_skipped``).
    """
    parts = ["RECON", line.level]
    items = list(line.fields.items())
    # Stable ordering: 'reason' always last (operator-facing failure context).
    if "reason" in line.fields:
        reason_val = line.fields["reason"]
        items = [(k, v) for k, v in items if k != "reason"] + [("reason", reason_val)]
    for k, v in items:
        if v == FLAG_VALUE:
            parts.append(k)  # bare flag token
        else:
            parts.append(f"{k}={_encode_value(v)}")
    return " ".join(parts)


def parse_recon_line(text: str) -> RECONLine:
    """Parse a canonical text RECON line back to :class:`RECONLine`.

    Inverse of :func:`format_recon_line`. Raises :class:`ReconSchemaError` if
    ``text`` is not a RECON line or violates the contract (unknown level, field
    with empty key). A bare token without ``=`` (e.g. ``fetch_skipped``) parses
    to ``fields["fetch_skipped"] = ""`` — i.e. a present flag.
    """
    stripped = text.strip()
    if not stripped.startswith("RECON "):
        raise ReconSchemaError(
            f"not a RECON line (missing 'RECON ' prefix): {text!r}"
        )
    tokens = stripped.split(" ")
    # tokens[0] == "RECON"; tokens[1] == level; rest are key=value or bare flags.
    if len(tokens) < 2:
        raise ReconSchemaError(f"RECON line has no level: {text!r}")
    level = tokens[1]
    if level not in _VALID_LEVELS:
        raise ReconSchemaError(
            f"RECON level {level!r} is not in {sorted(_VALID_LEVELS)}: {text!r}"
        )
    fields: dict[str, str] = {}
    for tok in tokens[2:]:
        if "=" in tok:
            k, _, encoded = tok.partition("=")
            if not k:
                raise ReconSchemaError(
                    f"RECON field with empty key in {tok!r}: {text!r}"
                )
            fields[k] = _decode_value(encoded)
        else:
            # Bare flag token (no '='). The real-world contract permits these
            # (plan-check emits ``RECON warn fetch_skipped reason=...``).
            # A leading '=' on a token parses as empty key and is rejected above
            # via the partition branch; a token that is ONLY '=' falls here and
            # is treated as an empty key flag, which is invalid.
            if not tok:
                raise ReconSchemaError(
                    f"RECON line has an empty token: {text!r}"
                )
            fields[tok] = FLAG_VALUE
    return RECONLine(level=level, fields=fields)  # type: ignore[arg-type]


def emit_recon(
    level: ReconLevel,
    *,
    reason: str | None = None,
    **fields: str,
) -> None:
    """Emit a canonical text RECON line to stderr.

    New code calls this instead of hand-writing ``print(f"RECON ...", ...)`` so
    the level vocabulary, key=value escaping, and ``reason``-last ordering stay
    consistent across the codebase. Existing hand-rolled sites remain valid
    (they already match this contract); migration is a tracked, incremental
    follow-up, not a prerequisite.

    Parameters
    ----------
    level:
        One of ``info`` / ``warn`` / ``error``.
    reason:
        Optional human-readable failure context. Emitted as the ``reason=…``
        field, always last, so ``grep 'RECON warn.*reason='`` finds every
        advisory failure regardless of which other fields are present.
    **fields:
        Arbitrary ``key=value`` payload. Values are percent-encoded for
        whitespace/``=`` safety; common punctuation stays readable.
    """
    if reason is not None:
        fields = {**fields, "reason": reason}
    line = RECONLine(level=level, fields=fields)
    print(format_recon_line(line), file=sys.stderr, flush=True)


def iter_recon_lines(lines: Iterable[str]) -> Iterable[RECONLine]:
    """Yield :class:`RECONLine` for every RECON line in ``lines``; skip non-RECON.

    For downstream consumers (aggregation, alerting) reading a stderr capture:
    lets them stream-parse without raising on interleaved non-RECON output.
    """
    for raw in lines:
        if raw.lstrip().startswith("RECON "):
            try:
                yield parse_recon_line(raw)
            except ReconSchemaError:
                # A malformed RECON line is itself a signal — but a consumer
                # streaming a capture should not crash on one bad line. Skip.
                continue
