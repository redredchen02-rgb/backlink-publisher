"""Unit 4 — link/anchor diversity audit + body-similarity readout + dry-run.

Body-similarity (shingle Jaccard) is the gate; footprint link byte-signature is
informational only (degenerate for same-target fan-out). Dry-run emits a
per-shot preview + audit summary with zero side effects.
"""
from __future__ import annotations

__tier__ = "unit"
import json

import pytest

from backlink_publisher.cli import spray_backlinks
from backlink_publisher.cli.spray_backlinks import core as spray_core
from backlink_publisher.cli.spray_backlinks._audit import (
    audit_batch,
    max_pairwise_similarity,
)
from backlink_publisher.publishing.registry import registered_platforms


def _row(body: str, anchor: str = "Example") -> dict:
    return {
        "content_markdown": body,
        "title": "t",
        "links": [{"kind": "main_domain", "url": "https://example.com", "anchor": anchor}],
    }


def test_distinct_bodies_pass_audit():
    rows = [_row("alpha beta gamma delta epsilon zeta"), _row("one two three four five six")]
    report = audit_batch(rows)
    assert report.passed
    assert report.body_max_similarity < 0.9


def test_near_identical_bodies_fail_audit():
    body = "the quick brown fox jumps over the lazy dog repeatedly today"
    rows = [_row(body), _row(body)]
    report = audit_batch(rows)
    assert not report.passed
    assert "too similar" in report.fail_reason


def test_max_pairwise_similarity_zero_for_single_body():
    assert max_pairwise_similarity(["only one body here"]) == 0.0


def test_distinct_main_anchor_count():
    rows = [_row("aaa bbb ccc ddd", "AnchorOne"), _row("eee fff ggg hhh", "AnchorTwo")]
    report = audit_batch(rows)
    assert report.distinct_main_anchors == 2


# --- CLI dry-run integration ------------------------------------------------

def _seed(platform: str) -> dict:
    return {
        "target_url": "https://example.com/post",
        "main_domain": "https://example.com",
        "language": "zh-CN",
        "platform": platform,
        "url_mode": "A",
        "publish_mode": "draft",
    }


def _distinct_rewrite(platform, shot_idx, domain_label, main_domain, anchors, topic, language):
    # Deliberately distinct per platform so the audit passes.
    filler = " ".join(f"{platform}word{i}" for i in range(20))
    return f"# {platform} variant {shot_idx}\n\n{filler}"


def test_dry_run_emits_preview_and_summary_no_side_effects(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(spray_core, "_default_rewrite_fn", lambda cfg: _distinct_rewrite)
    plats = registered_platforms()[:2]
    seed_path = tmp_path / "s.jsonl"
    seed_path.write_text(json.dumps(_seed(plats[0])) + "\n", encoding="utf-8")

    # default --dispatch is dry-run
    spray_backlinks.main(
        ["--input", str(seed_path), "--platforms", ",".join(plats), "--no-fetch-verify"]
    )
    out = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip()]
    shots = [o for o in out if o.get("kind") == "shot"]
    summary = [o for o in out if o.get("kind") == "audit_summary"]
    assert len(shots) == 2
    assert all("body_excerpt" in s for s in shots)
    assert len(summary) == 1
    assert summary[0]["passed"] is True
    assert summary[0]["n"] == 2
