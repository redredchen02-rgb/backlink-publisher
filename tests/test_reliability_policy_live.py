"""Live end-to-end verification of the reliability policy enforce path.

Plan: docs/plans/2026-06-03-007-feat-live-verify-reliability-policy-plan.md

Unlike ``test_reliability_policy.py`` (which calls ``publish_with_policy``
directly), these tests drive the REAL CLI loop body (``run_publish_loop`` →
``_publish_one_row``) with ``BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED``
actually flipped, so the genuinely-untested ``if policy_enabled()`` call-site
branch (``_engine.py``) and the module-level import seam (``_resume.py``)
execute. The policy *behaviors* (R2–R5) are layered on top as regression
coverage on a non-browser-tier platform (``fake``) — see R6.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from backlink_publisher.config import load_config
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.cli.publish_backlinks._engine import (
    PublishRunState,
    run_publish_loop,
)
from backlink_publisher.cli._resume import (
    _ResumeLoopState,
    _publish_one_resume_item,
)

_ENGINE_NS = "backlink_publisher.cli.publish_backlinks"
_RESUME_NS = "backlink_publisher.cli._resume"
_POLICY_ENV = "BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED"

_TS = "2026-06-03T00:00:00+00:00"


def _make_args(**over):
    """Minimal ``args`` stub for the publish loop.

    ``dry_run=False`` is load-bearing: the dry-run branch (``_engine.py:181``)
    calls ``adapter_publish`` unconditionally *before* the policy branch, which
    would corrupt the R1 negative assertion. ``skip_publish_time_check=True``
    bypasses the reachability gate so a single fake row reaches line 237.
    """
    base = dict(
        platform=None,        # fall back to row["platform"]
        mode="draft",
        dry_run=False,
        skip_publish_time_check=True,
        no_verify=True,
        reason=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _fake_row(platform="fake", rid="t1"):
    return {
        "id": rid,
        "platform": platform,
        "target_url": "https://example.com/landing",
        "anchor_text": "example",
        "title": "Example Title",
        "body_markdown": "Body.",
    }


def _ok_result(platform="fake"):
    return AdapterResult(
        status="drafted",
        adapter=platform,
        platform=platform,
        draft_url="https://fake.example/p/1",
    )


def _run_one(row, args):
    """Drive a single row through the real publish loop."""
    config = load_config()
    state = PublishRunState()
    run_publish_loop(
        [row], args, config, state, _TS,
        None,            # banner_emit
        set(),           # forced_keys
        0, 0,            # throttle_min, throttle_max
        {},              # initial_token_revs
    )
    return state


# ── R1: the primary risk — call-site branch selection (engine seam) ─────────


class TestR1EngineSeam:
    """flag=1 routes the engine through publish_with_policy, not adapter_publish."""

    def test_flag_on_routes_through_policy(self, fake_platform_registered, monkeypatch):
        monkeypatch.setenv(_POLICY_ENV, "1")
        with mock.patch(f"{_ENGINE_NS}.publish_with_policy",
                        return_value=_ok_result()) as pwp, \
             mock.patch(f"{_ENGINE_NS}.adapter_publish",
                        return_value=_ok_result()) as ap:
            _run_one(_fake_row(), _make_args())
        assert pwp.called, "policy path must fire when flag=1"
        assert not ap.called, "direct adapter_publish branch must NOT fire when flag=1"

    def test_flag_off_is_passthrough(self, fake_platform_registered, monkeypatch):
        monkeypatch.delenv(_POLICY_ENV, raising=False)
        with mock.patch(f"{_ENGINE_NS}.publish_with_policy",
                        return_value=_ok_result()) as pwp, \
             mock.patch(f"{_ENGINE_NS}.adapter_publish",
                        return_value=_ok_result()) as ap:
            _run_one(_fake_row(), _make_args())
        assert ap.called, "direct adapter_publish must fire when flag unset"
        assert not pwp.called, "policy path must NOT fire when flag unset"

    def test_flag_zero_is_passthrough(self, fake_platform_registered, monkeypatch):
        monkeypatch.setenv(_POLICY_ENV, "0")
        with mock.patch(f"{_ENGINE_NS}.publish_with_policy",
                        return_value=_ok_result()) as pwp, \
             mock.patch(f"{_ENGINE_NS}.adapter_publish",
                        return_value=_ok_result()) as ap:
            _run_one(_fake_row(), _make_args())
        assert ap.called and not pwp.called, "flag='0' must be treated as off"

    def test_dry_run_does_not_pollute_negative_assertion(
        self, fake_platform_registered, monkeypatch
    ):
        # Guard: with dry_run=True adapter_publish fires via the dry-run branch
        # regardless of the flag. The R1 harness pins dry_run=False; confirm the
        # dry-run path is the one that would otherwise break the assertion.
        monkeypatch.setenv(_POLICY_ENV, "1")
        with mock.patch(f"{_ENGINE_NS}.publish_with_policy",
                        return_value=_ok_result()) as pwp, \
             mock.patch(f"{_ENGINE_NS}.adapter_publish",
                        return_value=_ok_result()) as ap:
            _run_one(_fake_row(), _make_args(dry_run=True))
        assert ap.called, "dry-run branch calls adapter_publish before policy"
        assert not pwp.called, "policy path is not reached under dry_run"


_RUN_ID = "20260603T084759-abcdef12"  # matches checkpoint._RUN_ID_RE


def _run_one_resume(item, args, **over):
    """Drive a single item through the real resume body.

    The success tail calls ``checkpoint.update_item`` (unguarded) for a run_id
    with no checkpoint file; patch it to a no-op so the seam test stays focused
    on dispatch routing rather than checkpoint persistence.
    """
    state = _ResumeLoopState()
    kwargs = dict(
        ckpt={}, config=load_config(), banner_emit=None,
        run_id=_RUN_ID, args=args, throttle_min=0, throttle_max=0,
    )
    kwargs.update(over)
    with mock.patch("backlink_publisher.checkpoint.update_item"):
        _publish_one_resume_item(item, 0, state, **kwargs)


class TestR1ResumeSeam:
    """The resume path imports the seam at module top (different namespace)."""

    def test_flag_on_routes_through_policy(self, fake_platform_registered, monkeypatch):
        monkeypatch.setenv(_POLICY_ENV, "1")
        item = {"id": "t1", "payload": _fake_row()}
        with mock.patch(f"{_RESUME_NS}.publish_with_policy",
                        return_value=_ok_result()) as pwp, \
             mock.patch(f"{_RESUME_NS}.adapter_publish",
                        return_value=_ok_result()) as ap:
            _run_one_resume(item, _make_args())
        assert pwp.called and not ap.called, "resume must route via policy when flag=1"

    def test_flag_off_is_passthrough(self, fake_platform_registered, monkeypatch):
        monkeypatch.delenv(_POLICY_ENV, raising=False)
        item = {"id": "t1", "payload": _fake_row()}
        with mock.patch(f"{_RESUME_NS}.publish_with_policy",
                        return_value=_ok_result()) as pwp, \
             mock.patch(f"{_RESUME_NS}.adapter_publish",
                        return_value=_ok_result()) as ap:
            _run_one_resume(item, _make_args())
        assert ap.called and not pwp.called, "resume passthrough when flag unset"
