"""publish-backlinks CLI tests — Unit 2: checkpoint integration.

D1 split (2026-07-02): extracted from ``test_publish_backlinks.py``. Covers
checkpoint creation on success/failure/partial-batch, preflight/verify
failures skipping checkpoint creation, dry-run not creating a checkpoint,
graceful degradation when checkpoint creation itself raises, and the
quarantined-platform hard-skip path (which is not counted as a publish
failure). Shared builders live in ``_publish_backlinks_test_helpers.py``.
"""
from __future__ import annotations

__tier__ = "unit"
import json
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult
from _publish_backlinks_test_helpers import _make_valid_payload, _run_publish


@pytest.fixture(autouse=True)
def _mock_verify_pass(mocker):
    """Default: verification always passes so tests stay fast and network-free."""
    mocker.patch(
        "backlink_publisher.cli._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    )


@patch("backlink_publisher.checkpoint._cache_dir")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_checkpoint_created_on_success(mock_pub, mock_verify, mock_cache, tmp_path):
    """2-row batch both succeed → checkpoint has both items done, run_id in stderr."""
    mock_cache.return_value = tmp_path / "cache"
    payloads = [_make_valid_payload(platform="blogger") for _ in range(2)]
    for i, p in enumerate(payloads):
        p["id"] = f"r{i}"
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="blogger-api", platform="blogger",
        draft_url="https://blogger.example.com/p/1",
    )

    stdout, stderr, code = _run_publish(
        "\n".join(json.dumps(p) for p in payloads),
        ["--mode", "draft", "--log-level", "INFO"],
    )

    assert code == 0
    assert "run_id=" in stderr

    ckpt_dir = tmp_path / "cache" / "checkpoints"
    files = list(ckpt_dir.glob("*.json"))
    assert len(files) == 1
    import json as _json
    data = _json.loads(files[0].read_text())
    assert all(item["status"] == "done" for item in data["items"])
    assert len(data["items"]) == 2


@patch("backlink_publisher.checkpoint._cache_dir")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
def test_checkpoint_not_created_on_preflight_failure(mock_verify, mock_cache, tmp_path):
    """validate_publish_payload failure → no checkpoint created."""
    mock_cache.return_value = tmp_path / "cache"
    bad_row = {"id": "x", "platform": "blogger"}  # missing required fields

    stdout, stderr, code = _run_publish(json.dumps(bad_row), ["--mode", "draft"])

    assert code == 2
    ckpt_dir = tmp_path / "cache" / "checkpoints"
    assert not ckpt_dir.exists() or not list(ckpt_dir.glob("*.json"))


@patch("backlink_publisher.checkpoint._cache_dir")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_checkpoint_first_fails_second_succeeds(mock_pub, mock_verify, mock_cache, tmp_path):
    """First row ExternalServiceError → failed in checkpoint, second done.

    Note: each row MUST have a distinct target_url so the reconciler
    (which cross-references checkpoints against the dedup store)
    does not auto-fix r0's "failed" checkpoint to "done" when r1's
    same-URL dedup record is in ``done`` state (Plan 2026-05-28-004).
    """
    mock_cache.return_value = tmp_path / "cache"
    r0 = _make_valid_payload(platform="blogger")
    r0["id"] = "r0"
    r0["target_url"] = "https://example.com/r0"
    # Update links to reference r0's distinct target_url.
    for link in r0.get("links", []):
        if link["url"] == "https://example.com/article":
            link["url"] = r0["target_url"]
    r1 = _make_valid_payload(platform="blogger")
    r1["id"] = "r1"
    r1["target_url"] = "https://example.com/r1"
    for link in r1.get("links", []):
        if link["url"] == "https://example.com/article":
            link["url"] = r1["target_url"]
    mock_pub.side_effect = [
        ExternalServiceError("upstream down"),
        AdapterResult(status="drafted", adapter="blogger-api", platform="blogger",
                      draft_url="https://blogger.example.com/p/2"),
    ]

    stdout, stderr, code = _run_publish(
        "\n".join(json.dumps(p) for p in [r0, r1]), ["--mode", "draft"]
    )

    assert code == 4
    ckpt_dir = tmp_path / "cache" / "checkpoints"
    import json as _json
    data = _json.loads(list(ckpt_dir.glob("*.json"))[0].read_text())
    by_id = {item["id"]: item for item in data["items"]}
    assert by_id["r0"]["status"] == "failed"
    assert by_id["r0"]["error_class"] == "transient"
    assert by_id["r1"]["status"] == "done"


@patch("backlink_publisher.checkpoint._cache_dir")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
def test_checkpoint_not_created_on_verify_failure(mock_verify, mock_cache, tmp_path):
    """verify_adapter_setup failure → exit 3, no checkpoint created."""
    mock_cache.return_value = tmp_path / "cache"
    mock_verify.side_effect = DependencyError("oauth not configured")

    payload = _make_valid_payload(platform="blogger")
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--mode", "draft"])

    assert code == 3
    ckpt_dir = tmp_path / "cache" / "checkpoints"
    assert not ckpt_dir.exists() or not list(ckpt_dir.glob("*.json"))


