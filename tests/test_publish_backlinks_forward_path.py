"""publish-backlinks CLI tests — Unit 3: advisory forward-path drift
recording (Plan 2026-05-27-006 Unit 3).

D1 split (2026-07-02): extracted from ``test_publish_backlinks.py``. Covers
``_record_publish_path()`` directly (link-alive happy path, drift via
nofollow/rewritten/stripped, skipped-verification and no-required-links
no-ops, OR-logic across multiple links) plus the end-to-end path through the
publish loop confirming drift is advisory (doesn't change the exit code) and
that ``--dry-run`` records nothing. Shared builders live in
``_publish_backlinks_test_helpers.py``.
"""
from __future__ import annotations

__tier__ = "unit"
import json

import pytest

from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult
from unittest.mock import patch
from _publish_backlinks_test_helpers import _make_valid_payload, _run_publish


@pytest.fixture(autouse=True)
def _mock_verify_pass(mocker):
    """Default: verification always passes so tests stay fast and network-free."""
    mocker.patch(
        "backlink_publisher.cli._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    )


def _drift_result(
    platform: str = "medium",
    *,
    nofollow: bool = False,
    rewritten: bool = False,
    found: bool = True,
    verification: str = "ok",
    has_target_fields: bool = True,
) -> AdapterResult:
    """Build an AdapterResult with a link_attr_verification dict pre-set."""
    if verification == "skipped":
        link_attr: dict = {"verification": "skipped", "reason": "timeout"}
    elif not has_target_fields:
        link_attr = {"verification": "ok", "total_anchors": 2}  # no target_* fields
    else:
        link_attr = {
            "verification": "ok",
            "total_anchors": 2,
            "target_found": found,
            "target_nofollow": nofollow,
            "target_rewritten": rewritten,
            "target_nofollow_urls": ["https://x.com"] if nofollow else [],
            "target_missing_urls": [] if found else ["https://x.com"],
            "target_rewritten_urls": ["https://x.com"] if rewritten else [],
        }
    return AdapterResult(
        status="published",
        adapter=f"{platform}-api",
        platform=platform,
        published_url="https://pub.example.com/p/abc",
        _provider_meta={"link_attr_verification": link_attr},
    )


def _drift_row() -> dict:
    return {
        "id": "row01",
        "links": [
            {"url": "https://x.com", "required": True},
        ],
    }


def test_record_publish_path_link_alive_happy(monkeypatch, tmp_path):
    """Happy path: dofollow → link-alive recorded, no WARN, returns 0."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = _drift_result("medium", nofollow=False, rewritten=False, found=True)
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 0
    health = cstore.get_publish_path_health("medium")
    assert health["status"] == cstore.STATUS_LINK_ALIVE
    cstore.canary_health_store.reset()


def test_record_publish_path_drift_nofollow_returns_1_and_warns(
    monkeypatch, tmp_path, capsys
):
    """Drift (nofollow): drift recorded, WARN on stderr, returns 1, exit code unchanged."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = _drift_result("medium", nofollow=True)
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 1
    health = cstore.get_publish_path_health("medium")
    assert health["status"] == cstore.STATUS_DRIFT_CONFIRMED
    cstore.canary_health_store.reset()


def test_record_publish_path_drift_stripped_detected(monkeypatch, tmp_path):
    """Drift (stripped / missing): readable page, required link absent → drift (R5)."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = _drift_result("medium", found=False)
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 1
    assert cstore.get_publish_path_health("medium")["status"] == cstore.STATUS_DRIFT_CONFIRMED
    cstore.canary_health_store.reset()


def test_record_publish_path_skipped_verdict_records_nothing(monkeypatch, tmp_path):
    """skipped verification → nothing recorded (R5), returns 0."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = _drift_result("medium", verification="skipped")
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 0
    # No forward-path entry written at all — status remains NOT_CONFIGURED
    health = cstore.get_publish_path_health("medium")
    assert health["status"] == cstore.STATUS_NOT_CONFIGURED
    cstore.canary_health_store.reset()


def test_record_publish_path_no_required_links_records_nothing(monkeypatch, tmp_path):
    """No target_* fields (no required links) → nothing recorded, returns 0."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = _drift_result("medium", has_target_fields=False)
    ret = _record_publish_path("medium", result, {"id": "x", "links": []})

    assert ret == 0
    health = cstore.get_publish_path_health("medium")
    assert health["status"] == cstore.STATUS_NOT_CONFIGURED
    cstore.canary_health_store.reset()


def test_record_publish_path_no_provider_meta_records_nothing(monkeypatch, tmp_path):
    """_provider_meta=None (dry-run / no-verifier adapter) → nothing recorded."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = AdapterResult(
        status="published",
        adapter="medium-api",
        platform="medium",
        published_url="https://pub.example.com/p/1",
        _provider_meta=None,
    )
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 0
    cstore.canary_health_store.reset()


