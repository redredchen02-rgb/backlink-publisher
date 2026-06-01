"""Wave 1 Unit 4: flip-or-kill enforcement for canary-pending channels.

Closes the P0 rot risk: a markdown deadline that nothing reads is fire-and-forget.
This test parses ``docs/discovery/canary-pending.md`` and FAILS once a channel's
deadline passes while it is still registered ``dofollow="uncertain"`` — forcing the
operator to either flip it to ``True`` (after an OUR-pipeline canary) or retire it.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

import backlink_publisher.publishing.adapters  # noqa: F401 — populate the registry
from backlink_publisher.publishing.registry import dofollow_status, registered_platforms

_TRACKER = Path(__file__).parents[1] / "docs" / "discovery" / "canary-pending.md"
_ROW_RE = re.compile(r"^\|\s*([a-z0-9_]+)\s*\|\s*([\d-]+)\s*\|\s*([\d-]+)\s*\|\s*(\w+)\s*\|$")


def _parse_rows():
    text = _TRACKER.read_text(encoding="utf-8")
    block = text.split("<!-- canary-pending:begin -->", 1)[1].split("<!-- canary-pending:end -->", 1)[0]
    rows = []
    for line in block.splitlines():
        m = _ROW_RE.match(line.strip())
        if m:
            rows.append({
                "platform": m.group(1),
                "registered": m.group(2),
                "deadline": date.fromisoformat(m.group(3)),
                "status": m.group(4),
            })
    return rows


def test_tracker_file_exists_and_parses():
    assert _TRACKER.exists(), f"missing tracker: {_TRACKER}"
    rows = _parse_rows()
    assert rows, "canary-pending tracker has no parseable rows"


@pytest.mark.parametrize("row", _parse_rows(), ids=lambda r: r["platform"])
def test_pending_channel_not_past_deadline(row):
    """A pending channel past its deadline while still 'uncertain' fails CI."""
    if row["status"] != "pending":
        return  # flipped / retired rows are checked for consistency below
    if dofollow_status(row["platform"]) != "uncertain":
        return  # already flipped/retired in the registry; row is just stale
    assert date.today() <= row["deadline"], (
        f"{row['platform']} is past its canary deadline ({row['deadline']}) but is "
        f"still registered dofollow=\"uncertain\". Run the OUR-pipeline canary and "
        f"either flip it to dofollow=True or retire it — see docs/discovery/canary-pending.md."
    )


@pytest.mark.parametrize("row", _parse_rows(), ids=lambda r: r["platform"])
def test_row_consistent_with_registry(row):
    """A 'flipped' row must be dofollow=True in the registry; 'pending' must be registered."""
    assert row["platform"] in registered_platforms(), (
        f"{row['platform']} is in the canary tracker but not registered"
    )
    if row["status"] == "flipped":
        assert dofollow_status(row["platform"]) is True, (
            f"{row['platform']} is marked 'flipped' but registry shows "
            f"{dofollow_status(row['platform'])!r}"
        )
