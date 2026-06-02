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
from backlink_publisher.cli.spray_backlinks import core as spray_core
from backlink_publisher.publishing.registry import registered_platforms


def _fake_rewrite(platform, shot_idx, domain_label, main_domain, anchors, topic, language):
    return f"# {platform} variant {shot_idx}\n\nDistinct prose for {platform}."


def _mock_llm(monkeypatch):
    """Patch the CLI's rewrite-fn factory so no network/LLM is needed."""
    monkeypatch.setattr(spray_core, "_default_rewrite_fn", lambda cfg: _fake_rewrite)


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


def test_fans_one_seed_to_selected_platforms(tmp_path, capsys, monkeypatch):
    _mock_llm(monkeypatch)
    p0, p1 = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))

    spray_backlinks.main(
        ["--input", seed_path, "--platforms", f"{p0},{p1}", "--no-fetch-verify"]
    )

    out = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    shots = [o for o in out if o.get("kind") == "shot"]
    assert len(shots) == 2
    assert [s["platform"] for s in shots] == [p0, p1]
    # Distinct LLM bodies per shot (the stealth mechanism).
    assert shots[0]["body_excerpt"] != shots[1]["body_excerpt"]


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


def test_duplicate_platforms_deduped(tmp_path, capsys, monkeypatch):
    _mock_llm(monkeypatch)
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    spray_backlinks.main(
        ["--input", seed_path, "--platforms", f"{p0},{p0}", "--no-fetch-verify"]
    )
    out = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    shots = [o for o in out if o.get("kind") == "shot"]
    assert len(shots) == 1


def test_no_llm_configured_cli_aborts_exit_3(tmp_path):
    # No LLM in the sandbox → R4a hard abort at the draft step (exit 3).
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(
            ["--input", seed_path, "--platforms", p0, "--no-fetch-verify"]
        )
    assert exc.value.code == 3


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


def test_burst_aborts_when_audit_fails(tmp_path, monkeypatch):
    # Identical bodies → body-similarity audit fails → burst aborts (exit 2)
    # before any dispatch (no network).
    identical = lambda *a, **k: "the same body text repeated across every shot here"
    monkeypatch.setattr(spray_core, "_default_rewrite_fn", lambda cfg: identical)
    p0, p1 = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main([
            "--input", seed_path, "--platforms", f"{p0},{p1}",
            "--no-fetch-verify", "--dispatch", "burst",
        ])
    assert exc.value.code == 2


def test_all_platforms_gated_out_exits_2(tmp_path, monkeypatch):
    # Every platform canary-degraded + no --force → all soft-dropped → exit 2.
    import backlink_publisher.canary.store as canary_store
    monkeypatch.setattr(canary_store, "is_degraded", lambda p: True)
    p0, p1 = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(
            ["--input", seed_path, "--platforms", f"{p0},{p1}", "--no-fetch-verify"]
        )
    assert exc.value.code == 2


def test_bad_dispatch_mode_is_usage_error_exit_1(tmp_path):
    p0, _ = _two_registered()
    seed_path = _write_seed(tmp_path, _seed(p0))
    with pytest.raises(SystemExit) as exc:
        spray_backlinks.main(
            ["--input", seed_path, "--platforms", p0, "--dispatch", "nonsense"]
        )
    assert exc.value.code == 1
