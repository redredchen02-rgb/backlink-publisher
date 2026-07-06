"""Tests for cli.bind_channel — Plan 2026-05-19-001 Unit 2.

Locks the CLI contract:
- ``--channel <name>`` is required; argparse rejects missing
- Unknown ``<name>`` raises UsageError → exit_code=1 BEFORE any browser launch
- ``--channel ../etc/passwd`` payloads are rejected as unknown channel (defense-in-depth)
- Happy path emits the four EVENTS in order and exits 0
- Failure path emits ``channel.bind.failed`` and exits 3
- ``--help`` lists the CHANNELS members verbatim

No real Playwright; a fake browser runner is injected via the ``_browser_runner``
keyword on ``main()`` (production main() defaults to the real Playwright runner).
"""
from __future__ import annotations

__tier__ = "unit"
import json

import pytest

from backlink_publisher.cli import bind_channel as bc
from backlink_publisher.cli._bind.channels import CHANNELS


def _collect_events(out: str):
    return [json.loads(line) for line in out.strip().splitlines() if line.strip()]


class TestArgparse:
    def test_help_lists_channels(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--help"])
        assert excinfo.value.code == 0
        captured = capsys.readouterr().out
        for ch in CHANNELS:
            assert ch in captured

    def test_missing_channel_arg_exits_nonzero(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            bc.main([])
        assert excinfo.value.code != 0


class TestChannelValidation:
    def test_unknown_channel_exits_1_no_events(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "tiktok"])
        # UsageError → exit_code=1
        assert excinfo.value.code == 1
        # No JSONL events should have been emitted past parse failure
        out = capsys.readouterr().out
        assert "channel.bind.start" not in out

    def test_traversal_payload_rejected(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "../etc/passwd"])
        assert excinfo.value.code == 1


class TestHappyPath:
    def test_emits_four_events_in_order(self, monkeypatch, capsys):

        fake = _RecordingBrowserRunner(success=True)
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "velog"], _browser_runner=fake)
        assert excinfo.value.code == 0

        events = _collect_events(capsys.readouterr().out)
        assert [e["event"] for e in events] == [
            "channel.bind.start",
            "channel.bind.browser_ready",
            "channel.bind.login_detected",
            "channel.bind.persisted",
        ]
        # Every event carries channel name
        assert all(e["channel"] == "velog" for e in events)


class TestFailurePath:
    def test_predicate_timeout_exits_3_with_failed_event(self, capsys):
        fake = _RecordingBrowserRunner(success=True, predicate_timeout=True)
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "medium"], _browser_runner=fake)
        assert excinfo.value.code == 3

        events = _collect_events(capsys.readouterr().out)
        assert events[-1]["event"] == "channel.bind.failed"
        assert events[-1]["error_code"] == "bound_predicate_timeout"

    def test_playwright_launch_failure_exits_3(self, capsys):
        fake = _RecordingBrowserRunner(success=False, launch_error="playwright_launch_failed")
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "blogger"], _browser_runner=fake)
        assert excinfo.value.code == 3

        events = _collect_events(capsys.readouterr().out)
        assert events[-1]["event"] == "channel.bind.failed"


class TestCatchAllMessageScrubbed:
    """Plan D3 (R9) red-path security test: main()'s two catch-all except
    arms (`except PipelineError`, `except Exception`) used to emit
    `channel.bind.failed` with `message=str(exc)` completely unscrubbed —
    the actual unfiltered exit point on the stdout->WebUI chain (driver._emit
    -> webui_app/services/bind_job.py's BindJob.events list -> poll API,
    returned verbatim). Any exception outside run_bind()'s five enumerated
    types (PlaywrightLaunchError, BoundPredicateTimeout, IdentityMismatch,
    UsageError, PersistIOError) — e.g. a bare RuntimeError like
    chrome_backend.py:311's `_CdpClient.send()` raise — lands on the
    `except Exception` arm. This proves the final event's `message` field is
    scrub_text()-cleaned before it is emitted.
    """

    def test_unenumerated_runtimeerror_message_is_scrubbed(self, capsys):
        fake = _RaisingBrowserRunner(
            RuntimeError(
                "cdp error: session_token=abcdef0123456789abcdef0123456789ZZ"
            )
        )
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "velog"], _browser_runner=fake)
        assert excinfo.value.code == 5  # handle_unexpected_error's exit code

        events = _collect_events(capsys.readouterr().out)
        terminal = events[-1]
        assert terminal["event"] == "channel.bind.failed"
        assert terminal["error_code"] == "unexpected"
        assert "abcdef0123456789abcdef0123456789ZZ" not in terminal["message"]
        assert "<REDACTED>" in terminal["message"]

    def test_pipelineerror_message_is_scrubbed(self, capsys):
        from backlink_publisher._util.errors import ExternalServiceError

        fake = _RaisingBrowserRunner(
            ExternalServiceError(
                "upstream rejected: Authorization: Bearer abcdef0123456789abcdef0123456789"
            )
        )
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "velog"], _browser_runner=fake)
        assert excinfo.value.code == 4  # ExternalServiceError.exit_code

        events = _collect_events(capsys.readouterr().out)
        terminal = events[-1]
        assert terminal["event"] == "channel.bind.failed"
        assert terminal["error_code"] == "ExternalServiceError"
        assert "abcdef0123456789abcdef0123456789" not in terminal["message"]
        assert "<REDACTED>" in terminal["message"]

    def test_non_secret_message_passes_through(self, capsys):
        """Proves scrubbing doesn't over-redact ordinary diagnostic text."""
        fake = _RaisingBrowserRunner(RuntimeError("chrome binary not found"))
        with pytest.raises(SystemExit):
            bc.main(["--channel", "medium"], _browser_runner=fake)

        events = _collect_events(capsys.readouterr().out)
        terminal = events[-1]
        assert "chrome binary not found" in terminal["message"]


