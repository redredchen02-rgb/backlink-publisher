"""U4-0 golden corpus (plan 2026-06-22-001): pins the CURRENT publish-backlinks
exit-code + stdout contract across the scenario matrix, canonicalized so it is
stable under publish's intentional nondeterminism (timestamps).

This is the "zero behavior change" net for the U4 in-process-engine refactor:
after publish_rows / PublishOutcome / the epilogue split land (U4-1..U4-5), these
assertions MUST still hold byte-identically (modulo the canonicalized fields).

KEY CHARACTERIZED FACT (drives the U4-2 design): DependencyError and
AuthExpiredError mid-loop ABORT the run immediately (exit 3, epilogue skipped, no
stdout) — UNLIKE ExternalService/Banner/ContentRejected which record a failure row
and continue (epilogue then exits 4). So U4-2 must make DependencyError mirror
AuthExpiredError (typed abort, exit 3), NOT ExternalServiceError (continue, exit 4),
or these goldens flag the CLI exit-code regression.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import (
    AuthExpiredError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.cli.publish_backlinks import main
from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path):
    fake_config_dir = tmp_path / "config"
    fake_config_dir.mkdir(parents=True, exist_ok=True)
    with patch(
        "backlink_publisher.config._config_dir", return_value=fake_config_dir,
    ), patch(
        "backlink_publisher.checkpoint._cache_dir", return_value=tmp_path / "cache",
    ):
        from webui_store.channel_status import channel_status_store as _store
        _store.path = fake_config_dir / "channel-status.json"
        yield fake_config_dir


@pytest.fixture(autouse=True)
def _mock_verify_pass():
    with patch(
        "backlink_publisher.cli._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    ):
        yield


def _payload(row_id="char-1", platform="blogger"):
    return {
        "id": row_id, "platform": platform, "language": "en", "publish_mode": "draft",
        "target_url": "https://example.com/article", "main_domain": "https://example.com",
        "url_mode": "A", "title": "Test Article", "slug": "test-article",
        "excerpt": "An excerpt.", "tags": ["tag1"],
        "content_markdown": "Content about https://example.com page.",
        "links": [
            {"url": "https://example.com", "anchor": "Example", "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article", "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki", "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN", "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO", "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GH", "kind": "supporting", "required": False},
        ],
        "seo": {"title": "T", "description": "D", "canonical_url": "https://example.com/article"},
    }


def _ok_result():
    return AdapterResult(
        status="drafted", adapter="blogger-api", platform="blogger",
        draft_url="https://blogger.example.com/p/1",
    )


# Fields redacted before comparison: publish injects timestamps (and run_id into
# checkpoint, not the row). Redaction keeps the golden stable; structural fields
# (id/platform/status/error) are the contract.
_VOLATILE = {"created_at", "run_id", "published_at_raw", "published_at_utc"}


def _canon(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.strip().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows.append({k: ("<redacted>" if k in _VOLATILE else v) for k, v in sorted(row.items())})
    return rows


def _run(side_effect, n_rows, argv):
    payloads = "\n".join(json.dumps(_payload(row_id=f"r{i}")) for i in range(n_rows))
    old = (sys.stdin, sys.stdout, sys.stderr)
    try:
        sys.stdin, sys.stdout, sys.stderr = StringIO(payloads), StringIO(), StringIO()
        with patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup"), \
             patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
            mock_pub.side_effect = side_effect
            try:
                main(argv)
                code = 0
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return _canon(sys.stdout.getvalue()), code
    finally:
        sys.stdin, sys.stdout, sys.stderr = old


_ARGV = ["--mode", "draft", "--skip-publish-time-check"]


def test_golden_single_success():
    rows, code = _run([_ok_result()], 1, _ARGV)
    assert code == 0
    assert len(rows) == 1 and rows[0]["status"] == "drafted" and rows[0]["error"] is None


def test_golden_two_successes():
    rows, code = _run([_ok_result(), _ok_result()], 2, _ARGV)
    assert code == 0
    assert len(rows) == 2 and all(r["status"] == "drafted" for r in rows)


def test_golden_partial_ok_then_external_error_exits_4_writes_only_success():
    rows, code = _run([_ok_result(), ExternalServiceError("svc down")], 2, _ARGV)
    assert code == 4, "any failed row -> epilogue exits 4"
    assert len(rows) == 1 and rows[0]["error"] is None, "only the successful row is written to stdout"


def test_golden_single_external_error_exits_4_empty_stdout():
    rows, code = _run([ExternalServiceError("svc down")], 1, _ARGV)
    assert code == 4
    assert rows == [], "no successful rows -> nothing written, but exit is 4 (failed present)"


def test_golden_single_dependency_error_aborts_exit_3_no_stdout():
    """DependencyError mid-loop ABORTS immediately (emit_error exit 3), epilogue
    never runs -> exit 3, empty stdout. U4-2 must preserve this (mirror auth, not external)."""
    rows, code = _run([DependencyError("missing config")], 1, _ARGV)
    assert code == 3
    assert rows == []


def test_golden_ok_then_dependency_error_aborts_before_writing_success():
    """row1 succeeds (in state) then row2 DependencyError aborts the WHOLE run before
    the epilogue writes -> exit 3, empty stdout (row1's success is NOT emitted).
    This is the immediate-abort semantics U4-2 must keep."""
    rows, code = _run([_ok_result(), DependencyError("missing config")], 2, _ARGV)
    assert code == 3
    assert rows == [], "epilogue skipped on dependency-abort -> row1 success not written"


def test_golden_auth_expired_aborts_exit_3_no_stdout():
    rows, code = _run(
        [AuthExpiredError(channel="medium", reason="HTTP 401")], 1,
        ["--platform", "medium", "--mode", "draft", "--skip-publish-time-check"],
    )
    assert code == 3
    assert rows == []
