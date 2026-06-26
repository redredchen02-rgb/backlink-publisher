"""R7/R8: scrubbed-replay e2e of the real-credential publish path (CI half).

This module is the **scrubbed-replay** half — it carries ``__tier__ = 'e2e'`` and
runs in CI with zero secrets, replaying recorded Medium/Blogger results + live
page HTML through the publish-verify seams. The **live** half (real throwaway
credentials, draft mode) lives in ``test_live_publish_real.py`` and is NEVER
e2e-tiered (CI injects no secrets).

It asserts the two independent verification layers SEPARATELY:
  * ``verify_published`` — the link **exists** gate (drives ``*_unverified``);
  * ``link_attr_verification`` — the **dofollow truth** (advisory), surfaced in
    the publish output so a publish-ok-but-nofollow link records the nofollow
    truth instead of a false dofollow positive.

Auth-expired exit semantics (exit 3 + channel flip + checkpoint) are locked by
``test_publish_backlinks_auth_expired_flip.py``; here we only assert the
publish path aborts cleanly with no ``*_unverified`` rows.
"""

from __future__ import annotations

__tier__ = "e2e"

from io import StringIO
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import AuthExpiredError, ExternalServiceError
from backlink_publisher.cli.publish_backlinks import main
from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live_publish"
_TARGET = "https://my.site/article"


# ── harness ────────────────────────────────────────────────────────────────
def _run_publish(input_data: str, argv: list[str] | None = None) -> tuple[str, str, int]:
    old = (sys.stdin, sys.stdout, sys.stderr)
    try:
        sys.stdin = StringIO(input_data)
        sys.stdout, sys.stderr = StringIO(), StringIO()
        try:
            main(argv or [])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return sys.stdout.getvalue(), sys.stderr.getvalue(), code
    finally:
        sys.stdin, sys.stdout, sys.stderr = old


def _payload(platform: str, row_id: str = "e2e-1") -> dict:
    return {
        "id": row_id, "platform": platform, "language": "en", "publish_mode": "publish",
        "target_url": _TARGET, "main_domain": "https://my.site", "url_mode": "A",
        "title": "Recorded Post", "slug": "recorded-post", "excerpt": "An excerpt.",
        "tags": ["tag1"], "content_markdown": "Content linking https://my.site page.",
        "links": [
            {"url": "https://my.site", "anchor": "Site", "kind": "main_domain", "required": True},
            {"url": _TARGET, "anchor": "Article", "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki", "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN", "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO", "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GH", "kind": "supporting", "required": False},
        ],
        "seo": {"title": "Recorded | SEO", "description": "d", "canonical_url": _TARGET},
    }


def _link_attr_from_fixture(html_name: str, target: str = _TARGET) -> dict:
    """Run the REAL dofollow-truth layer against a recorded live page (offline:
    patch the verifier's HTTP seam to serve the fixture HTML)."""
    from backlink_publisher.publishing.adapters import link_attr_verifier as lav

    html = (_FIXTURES / html_name).read_text(encoding="utf-8")
    with patch(
        "backlink_publisher.publishing.adapters.link_attr_verifier._fetch_body_via_preflight",
        return_value=(html.encode(), None),
    ):
        return lav.verify_link_attributes(
            "https://recorded.example/post", target_urls=[target]
        )


def _recorded(name: str) -> dict:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _adapter_result(recorded: dict, verdict: dict) -> AdapterResult:
    return AdapterResult(
        status=recorded["status"], adapter=recorded["adapter"],
        platform=recorded["platform"], published_url=recorded.get("published_url", ""),
        draft_url=recorded.get("draft_url", ""),
        _provider_meta={"link_attr_verification": verdict},
    )


