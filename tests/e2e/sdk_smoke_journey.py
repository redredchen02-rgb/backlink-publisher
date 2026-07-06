"""U8a (plan 2026-06-24-001): in-process plan → validate → publish smoke journey.

Tests the full SDK pipeline in a single process, with adapter mocked. No sockets
needed. NOT collected by the default ``test_*.py`` glob; run explicitly::

    pytest tests/e2e/sdk_smoke_journey.py

Coverage:
  S1  plan(blogger seed) → validate → publish(mocked drafted) → success
  S2  publish with empty published_url + draft_url → _unverified suffix (B1 on
      SDK path: confirms _do_verify correctly marks empty-URL publishes as
      unverified through the in-process engine)
"""

from __future__ import annotations

__tier__ = "e2e"

import json
from unittest.mock import patch

import pytest

from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult
import backlink_publisher.sdk as sdk

# ── blogger seed (API-tier — no Chrome / subprocess needed) ──────────────────

def _blogger_seed() -> dict:
    return {
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "language": "en",
        "platform": "blogger",
        "url_mode": "A",
        "publish_mode": "draft",
        "topic": "Test Topic",
    }


def _blogger_draft_result(item_id: str = "r0") -> AdapterResult:
    return AdapterResult(
        status="drafted",
        adapter="blogger-api",
        platform="blogger",
        draft_url=f"https://blogger.example.com/p/{item_id}",
    )


# ── S1: happy-path smoke ─────────────────────────────────────────────────────

def test_sdk_plan_validate_publish_smoke():
    """S1: in-process plan → validate → publish(mocked adapter) journey succeeds."""
    seed = _blogger_seed()

    # Step 1: plan
    plan_result = sdk.plan(seed)
    assert plan_result.success, f"sdk.plan failed: {plan_result.error}"
    assert plan_result.rows, "plan produced no rows"

    # Step 2: validate
    validate_result = sdk.validate(plan_result.rows, no_check_urls=True)
    assert validate_result.success, f"sdk.validate failed: {validate_result.error}"
    assert validate_result.rows, "validate produced no rows"

    # Step 3: publish (mock adapter so nothing is posted)
    with patch(
        "backlink_publisher.cli.publish_backlinks.adapter_publish",
    ) as mock_pub, patch(
        "backlink_publisher.cli.publish_backlinks.verify_adapter_setup",
    ), patch(
        "backlink_publisher.cli.publish._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    ):
        row = validate_result.rows[0]
        row_id = row.get("id", "r0")
        mock_pub.return_value = _blogger_draft_result(row_id)

        pub_result = sdk.publish(validate_result.rows)

    assert pub_result.success, f"sdk.publish failed: {pub_result.error}"
    assert pub_result.rows, "publish produced no rows"
    out_row = pub_result.rows[0]
    assert out_row.get("status") not in (None, ""), (
        f"publish row has no status: {out_row}"
    )
    assert "_unverified" not in out_row.get("status", ""), (
        f"happy-path must not be _unverified, got: {out_row['status']!r}"
    )


# ── S2: empty-URL publish → _unverified (B1 coverage on SDK path) ─────────────

def test_sdk_publish_empty_url_is_unverified():
    """S2: SDK publish with empty published_url + draft_url → _unverified status.

    Covers the B1 fix (_do_verify returning False for empty URLs) on the
    in-process SDK code path. The SDK path uses the same _do_verify helper,
    so this confirms the fix holds end-to-end through the SDK.
    """
    seed = _blogger_seed()

    plan_result = sdk.plan(seed)
    assert plan_result.success, f"sdk.plan failed: {plan_result.error}"

    validate_result = sdk.validate(plan_result.rows, no_check_urls=True)
    assert validate_result.success, f"sdk.validate failed: {validate_result.error}"

    with patch(
        "backlink_publisher.cli.publish_backlinks.adapter_publish",
    ) as mock_pub, patch(
        "backlink_publisher.cli.publish_backlinks.verify_adapter_setup",
    ), patch(
        "backlink_publisher.cli.publish._publish_helpers.verify_published",
        return_value=VerificationResult(ok=True, reason=""),
    ):
        mock_pub.return_value = AdapterResult(
            status="published",
            adapter="blogger-api",
            platform="blogger",
            published_url="",
            draft_url="",
        )

        pub_result = sdk.publish(validate_result.rows)

    # publish with empty URL exits non-zero (unverified) but still returns rows
    assert not pub_result.success or "_unverified" in (pub_result.rows[0].get("status") or ""), (
        f"Empty-URL publish must produce _unverified status or failure.\n"
        f"success={pub_result.success}, rows={pub_result.rows}"
    )
    if pub_result.rows:
        status = pub_result.rows[0].get("status", "")
        assert "unverified" in status, (
            f"expected '_unverified' in status, got: {status!r}"
        )