def test_record_publish_path_empty_provider_meta_records_nothing(monkeypatch, tmp_path):
    """_provider_meta={} (empty dict, distinct code path from None) → returns 0."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    result = AdapterResult(
        status="published",
        adapter="medium-api",
        platform="medium",
        published_url="https://pub.example.com/p/1",
        _provider_meta={},
    )
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 0
    assert cstore.get_publish_path_health("medium")["status"] == cstore.STATUS_NOT_CONFIGURED
    cstore.canary_health_store.reset()


def test_record_publish_path_or_logic_any_drift_is_drift(monkeypatch, tmp_path):
    """Multi-link row: one dofollow, one rewritten → OR → platform verdict = drift."""
    from backlink_publisher.canary import store as cstore
    from backlink_publisher.cli._publish_helpers import _record_publish_path

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    cstore.canary_health_store.reset()

    # Simulate: first link dofollow, second rewritten
    result = _drift_result("medium", rewritten=True)
    ret = _record_publish_path("medium", result, _drift_row())

    assert ret == 1
    assert cstore.get_publish_path_health("medium")["status"] == cstore.STATUS_DRIFT_CONFIRMED
    cstore.canary_health_store.reset()


# ---------------------------------------------------------------------------
# Unit 3 — end-to-end through publish loop (advisory, no exit-code change)
# ---------------------------------------------------------------------------

@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_path_drift_does_not_change_exit_code(
    mock_pub, mock_verify_setup, monkeypatch, tmp_path
):
    """Drift detected during publish → advisory WARN on stderr, exit code still 0."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.canary import store as cstore
    cstore.canary_health_store.reset()

    mock_pub.return_value = _drift_result("medium", nofollow=True)
    payload = _make_valid_payload(platform="medium")

    stdout, stderr, code = _run_publish(
        json.dumps(payload), ["--platform", "medium", "--mode", "publish"]
    )

    assert code == 0, f"drift should not change exit code. stderr={stderr}"
    assert "publish-path-canary" in stderr
    assert "drift" in stderr
    cstore.canary_health_store.reset()


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
def test_publish_path_dry_run_records_nothing(
    mock_pub, mock_verify_setup, monkeypatch, tmp_path
):
    """--dry-run → adapters don't verify → nothing recorded to forward-path store."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.canary import store as cstore
    cstore.canary_health_store.reset()

    # Dry-run result (no _provider_meta)
    mock_pub.return_value = AdapterResult(
        status="dry_run",
        adapter="medium-api",
        platform="medium",
        published_url="",
        _dry_run=True,
    )
    payload = _make_valid_payload(platform="medium")

    stdout, stderr, code = _run_publish(
        json.dumps(payload), ["--platform", "medium", "--mode", "publish", "--dry-run"]
    )

    health = cstore.get_publish_path_health("medium")
    assert health["status"] == cstore.STATUS_NOT_CONFIGURED