@patch("backlink_publisher.checkpoint._cache_dir")
def test_checkpoint_not_created_on_dry_run(mock_cache, tmp_path):
    """--dry-run → no checkpoint file created."""
    mock_cache.return_value = tmp_path / "cache"
    payload = _make_valid_payload(platform="medium")
    with patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.return_value = AdapterResult(
            status="draft", adapter="medium-api", platform="medium",
            _dry_run=True, _command="dry-run plan",
        )
        stdout, stderr, code = _run_publish(json.dumps(payload), ["--dry-run"])

    assert code == 0
    ckpt_dir = tmp_path / "cache" / "checkpoints"
    assert not ckpt_dir.exists() or not list(ckpt_dir.glob("*.json"))


@patch("backlink_publisher.checkpoint._cache_dir")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_checkpoint_create_failure_degrades_gracefully(mock_pub, mock_verify, mock_cache, tmp_path):
    """create_checkpoint raising OSError → publish run still completes, no crash."""
    mock_cache.return_value = tmp_path / "cache"
    mock_pub.return_value = AdapterResult(
        status="drafted", adapter="blogger-api", platform="blogger",
        draft_url="https://blogger.example.com/p/1",
    )
    with patch("backlink_publisher.cli.publish_backlinks.checkpoint.create_checkpoint",
               side_effect=OSError("disk full")):
        payload = _make_valid_payload(platform="blogger")
        stdout, stderr, code = _run_publish(json.dumps(payload), ["--mode", "draft"])

    assert code == 0
    assert "checkpoint not created" in stderr
    assert stdout.strip() != ""


@patch("backlink_publisher.checkpoint._cache_dir")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_checkpoint_3_rows_2_done_1_failed(mock_pub, mock_verify, mock_cache, tmp_path):
    """3-row batch: first two succeed, third raises → checkpoint has 2 done, 1 failed."""
    mock_cache.return_value = tmp_path / "cache"
    payloads = [_make_valid_payload(platform="blogger") for _ in range(3)]
    for i, p in enumerate(payloads):
        p["id"] = f"r{i}"
        p["target_url"] = f"https://example.com/r{i}"
        for link in p.get("links", []):
            if link["url"] == "https://example.com/article":
                link["url"] = p["target_url"]
    mock_pub.side_effect = [
        AdapterResult(status="drafted", adapter="blogger-api", platform="blogger",
                      draft_url="https://blogger.example.com/p/1"),
        AdapterResult(status="drafted", adapter="blogger-api", platform="blogger",
                      draft_url="https://blogger.example.com/p/2"),
        ExternalServiceError("timeout"),
    ]

    stdout, stderr, code = _run_publish(
        "\n".join(json.dumps(p) for p in payloads), ["--mode", "draft"]
    )

    assert code == 4
    import json as _json
    ckpt_dir = tmp_path / "cache" / "checkpoints"
    data = _json.loads(list(ckpt_dir.glob("*.json"))[0].read_text())
    by_id = {item["id"]: item for item in data["items"]}
    assert by_id["r0"]["status"] == "done"
    assert by_id["r1"]["status"] == "done"
    assert by_id["r2"]["status"] == "failed"


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_quarantined_hard_skip_is_skipped_not_failed(
    mock_pub, mock_verify, tmp_path, monkeypatch
):
    """A quarantined platform opted into hard_skip is filtered from the payload
    WITHOUT being counted as a publish failure: the run still exits 0 (a
    deliberate advisory skip is not exit-4). Regression for the ce:review
    finding that skipped_quarantined rows were appended as failure rows."""
    from backlink_publisher.canary import store as canary_store

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        "\n".join(
            [
                "[canary.blogger]",
                'post_url = "https://canary.example.com/p.html"',
                'expected_target = "https://example.com/"',
                'marker = "cnry-zzz"',
                "hard_skip = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    canary_store.canary_health_store.reset()
    # Quarantine blogger (two consecutive drifts crosses QUARANTINE_AFTER_N).
    canary_store.record_verdict("blogger", canary_store.STATUS_DRIFT_CONFIRMED)
    canary_store.record_verdict("blogger", canary_store.STATUS_DRIFT_CONFIRMED)
    assert canary_store.is_quarantined("blogger") is True

    payload = _make_valid_payload(platform="blogger")
    stdout, stderr, code = _run_publish(
        json.dumps(payload), ["--platform", "blogger", "--mode", "draft"]
    )

    # The deliberate skip must NOT be a publish failure.
    assert code != 4, f"quarantine skip wrongly treated as failure. stderr: {stderr}"
    assert code in (0, 5)  # 0 = clean; 5 = "no payloads published" (all skipped)
    # The adapter was never invoked for the skipped row.
    assert mock_pub.call_count == 0
    # Operator gets a clear advisory on stderr; nothing published to stdout.
    assert "skipped_quarantined" in stderr
    assert stdout.strip() == ""
    canary_store.canary_health_store.reset()
