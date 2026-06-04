"""OPT1: atomic_write_jsonl streams O(1) via atomic_write_stream (no full-doc buffer).

Built for docs/plans/2026-06-01-003 OPT1. Characterization-first: the streamed
output is asserted byte-identical to the prior StringIO-buffered output.
"""
__tier__ = "unit"
import json
import tracemalloc
from io import StringIO
from pathlib import Path

import pytest

from backlink_publisher._util.jsonl import atomic_write_jsonl, write_jsonl
from backlink_publisher.persistence.safe_write import atomic_write, atomic_write_stream


def _rows(n, payload_len=200):
    return [{"i": i, "data": "x" * payload_len} for i in range(n)]


def test_jsonl_byte_identical_to_legacy_stringio(tmp_path: Path):
    """Characterization: streamed output == prior StringIO-buffered output, byte for byte."""
    rows = _rows(50)
    buf = StringIO()
    write_jsonl(rows, buf)
    expected = buf.getvalue().encode("utf-8")
    target = tmp_path / "out.jsonl"
    atomic_write_jsonl(rows, target)
    assert target.read_bytes() == expected


def test_jsonl_mode_0600(tmp_path: Path):
    target = tmp_path / "out.jsonl"
    atomic_write_jsonl(_rows(3), target)
    assert (target.stat().st_mode & 0o777) == 0o600


def test_jsonl_empty_rows(tmp_path: Path):
    target = tmp_path / "empty.jsonl"
    atomic_write_jsonl([], target)
    assert target.exists()
    assert target.read_bytes() == b""


def test_jsonl_accepts_generator(tmp_path: Path):
    """Rows may be a lazy generator — the streaming consumer must accept it."""
    target = tmp_path / "gen.jsonl"
    atomic_write_jsonl((r for r in _rows(10)), target)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    assert json.loads(lines[0])["i"] == 0


def test_jsonl_overwrite_leaves_no_siblings(tmp_path: Path):
    target = tmp_path / "x.jsonl"
    atomic_write_jsonl(_rows(2), target)
    atomic_write_jsonl(_rows(5), target)
    assert len(target.read_text(encoding="utf-8").splitlines()) == 5
    leftovers = sorted(p.name for p in tmp_path.iterdir() if p.name != "x.jsonl")
    assert leftovers == [], f"unexpected temp/lock leftovers: {leftovers}"


def test_jsonl_peak_memory_sublinear(tmp_path: Path):
    """Guard against regression to full-document buffering.

    Rows are built BEFORE tracing so the measured peak reflects only what the
    write path allocates. O(N) buffering (the old StringIO.getvalue) peaks at
    ~doc size; streaming peaks at ~one row. Generous bound separates them.
    """
    n, payload = 4000, 500
    rows = _rows(n, payload)            # built before tracing
    doc_bytes = n * payload
    target = tmp_path / "big.jsonl"
    tracemalloc.start()
    atomic_write_jsonl(rows, target)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < doc_bytes, f"peak {peak} >= doc {doc_bytes}: looks like full-doc buffering"
    assert len(target.read_text(encoding="utf-8").splitlines()) == n


# --- atomic_write_stream primitive (now single-sources atomic_write machinery) ---

def test_atomic_write_still_works_via_wrapper(tmp_path: Path):
    target = tmp_path / "t.txt"
    atomic_write(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"
    assert (target.stat().st_mode & 0o777) == 0o600


def test_atomic_write_stream_writes_via_callback(tmp_path: Path):
    target = tmp_path / "cb.txt"
    atomic_write_stream(target, lambda f: f.write("a\nb\nc\n"))
    assert target.read_text(encoding="utf-8") == "a\nb\nc\n"


def test_atomic_write_stream_failure_preserves_target(tmp_path: Path):
    target = tmp_path / "keep.txt"
    atomic_write(target, "original")

    def boom(f):
        f.write("partial")
        raise RuntimeError("write failed mid-stream")

    with pytest.raises(RuntimeError, match="write failed"):
        atomic_write_stream(target, boom)
    assert target.read_text(encoding="utf-8") == "original"
    leftovers = sorted(p.name for p in tmp_path.iterdir() if p.name != "keep.txt")
    assert leftovers == [], f"unexpected temp/lock leftovers: {leftovers}"
