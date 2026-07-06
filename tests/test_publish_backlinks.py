"""Tests for publish-backlinks CLI — Unit 1 (adapter dispatch, exit codes).

D1 split (2026-07-02): checkpoint-integration tests (Unit 2) moved to
``test_publish_backlinks_checkpoint.py``; the ``_record_publish_path()``
forward-path drift tests (Unit 3) moved to
``test_publish_backlinks_forward_path.py``. Shared builders (``_run_publish``,
``_make_valid_payload``) live in ``_publish_backlinks_test_helpers.py``
(used by all three files); ``_make_result`` stays local here since only
this file's tests use it.
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
        "backlink_publisher.cli.publish._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    )


def _make_result(platform="medium", adapter="medium-api", mode="draft") -> AdapterResult:
    status = "published" if mode == "publish" else "drafted"
    return AdapterResult(
        status=status,
        adapter=adapter,
        platform=platform,
        draft_url="" if mode == "publish" else "https://medium.com/p/abc123",
        published_url="https://medium.com/p/abc123" if mode == "publish" else "",
    )


@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_dry_run(mock_pub):
    """--dry-run calls adapter with dry_run=True and outputs plan without publishing."""
    mock_pub.return_value = AdapterResult(
        status="draft",
        adapter="medium-api",
        platform="medium",
        _dry_run=True,
        _command="publish to medium --mode draft (dry-run)",
    )
    payload = _make_valid_payload(platform="medium")
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--dry-run"])

    assert code == 0, f"Expected 0, got {code}. stderr: {stderr}"
    # adapter was called with dry_run=True (not a real publish)
    call_kwargs = mock_pub.call_args[1]
    assert call_kwargs.get("dry_run") is True
    output = json.loads(stdout.strip())
    assert output["_dry_run"] is True
    assert output["platform"] == "medium"
    assert "_command" in output


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_draft_mode(mock_pub, mock_verify):
    mock_pub.return_value = _make_result(platform="medium", mode="draft")

    payload = _make_valid_payload(platform="medium")
    stdout, stderr, code = _run_publish(
        json.dumps(payload), ["--platform", "medium", "--mode", "draft"]
    )

    assert code == 0, f"Expected 0. stderr: {stderr}"
    output = json.loads(stdout.strip())
    assert output["status"] == "drafted"
    assert output["draft_url"] == "https://medium.com/p/abc123"
    assert output["error"] is None
    mock_verify.assert_called_once()


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_blogger(mock_pub, mock_verify):
    mock_pub.return_value = AdapterResult(
        status="drafted",
        adapter="blogger-api",
        platform="blogger",
        draft_url="https://myblog.blogspot.com/2026/05/post.html",
    )

    payload = _make_valid_payload(platform="blogger")
    stdout, stderr, code = _run_publish(
        json.dumps(payload), ["--platform", "blogger", "--mode", "draft"]
    )

    assert code == 0, f"Expected 0. stderr: {stderr}"
    output = json.loads(stdout.strip())
    assert output["platform"] == "blogger"
    assert output["status"] == "drafted"


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_with_row_platform(mock_pub, mock_verify):
    """Per-row platform used when --platform is not specified."""
    mock_pub.return_value = _make_result(platform="medium")

    payload = _make_valid_payload(platform="medium")
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--mode", "draft"])

    assert code == 0
    mock_verify.assert_called_once()


@patch(
    "backlink_publisher.cli.publish_backlinks.verify_adapter_setup",
    side_effect=DependencyError("Blogger OAuth not configured"),
)
def test_publish_missing_adapter_config(mock_verify):
    """Exit code 3 when adapter config is missing."""
    payload = _make_valid_payload(platform="blogger")
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--platform", "blogger"])

    assert code == 3
    assert "OAuth" in stderr


def test_publish_unknown_platform_rejected():
    """platform=xyznonexistent rejected with exit code 2."""
    payload = _make_valid_payload(platform="xyznonexistent")
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--mode", "draft"])

    assert code == 2
    assert "xyznonexistent" in stderr.lower()
    assert stdout == ""


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish",
       side_effect=ExternalServiceError("editor not found"))
def test_publish_external_service_error(mock_pub, mock_verify):
    """ExternalServiceError from adapter records failure and exits 4 (not abort mid-batch)."""
    payload = _make_valid_payload(platform="medium")
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--mode", "draft"])

    assert code == 4
    assert "editor not found" in stderr


@patch("backlink_publisher.cli.publish._publish_helpers.time.sleep")
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_external_service_error_mid_batch_continues(mock_pub, mock_verify, mock_sleep):
    """ExternalServiceError on row 2 of 3 does not abort rows 1 and 3."""
    results = [
        _make_result(platform="medium"),
        ExternalServiceError("rate-limited"),
        _make_result(platform="medium"),
    ]
    mock_pub.side_effect = results

    payloads = [_make_valid_payload(platform="medium") for _ in range(3)]
    for i, p in enumerate(payloads):
        p["id"] = f"row-{i}"
    stdout, stderr, code = _run_publish(
        "\n".join(json.dumps(p) for p in payloads), ["--mode", "draft"]
    )

    assert code == 4  # failure recorded
    assert "rate-limited" in stderr

    # Rows 1 and 3 succeeded — written to stdout
    out_lines = [l for l in stdout.strip().split("\n") if l]
    assert len(out_lines) == 2
    out_ids = {json.loads(l)["id"] for l in out_lines}
    assert "row-0" in out_ids
    assert "row-2" in out_ids

    # All 3 adapter calls were made
    assert mock_pub.call_count == 3


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_external_service_error_all_rows_fail(mock_pub, mock_verify):
    """All rows ExternalServiceError → exit 4, nothing on stdout."""
    mock_pub.side_effect = ExternalServiceError("service down")

    rows = [_make_valid_payload(platform="medium") for _ in range(2)]
    stdout, stderr, code = _run_publish(
        "\n".join(json.dumps(r) for r in rows), ["--mode", "draft"]
    )

    assert code == 4
    assert stdout.strip() == ""  # no successful rows
    assert "service down" in stderr


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_dependency_error_still_aborts(mock_pub, mock_verify):
    """DependencyError still aborts immediately (exit 3, not log-and-continue)."""
    mock_pub.side_effect = DependencyError("oauth not configured")

    payloads = [_make_valid_payload(platform="blogger") for _ in range(2)]
    stdout, stderr, code = _run_publish(
        "\n".join(json.dumps(p) for p in payloads), ["--mode", "draft"]
    )

    assert code == 3
    assert "oauth not configured" in stderr
    # Only first adapter call was made — abort on first DependencyError
    assert mock_pub.call_count == 1


def test_publish_empty_input():
    """Empty input must produce error."""
    stdout, stderr, code = _run_publish("")
    assert code == 2
    assert stdout == ""


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_output_schema(mock_pub, mock_verify):
    """Publish output matches the expected JSONL schema."""
    mock_pub.return_value = _make_result(platform="medium")

    payload = _make_valid_payload(platform="medium")
    stdout, stderr, code = _run_publish(
        json.dumps(payload), ["--platform", "medium", "--mode", "draft"]
    )

    assert code == 0
    output = json.loads(stdout.strip())

    for field in ["id", "platform", "status", "title", "target_url", "article_urls",
                  "draft_url", "published_url", "created_at", "adapter", "error"]:
        assert field in output, f"Missing field: {field}"
    assert output["article_urls"] == ["https://medium.com/p/abc123"]


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_default_is_draft(mock_pub, mock_verify):
    """Default mode must be draft."""
    mock_pub.return_value = _make_result(platform="medium", mode="draft")

    payload = _make_valid_payload()
    stdout, stderr, code = _run_publish(json.dumps(payload), ["--platform", "medium"])

    assert code == 0
    call_kwargs = mock_pub.call_args[1]
    assert call_kwargs.get("mode") == "draft"


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_blogger_and_medium_rows(mock_pub, mock_verify):
    """Full integration: one blogger + one medium row, both mocked, exit 0."""
    def side_effect(payload, mode, config, dry_run=False, **_kwargs):
        # **_kwargs accepts ``banner_emit`` (Plan 2026-05-20-004 Unit 1).
        platform = payload.get("platform", "")
        return AdapterResult(
            status="drafted",
            adapter=f"{platform}-api",
            platform=platform,
            draft_url=f"https://{platform}.example.com/p/123",
        )

    mock_pub.side_effect = side_effect

    rows = [
        json.dumps(_make_valid_payload(platform="blogger")),
        json.dumps(_make_valid_payload(platform="medium")),
    ]
    stdout, stderr, code = _run_publish("\n".join(rows), ["--mode", "draft"])

    assert code == 0, f"Expected 0. stderr: {stderr}"
    lines = [l for l in stdout.strip().split("\n") if l]
    assert len(lines) == 2