# ── scrubbed-replay scenarios ────────────────────────────────────────────────
@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_dofollow_replay_both_layers(mock_vp, mock_pub, mock_setup):
    """Happy: link exists (verify_published ok) AND dofollow truth confirmed."""
    verdict = _link_attr_from_fixture("medium_dofollow.html")
    # Layer 2 sanity: the real parser saw a present, dofollow operator link.
    assert verdict["target_found"] is True
    assert verdict["target_nofollow"] is False

    mock_pub.return_value = _adapter_result(_recorded("medium_recorded"), verdict)
    mock_vp.return_value = VerificationResult(ok=True, reason="")

    stdout, stderr, code = _run_publish(json.dumps(_payload("medium")), ["--mode", "publish"])
    assert code == 0
    out = json.loads(stdout.strip())
    assert "unverified" not in out["status"]                    # layer 1: link exists
    assert out["link_attr_verification"]["target_nofollow"] is False  # layer 2: dofollow


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_ratio_two_platforms_dofollow(mock_vp, mock_pub, mock_setup):
    """≥2-platform dofollow ratio: medium + blogger both verified dofollow."""
    mock_vp.return_value = VerificationResult(ok=True, reason="")
    adapters_seen = []

    def _publish_side(*a, **k):
        payload = k.get("payload") or (a[0] if a else {})
        platform = payload.get("platform")
        rec = _recorded(f"{platform}_recorded")
        verdict = _link_attr_from_fixture(rec["live_html_fixture"])
        adapters_seen.append(rec["adapter"])
        return _adapter_result(rec, verdict)

    mock_pub.side_effect = _publish_side
    rows = "\n".join(json.dumps(_payload(p, row_id=f"e2e-{p}")) for p in ("medium", "blogger"))
    stdout, stderr, code = _run_publish(rows, ["--mode", "publish"])

    assert code == 0
    outs = [json.loads(l) for l in stdout.strip().splitlines() if l.strip()]
    verified = [o for o in outs if "unverified" not in o["status"]
                and not o["link_attr_verification"]["target_nofollow"]]
    assert len(verified) >= 2                                   # the ratio lock
    assert len({o["adapter"] for o in verified}) >= 2           # two distinct platforms


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_publish_ok_but_stripped_records_nofollow_truth(mock_vp, mock_pub, mock_setup):
    """Anti-false-positive: the link EXISTS (verify_published ok=True) but its
    rel is nofollow — the system must record the nofollow truth and NOT report
    dofollow, independent of the link-exists gate."""
    verdict = _link_attr_from_fixture("medium_nofollow.html")
    assert verdict["target_found"] is True
    assert verdict["target_nofollow"] is True                   # layer 2 caught it

    mock_pub.return_value = _adapter_result(_recorded("medium_recorded"), verdict)
    mock_vp.return_value = VerificationResult(ok=True, reason="")  # link present → ok

    stdout, stderr, code = _run_publish(json.dumps(_payload("medium")), ["--mode", "publish"])
    out = json.loads(stdout.strip())
    assert "unverified" not in out["status"]                    # layer 1 still passes
    assert out["link_attr_verification"]["target_nofollow"] is True  # but no false dofollow


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_rewritten_interstitial_recorded(mock_vp, mock_pub, mock_setup):
    """A target reachable only via a redirect interstitial → target_rewritten."""
    verdict = _link_attr_from_fixture("medium_rewritten.html")
    assert verdict["target_found"] is True
    assert verdict["target_rewritten"] is True

    mock_pub.return_value = _adapter_result(_recorded("medium_recorded"), verdict)
    mock_vp.return_value = VerificationResult(ok=True, reason="")
    stdout, _, code = _run_publish(json.dumps(_payload("medium")), ["--mode", "publish"])
    out = json.loads(stdout.strip())
    assert out["link_attr_verification"]["target_rewritten"] is True


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_exit_code_precedence_publish_fail_over_unverified(mock_vp, mock_pub, mock_setup):
    """One ExternalServiceError row + one unverified row → exit 4 (publish-fail
    dominates the unverified exit 5)."""
    verdict = _link_attr_from_fixture("medium_dofollow.html")
    mock_pub.side_effect = [
        ExternalServiceError("service down"),
        _adapter_result(_recorded("blogger_recorded"), verdict),
    ]
    mock_vp.return_value = VerificationResult(ok=False, reason="title missing")
    rows = "\n".join(json.dumps(_payload(p, row_id=f"e2e-{p}")) for p in ("medium", "blogger"))
    _, _, code = _run_publish(rows, ["--mode", "publish"])
    assert code == 4


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_auth_expired_aborts_without_unverified_rows(mock_vp, mock_pub, mock_setup):
    """AuthExpiredError mid-flow → exit 3, epilogue skipped, no *_unverified rows.
    (Channel flip + checkpoint locked by test_publish_backlinks_auth_expired_flip.)"""
    mock_pub.side_effect = AuthExpiredError(channel="medium", reason="HTTP 401")
    stdout, stderr, code = _run_publish(json.dumps(_payload("medium")), ["--platform", "medium", "--mode", "publish"])
    assert code == 3
    assert "_unverified" not in stdout


@patch("backlink_publisher.cli.publish_backlinks.verify_adapter_setup")
@patch("backlink_publisher.cli.publish_backlinks.adapter_publish")
@patch("backlink_publisher.cli._publish_helpers.verify_published")
def test_empty_live_url_is_not_verified_dofollow(mock_vp, mock_pub, mock_setup):
    """Empty published_url + draft_url → verify skipped. An empty URL must NOT
    count as verified-dofollow; documented as xfail until the gap is closed."""
    mock_pub.return_value = AdapterResult(
        status="published", adapter="medium-api", platform="medium",
        published_url="", draft_url="",
    )
    stdout, _, code = _run_publish(json.dumps(_payload("medium")), ["--mode", "publish"])
    out = json.loads(stdout.strip())
    # Desired (currently failing) invariant: empty URL ⇒ unverified, not clean.
    assert "unverified" in out["status"]