class _RaisingBrowserRunner:
    """Fake browser runner whose launch_and_wait raises a caller-supplied
    exception unconditionally — used to exercise the code paths outside
    run_bind()'s five enumerated exception types (constraint: whatever this
    raises must NOT be one of PlaywrightLaunchError/BoundPredicateTimeout/
    IdentityMismatch, or run_bind's own except-arms would catch it first)."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def launch_and_wait(self, *, recipe, on_browser_ready, on_login_detected):
        raise self._exc


# ───────── fake runner shared with driver tests ─────────


class _RecordingBrowserRunner:
    def __init__(
        self,
        *,
        success: bool = True,
        launch_error: str | None = None,
        predicate_timeout: bool = False,
        identity_mismatch: tuple[str, str] | None = None,
    ) -> None:
        self.success = success
        self.launch_error = launch_error
        self.predicate_timeout = predicate_timeout
        self.identity_mismatch = identity_mismatch

    def launch_and_wait(self, *, recipe, on_browser_ready, on_login_detected):
        from backlink_publisher.cli._bind import driver as drv
        if not self.success:
            raise drv.PlaywrightLaunchError(self.launch_error or "playwright_launch_failed")
        on_browser_ready()
        if self.predicate_timeout:
            raise drv.BoundPredicateTimeout()
        if self.identity_mismatch is not None:
            old, new = self.identity_mismatch
            raise drv.IdentityMismatch(old_account=old, new_account=new)
        on_login_detected()
        return _FakeStorageStateProvider()


class _FakeStorageStateProvider:
    def __call__(self, *, path):
        from pathlib import Path
        Path(path).write_text('{"cookies": [], "origins": []}')


# ─── Plan 2026-05-19-003 Unit 1 — IdentityMismatch CLI emission ───


class TestIdentityMismatchFailedEvent:
    """When run_bind returns BindResult with error_code='identity_mismatch',
    the CLI emits channel.bind.failed with error_code + old_account +
    new_account in the payload, and exits 3 (DependencyError class)."""

    def test_emits_failed_event_with_error_code(self, capsys):
        fake = _RecordingBrowserRunner(
            success=True, identity_mismatch=("alice", "bob")
        )
        with pytest.raises(SystemExit) as excinfo:
            bc.main(["--channel", "medium"], _browser_runner=fake)
        assert excinfo.value.code == 3

        events = _collect_events(capsys.readouterr().out)
        assert events[-1]["event"] == "channel.bind.failed"
        assert events[-1]["error_code"] == "identity_mismatch"

    def test_emits_extras_old_account_and_new_account(self, capsys):
        fake = _RecordingBrowserRunner(
            success=True, identity_mismatch=("alice", "bob")
        )
        with pytest.raises(SystemExit):
            bc.main(["--channel", "medium"], _browser_runner=fake)

        events = _collect_events(capsys.readouterr().out)
        terminal = events[-1]
        assert terminal["old_account"] == "alice"
        assert terminal["new_account"] == "bob"

    def test_non_identity_mismatch_failure_has_no_account_extras(self, capsys):
        """Regression: existing failure paths (predicate timeout, launch
        error) must not gain account extras."""
        fake = _RecordingBrowserRunner(success=True, predicate_timeout=True)
        with pytest.raises(SystemExit):
            bc.main(["--channel", "medium"], _browser_runner=fake)

        events = _collect_events(capsys.readouterr().out)
        terminal = events[-1]
        assert terminal["event"] == "channel.bind.failed"
        assert "old_account" not in terminal
        assert "new_account" not in terminal
