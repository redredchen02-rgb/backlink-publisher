"""Unit 1 — spray-backlinks CLI scaffold (plan 2026-06-02-005).

Exercises the shell's argparse + JSONL I/O + exit-code discipline + seed
expansion. The autouse conftest fixtures sandbox the config dir and block
sockets, so no network is touched.
"""

from __future__ import annotations

import json

import pytest

import backlink_publisher.publishing.adapters  # noqa: F401  populate registry
from backlink_publisher.cli import spray_backlinks
from backlink_publisher.publishing.registry import registered_platforms


def _seed(platform: str) -> dict:
    return {
        "target_url": "https://example.com/post",
        "main_domain": "https://example.com",
        "language": "zh-CN",
        "platform": platform,
        "url_mode": "A",
        "publish_mode": "draft",
    }


def _write_seed(tmp_path, seed: dict):
    path = tmp_path / "seed.jsonl"
    path.write_text(json.dumps(seed) + "\n", encoding="utf-8")
    return str(path)


def _two_registered() -> list[str]:
    plats = registered_platforms()
    assert len(plats) >= 2, "need >=2 registered platforms for the fan-out test"
    return plats[:2]


def test_fans_one_seed_to_selected_platforms(tmp_path, capsys):
    p0, p1 = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))

    spray_backlinks.main(["--input", seed_path, "--platforms", f"{p0},{p1}"])

    rows = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(rows) == 2
    assert [r["platform"] for r in rows] == [p0, p1]
    # Seed is cloned per platform; non-platform fields are preserved.
    assert all(r["target_url"] == "https://example.com/post" for r in rows)


def test_unknown_platform_is_usage_error_exit_1(tmp_path):
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(["--input", seed_path, "--platforms", "not-a-real-platform"])
    assert exc.value.code == 1


def test_empty_platform_selection_is_usage_error_exit_1(tmp_path):
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(["--input", seed_path, "--platforms", ""])
    assert exc.value.code == 1


def test_duplicate_platforms_deduped(tmp_path, capsys):
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    spray_backlinks.main(["--input", seed_path, "--platforms", f"{p0},{p0}"])
    rows = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert len(rows) == 1


def test_multiple_seeds_rejected_single_seed_scope(tmp_path):
    p0, _ = _two_registered()
    path = tmp_path / "seeds.jsonl"
    path.write_text(json.dumps(_seed(p0)) + "\n" + json.dumps(_seed(p0)) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(["--input", str(path), "--platforms", p0])
    assert exc.value.code == 1


def test_invalid_seed_rejected_exit_2(tmp_path):
    p0, _ = _two_registered()
    bad = _seed(p0)
    del bad["target_url"]  # missing required field
    seed_path = _write_seed(tmp_path, bad)
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(["--input", seed_path, "--platforms", p0])
    assert exc.value.code == 2


def test_bad_dispatch_mode_is_usage_error_exit_1(tmp_path):
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(
            ["--input", seed_path, "--platforms", p0, "--dispatch", "nonsense"]
        )
    assert exc.value.code == 1
