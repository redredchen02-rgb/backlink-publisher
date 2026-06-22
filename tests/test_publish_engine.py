"""U4-1/U4-3 (plan 2026-06-22-001): the in-process publish engine.

These tests drive ``publish_rows`` (the SystemExit-free in-process entry) and
``PublishOutcome.terminal_exit_code`` directly — the embedded-SDK path that does
NOT go through argparse / stdout / SystemExit. The CLI byte-parity net lives in
``test_publish_engine_golden.py``; this file pins the *typed* contract:

  - publish_rows NEVER raises SystemExit (the headline invariant) — not on
    success, partial failure, DependencyError, AuthExpiredError, mid-run token
    drift, or checkpoint-creation failure.
  - PublishOutcome.terminal_exit_code reproduces the epilogue's exit code (0/3/4/5)
    by branch *precedence* (the same pure _decide_publish_exit the epilogue
    dispatches off), so an embedded caller and the CLI can never disagree.
"""
from __future__ import annotations

__tier__ = "unit"
import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backlink_publisher._util.errors import (
    AuthExpiredError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.config import load_config
from backlink_publisher.cli.publish_backlinks._engine import (
    PublishOptions,
    PublishOutcome,
    PublishRunState,
    publish_rows,
)
from backlink_publisher.cli._publish_helpers import (
    PublishExitDecision,
    _decide_publish_exit,
    _publish_epilogue,
)
from backlink_publisher.linkcheck.verify import VerificationResult
from backlink_publisher.publishing.adapters.base import AdapterResult


# --------------------------------------------------------------------------- #
# Isolation: pin config/cache/token storage under tmp so the engine never
# touches the operator's real state. Env var drives token + dedup + config dir;
# _cache_dir patch drives checkpoints; store.path rebind drives canary/channel.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(cfg))
    with patch(
        "backlink_publisher.config._config_dir", return_value=cfg,
    ), patch(
        "backlink_publisher.checkpoint._cache_dir", return_value=tmp_path / "cache",
    ):
        from webui_store.channel_status import channel_status_store as _store
        old = _store.path
        _store.path = cfg / "channel-status.json"
        try:
            yield cfg
        finally:
            _store.path = old


def _payload(row_id="r0", platform="blogger"):
    return {
        "id": row_id, "platform": platform, "language": "en", "publish_mode": "draft",
        "target_url": "https://example.com/article", "main_domain": "https://example.com",
        "url_mode": "A", "title": "Test Article", "slug": "test-article",
        "excerpt": "An excerpt.", "tags": ["tag1"],
        "content_markdown": "Content about https://example.com page.",
        "links": [
            {"url": "https://example.com", "anchor": "Example", "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article", "kind": "target", "required": True},
        ],
        "seo": {"title": "T", "description": "D", "canonical_url": "https://example.com/article"},
    }


def _ok(platform="blogger"):
    return AdapterResult(
        status="drafted", adapter=f"{platform}-api", platform=platform,
        draft_url=f"https://{platform}.example.com/p/1",
    )


def _opts(**kw):
    base = dict(
        mode="draft", skip_publish_time_check=True, no_verify=True,
        throttle_min=0, throttle_max=0,
    )
    base.update(kw)
    return PublishOptions(**base)


def _run_rows(side_effect, rows, options):
    """Drive publish_rows with a patched adapter seam. Asserts NO SystemExit."""
    with patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = side_effect
        try:
            return publish_rows(rows, load_config(), options=options)
        except SystemExit as exc:  # the invariant this whole file guards
            pytest.fail(f"publish_rows raised SystemExit({exc.code}) — must be SystemExit-free")


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_dry_run_two_rows_exit0_no_systemexit():
    outcome = _run_rows(
        [_ok(), _ok()],
        [_payload("a"), _payload("b")],
        _opts(dry_run=True),
    )
    assert isinstance(outcome, PublishOutcome)
    assert outcome.success_count == 2
    assert outcome.terminal_exit_code == 0
    assert not outcome.auth_aborted and not outcome.dependency_aborted
    # dry-run outputs carry the draft url + the dry-run marker
    assert all(o["draft_url"] for o in outcome.outputs)
    assert all(o.get("_dry_run") for o in outcome.outputs)


def test_live_single_success_exit0():
    outcome = _run_rows([_ok()], [_payload("a")], _opts())
    assert outcome.success_count == 1 and outcome.fail_count == 0
    assert outcome.terminal_exit_code == 0


# --------------------------------------------------------------------------- #
# DependencyError → typed abort (NOT SystemExit), exit 3, whole batch stops
# --------------------------------------------------------------------------- #
def test_dependency_error_aborts_typed_exit3():
    outcome = _run_rows([DependencyError("oauth missing")], [_payload("a")], _opts())
    assert outcome.dependency_aborted is True
    assert outcome.terminal_exit_code == 3
    assert outcome.success_count == 0 and outcome.fail_count == 0


def test_ok_then_dependency_error_aborts_whole_batch():
    """row0 succeeds (in state) then row1 DependencyError aborts the run; the
    outcome is exit 3 regardless of the prior success (immediate-abort)."""
    outcome = _run_rows(
        [_ok(), DependencyError("oauth missing")],
        [_payload("a"), _payload("b")],
        _opts(),
    )
    assert outcome.dependency_aborted is True
    assert outcome.terminal_exit_code == 3


# --------------------------------------------------------------------------- #
# Mid-run token drift (rotated credentials) → typed abort, exit 3, stops the run
# --------------------------------------------------------------------------- #
def test_token_drift_midrun_aborts_typed_exit3():
    from backlink_publisher.config.tokens import save_blogger_token

    save_blogger_token({"client_id": "a", "client_secret": "b"})  # rev=1 at run-start

    def rotate_on_first(*a, **k):
        # Simulate the WebUI saving a new token between row0 and row1.
        save_blogger_token({"client_id": "new", "client_secret": "new"})  # rev=2
        return _ok()

    with patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
        mock_pub.side_effect = rotate_on_first
        try:
            outcome = publish_rows(
                [_payload("a"), _payload("b")], load_config(), options=_opts(),
            )
        except SystemExit as exc:
            pytest.fail(f"token drift raised SystemExit({exc.code}) — must be typed")

    assert outcome.dependency_aborted is True
    assert outcome.terminal_exit_code == 3
    # The safety property: row1 was NOT published with the rotated credential —
    # the drift check fires before row1's adapter call, so only row0 ran.
    assert mock_pub.call_count == 1


# --------------------------------------------------------------------------- #
# AuthExpiredError → typed abort, exit 3, side effects still run (channel flip)
# --------------------------------------------------------------------------- #
def test_auth_expired_aborts_typed_exit3_and_flips_channel():
    from webui_store.channel_status import get_status

    outcome = _run_rows(
        [AuthExpiredError(channel="medium", reason="HTTP 401")],
        [_payload("a", platform="medium")],
        _opts(platform="medium"),
    )
    assert outcome.auth_aborted is True
    assert outcome.terminal_exit_code == 3
    assert outcome.state.auth_error_class == "AuthExpiredError"
    # R3a side effects preserved even though no SystemExit fired in the loop:
    assert get_status("medium")["status"] == "expired"


# --------------------------------------------------------------------------- #
# Partial success → exit 4, successful row retained in outputs
# --------------------------------------------------------------------------- #
def test_partial_ok_then_external_error_exit4():
    outcome = _run_rows(
        [_ok(), ExternalServiceError("svc down")],
        [_payload("a"), _payload("b")],
        _opts(),
    )
    assert outcome.success_count == 1 and outcome.fail_count == 1
    assert outcome.terminal_exit_code == 4
    # _decide_publish_exit keeps only the successful row in `successful`
    decision = _decide_publish_exit(
        outcome.outputs, dry_run=False, dedup_hold_count=0,
    )
    assert len(decision.successful) == 1 and decision.successful[0]["error"] is None
    assert len(decision.failed) == 1


# --------------------------------------------------------------------------- #
# Checkpoint creation fail-soft → run completes, outcome carries the flag
# --------------------------------------------------------------------------- #
def test_checkpoint_create_failure_is_fail_soft():
    with patch(
        "backlink_publisher.cli.publish_backlinks.checkpoint.create_checkpoint",
        side_effect=OSError("disk full"),
    ):
        outcome = _run_rows([_ok()], [_payload("a")], _opts())
    assert outcome.checkpoint_disabled is True
    assert outcome.success_count == 1
    assert outcome.terminal_exit_code == 0


# --------------------------------------------------------------------------- #
# terminal_exit_code matrix: prove the verdict is by branch PRECEDENCE, not by
# count, by cross-checking the pure decision against the REAL epilogue's exit.
# --------------------------------------------------------------------------- #
def _ok_row(rid="a"):
    return {"id": rid, "platform": "blogger", "status": "drafted", "error": None}


def _unverified_row(rid="b"):
    return {"id": rid, "platform": "blogger", "status": "published_unverified", "error": None}


def _fail_row(rid="c"):
    return {"id": rid, "platform": "blogger", "status": "failed", "error": "boom"}


def _epilogue_exit(outputs, *, dry_run, dedup_hold_count):
    """Run the REAL impure epilogue, capturing the exit code it raises (0 if it
    returns without exiting). stdout/stderr are swallowed."""
    args = SimpleNamespace(dry_run=dry_run, reconcile=False, reconcile_all=False)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            _publish_epilogue(
                outputs, [], args, None, 0, 0, 0,
                dedup_hold_count=dedup_hold_count,
            )
            return 0
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1


@pytest.mark.parametrize(
    "outputs, dry_run, holds, expected",
    [
        ([_fail_row("a"), _fail_row("b")], False, 1, 4),   # 2 fail + 1 held -> 4 (fail wins)
        ([], False, 2, 3),                                 # 0 success + holds>0 -> 3
        ([_ok_row(), _unverified_row()], False, 0, 5),     # success + unverified -> 5
        ([_fail_row(), _unverified_row()], False, 0, 4),   # 1 fail + 1 unverified -> 4 (fail wins)
        ([_ok_row(), _ok_row("d")], False, 0, 0),          # all clean -> 0
        ([], False, 0, 5),                                 # nothing published, no holds -> 5
        ([_ok_row()], True, 0, 0),                          # dry-run success -> 0
    ],
)
def test_decision_matches_epilogue_by_precedence(outputs, dry_run, holds, expected):
    decision = _decide_publish_exit(outputs, dry_run=dry_run, dedup_hold_count=holds)
    assert decision.exit_code == expected, f"pure decision: {decision.kind}"
    assert _epilogue_exit(outputs, dry_run=dry_run, dedup_hold_count=holds) == expected, (
        "impure epilogue diverged from the pure decision"
    )


def test_decision_is_pure_dataclass():
    d = _decide_publish_exit([_ok_row()], dry_run=False, dedup_hold_count=0)
    assert isinstance(d, PublishExitDecision)
    assert d.kind == "ok" and d.exit_code == 0


def test_force_manifest_conflict_aborts_typed_exit1_no_systemexit():
    """A force on a live 'done' key (R11) is the FOURTH in-loop kill point (the
    plan's enumeration missed it). It must abort with exit 1 (UsageError, NOT 3)
    via a typed sentinel — publish_rows stays SystemExit-free even with
    forced_keys."""
    row = _payload("a", platform="medium")
    # gate_with_force is late-imported by the loop from _dedup_gate; patch it there
    # to return the 'conflict' verdict (it no longer SystemExits — that is the fix).
    with patch(
        "backlink_publisher.cli._dedup_gate.gate_with_force",
        return_value=("conflict", None),
    ):
        with patch("backlink_publisher.cli.publish_backlinks.adapter_publish") as mock_pub:
            mock_pub.return_value = _ok("medium")
            try:
                outcome = publish_rows(
                    [row], load_config(),
                    options=_opts(platform="medium"),
                    forced_keys={("dummy",)},
                )
            except SystemExit as exc:
                pytest.fail(f"force-conflict raised SystemExit({exc.code}) — must be typed")

    assert outcome.state.conflict_aborted is True
    assert outcome.terminal_exit_code == 1
    assert "force-manifest conflict" in (outcome.state.conflict_error or "")
    # conflict aborts before the adapter is ever called
    assert mock_pub.call_count == 0


def test_terminal_exit_code_short_circuits_on_abort():
    """Even with a 'clean' output set, an abort flag forces exit 3 (the
    AuthExpiredError / DependencyError family), so a consumer never reads a
    stale 0 after an aborted run."""
    st = PublishRunState(outputs=[_ok_row()])
    st.dependency_aborted = True
    oc = PublishOutcome(state=st, options=_opts())
    assert oc.terminal_exit_code == 3

    st2 = PublishRunState(outputs=[_ok_row()])
    st2.auth_aborted = True
    oc2 = PublishOutcome(state=st2, options=_opts())
    assert oc2.terminal_exit_code == 3
