"""Regression: spray-backlinks --resume must fail cleanly on input/checkpoint mismatch.

Audit finding [30]: ``_setup_resume`` did ``seed_indices_to_process.remove(s["index"])``
for every completed checkpoint seed. When the resumed input has fewer rows than the
original run, a stored index >= len(rows) is absent from the list and list.remove()
raised a bare ``ValueError`` — not a ``PipelineError`` — so main() crashed with a raw
traceback instead of a clean UsageError envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backlink_publisher._util.errors import UsageError
from backlink_publisher.cli.spray_backlinks import _gates


def test_resume_with_fewer_rows_than_checkpoint_raises_usage_error(tmp_path: Path) -> None:
    run_id = "20260713T000000-deadbeef"
    ckpt = {
        "seeds": [
            {"index": 0, "status": "completed", "cross_seed_pairs": []},
            # index 3 was completed in the original 5-seed run…
            {"index": 3, "status": "completed", "cross_seed_pairs": []},
        ]
    }
    (tmp_path / f"{run_id}.json").write_text(json.dumps(ckpt), encoding="utf-8")

    args = SimpleNamespace(resume=run_id)
    # …but the resumed input now has only 3 rows (valid indices 0,1,2).
    rows = [{"seed": "a"}, {"seed": "b"}, {"seed": "c"}]

    with pytest.raises(UsageError) as excinfo:
        _gates._setup_resume(args, rows, cdir=tmp_path)

    msg = str(excinfo.value).lower()
    assert "3" in str(excinfo.value)  # the out-of-range checkpoint index
    assert "checkpoint" in msg or "does not match" in msg
