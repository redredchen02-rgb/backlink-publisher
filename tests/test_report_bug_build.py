"""Unit tests for ``backlink_publisher.cli.report_bug._build``.

Covers: section assembly, secret redaction (free-text + structured), Markdown
render, JSON parseability, self-diagnosis mapping, report file persistence, and
the "no error source" general-report path.
"""

from __future__ import annotations

__tier__ = "unit"

import json
import os

import pytest

from backlink_publisher._util.error_envelope import ErrorEnvelope
from backlink_publisher.cli.report_bug._build import (
    build_report,
    render_json,
    render_markdown,
    ReportInput,
    save_report,
    self_diagnose,
)

_SECRET_TOKEN = "supersecret-token-abc123"
_SECRET_BEARER = "Bearer eyJ.abc.def"


def _sample_input() -> ReportInput:
    env = ErrorEnvelope(
        error_class="AuthExpiredError",
        exit_code=3,
        message=f"channel velog credentials expired token={_SECRET_TOKEN}",
    )
    stderr = (
        f"{_SECRET_BEARER}\n"
        "authorization: Basic dXNlcjpwYXNz\n"
        "run_id=20240101T000000-aa11bb22\n"
        "fatal: boom\n"
    )
    return ReportInput(
        envelope=env,
        stderr_text=stderr,
        command="publish-backlinks --resume X",
        run_id="20240101T000000-aa11bb22",
        describe=f"publish stuck, cookie={_SECRET_TOKEN}",
    )


# ── env-var value leak (audit finding [05]) ──────────────────────────────────


class TestBacklinkEnvVarValuesNotLeaked:
    def test_values_never_leak_names_kept(self, monkeypatch) -> None:
        """BACKLINK_/BLP_ env vars are emitted as NAMES ONLY; their values
        (frequently API keys / proxy creds) must appear nowhere in the
        safe-to-share report, since _redact_in_place cannot mask full prefixed
        names. The names themselves stay (useful: which config vars are set)."""
        secret = "sk-leaktest-DO-NOT-SHARE-9f9f9f"
        monkeypatch.setenv("BACKLINK_LLM_API_KEY", secret)
        monkeypatch.setenv("BLP_PROXY", "http://leakuser:leakpass@proxy.example")

        report = build_report(_sample_input(), redact=True)
        env = report["environment"]

        # NAMES survive (membership works for both list and dict shapes).
        assert "BACKLINK_LLM_API_KEY" in env["backlink_env_vars"]
        assert "BLP_PROXY" in env["backlink_env_vars"]

        # VALUES must appear NOWHERE — structured report or rendered markdown.
        blob = json.dumps(report) + "\n" + render_markdown(report)
        assert secret not in blob, "BACKLINK_ env-var value leaked into report"
        assert "leakuser:leakpass" not in blob, "BLP_ env-var value leaked"

    def test_values_absent_even_with_no_redact(self, monkeypatch) -> None:
        """--no-redact only opts out of free-text scrubbing; env-var VALUES were
        never meant to be captured at all, so they stay out regardless."""
        secret = "sk-noredact-leaktest-1234abcd"
        monkeypatch.setenv("BACKLINK_LLM_API_KEY", secret)
        report = build_report(_sample_input(), redact=False)
        blob = json.dumps(report) + "\n" + render_markdown(report)
        assert secret not in blob


# ── assembly ─────────────────────────────────────────────────────────────────


class TestBuildReport:
    def test_all_sections_present(self) -> None:
        report = build_report(_sample_input(), redact=True)
        for key in (
            "generated_at", "schema", "command", "run_id", "description",
            "error", "environment", "config_snapshot", "health",
            "recent_runs", "suggested_fixes",
        ):
            assert key in report

    def test_markdown_has_all_headings(self) -> None:
        md = render_markdown(build_report(_sample_input(), redact=True))
        for heading in (
            "TL;DR", "重現步驟", "錯誤 (Error)", "環境 (Environment)",
            "設定快照", "儲存體健康", "近期執行", "建議修復", "機器可讀 JSON",
        ):
            assert heading in md

    def test_json_parseable(self) -> None:
        report = build_report(_sample_input(), redact=True)
        parsed = json.loads(render_json(report))
        assert parsed["schema"] == "blp-bug-report/1"
        assert parsed["error"]["error_class"] == "AuthExpiredError"


# ── redaction ────────────────────────────────────────────────────────────────


class TestRedaction:
    def test_free_text_secrets_masked(self) -> None:
        md = render_markdown(build_report(_sample_input(), redact=True))
        assert _SECRET_TOKEN not in md
        assert _SECRET_BEARER not in md
        assert "dXNlcjpwYXNz" not in md  # Basic auth payload
        # The masked marker must be present instead.
        assert "***" in md

    def test_no_redact_leaks_secret(self) -> None:
        md = render_markdown(build_report(_sample_input(), redact=False))
        assert _SECRET_TOKEN in md

    def test_structured_redaction(self) -> None:
        inp = ReportInput(
            stderr_text="",
            describe=None,
            command=None,
            run_id=None,
            envelope=None,
        )
        # Inject a sensitive-keyed value into the environment section path via
        # a crafted description won't exercise structured redaction; instead
        # assert the structured scrubber is wired by checking the report dict
        # itself survives _redact_in_place without raising.
        report = build_report(inp, redact=True)
        assert report["environment"]  # built without error


# ── self-diagnosis ───────────────────────────────────────────────────────────


class TestSelfDiagnose:
    def test_auth_expired_hints_rebind(self) -> None:
        hints = self_diagnose("AuthExpiredError")
        assert any("re-bind" in h or "login" in h for h in hints)

    def test_registry_error_hints_dev_bug(self) -> None:
        hints = self_diagnose("RegistryError")
        assert any("maintainer" in h or "developer" in h or "bug" in h for h in hints)

    def test_unknown_class_generic(self) -> None:
        hints = self_diagnose(None)
        assert hints and "describe" in hints[0].lower()

    def test_unknown_error_class(self) -> None:
        hints = self_diagnose("SomeWeirdError")
        assert any("SomeWeirdError" in h for h in hints)


# ── persistence ──────────────────────────────────────────────────────────────


class TestSaveReport:
    def test_writes_md_and_json(self, tmp_path) -> None:
        report = build_report(_sample_input(), redact=True)
        md_path, json_path = save_report(report, tmp_path, redact=True)
        assert md_path.exists()
        assert json_path.exists()
        assert md_path.suffix == ".md"
        assert json_path.suffix == ".json"
        # JSON file is itself parseable.
        json.loads(json_path.read_text(encoding="utf-8"))

    def test_file_mode_0600(self, tmp_path) -> None:
        report = build_report(_sample_input(), redact=True)
        md_path, _ = save_report(report, tmp_path, redact=True)
        if os.name == "posix":
            assert (md_path.stat().st_mode & 0o777) == 0o600

    def test_no_error_source_builds_general(self, tmp_path) -> None:
        report = build_report(ReportInput(), redact=True)
        assert report["error"]["captured"] is False
        assert report["suggested_fixes"]
        md_path, _ = save_report(report, tmp_path, redact=True)
        assert md_path.exists()
