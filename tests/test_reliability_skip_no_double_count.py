"""Enforce skips must not double-count as publish.failed (Plan 2026-06-15-006, Unit 3).

An enforce skip is recorded as a reliability.decision at the dispatch seam (U2).
The checkpoint also marks the item failed with error_class=policy_skip; the
projector must SUPPRESS the publish.failed projection for that error_class so the
skip is not also counted as a failure in success_rate's denominator.
"""
from __future__ import annotations

__tier__ = "integration"

import sqlite3

import pytest

from backlink_publisher import checkpoint
from backlink_publisher.checkpoint import create_checkpoint, update_item
from backlink_publisher.events import EventStore, project_run_safe


@pytest.fixture(autouse=True)
def _isolate_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    yield


def _kinds() -> list[str]:
    with EventStore().connect() as conn:
        conn.row_factory = sqlite3.Row
        return [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY id")]


def _seed_failed_run(*, error_class: str, platform: str = "blogger") -> str:
    rows = [{
        "id": "r0", "platform": platform, "language": "en",
        "publish_mode": "draft", "target_url": "https://example.com/a",
        "main_domain": "https://example.com", "title": "T", "slug": "t",
        "content_markdown": "x", "links": [],
    }]
    run_id, _ = create_checkpoint(rows, platform=platform, mode="publish")
    update_item(
        run_id, "r0", "failed",
        error="circuit open for blogger",
        error_class=error_class,
        adapter=platform,
    )
    return run_id


def test_policy_skip_is_not_projected_as_publish_failed():
    """An enforce skip (error_class=policy_skip) must NOT become a publish.failed."""
    run_id = _seed_failed_run(error_class=checkpoint.POLICY_SKIP)

    project_run_safe(run_id)

    assert "publish.failed" not in _kinds()


def test_genuine_failure_is_still_projected():
    """Regression: a non-skip failure still projects publish.failed (no over-suppression)."""
    run_id = _seed_failed_run(error_class="unexpected")

    project_run_safe(run_id)

    assert "publish.failed" in _kinds()
