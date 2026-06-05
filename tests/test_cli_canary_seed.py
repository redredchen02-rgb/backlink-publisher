"""Tests for canary-seed CLI (Plan 2026-06-02-003 Unit 2).

Tests cover the verdict mapping logic first (per test-first Execution note),
then the full flow: uncertain cohort gate, credential check, publish+sleep,
post_url extraction, inspect_target_anchor call, JSONL output shape.

Patching convention (per feedback_mock_patch_paths_after_extraction):
  - patch at the module's local reference: ``canary_seed.inspect_target_anchor``,
    ``canary_seed.publish``, ``canary_seed.verify_adapter_setup``, etc.
  - ``_sleep`` patched to no-op so no test ever actually sleeps.
  - SSRF guard patched via ``canary_seed._ssrf_check``.

conftest autouse fixtures apply (sockets blocked, config dir sandboxed).
"""
from __future__ import annotations

__tier__ = "unit"
import json
import time
from unittest.mock import MagicMock, patch

import pytest

import backlink_publisher.cli.canary_seed as cs
from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher._util.errors import DependencyError, UsageError


# ── helpers ──────────────────────────────────────────────────────────────────


def _adapter_result(
    *,
    status: str = "published",
    published_url: str = "https://platform.example/test-post",
    draft_url: str = "",
) -> AdapterResult:
    return AdapterResult(
        status=status,
        adapter="test-api",
        platform="hashnode",
        published_url=published_url,
        draft_url=draft_url,
    )


def _anchor(
    *,
    page_readable: bool = True,
    target_anchor_found: bool = True,
    target_is_nofollow: bool = False,
    target_rel: str | None = None,
    reason: str | None = None,
) -> dict:
    return {
        "page_readable": page_readable,
        "target_anchor_found": target_anchor_found,
        "target_is_nofollow": target_is_nofollow,
        "target_rel": target_rel,
        "reason": reason,
    }


def _run(
    argv: list[str],
    *,
    dofollow_status_map: dict | None = None,
    visibility_map: dict | None = None,
    publish_return=None,
    publish_side_effect=None,
    anchor_return=None,
    verify_side_effect=None,
) -> tuple[int, str, str]:
    """Run cs.main(argv) with all network calls mocked.

    Returns (exit_code, stdout, stderr).

    ``visibility_map`` mocks ``registry.visibility`` per-platform; any platform
    not listed defaults to ``"active"`` so the canary-eligibility gate only
    rejects platforms explicitly marked ``"retired"`` here. This mirrors the
    ``dofollow_status_map`` pattern and keeps the unit isolated from registry
    visibility churn.
    """
    if dofollow_status_map is None:
        dofollow_status_map = {"hashnode": "uncertain", "substack": "uncertain"}
    if visibility_map is None:
        visibility_map = {}

    publish_kw = {}
    if publish_side_effect is not None:
        publish_kw["side_effect"] = publish_side_effect
    elif publish_return is not None:
        publish_kw["return_value"] = publish_return
    else:
        publish_kw["return_value"] = _adapter_result()

    anchor_kw = {"return_value": anchor_return if anchor_return is not None else _anchor()}

    verify_kw = {}
    if verify_side_effect is not None:
        verify_kw["side_effect"] = verify_side_effect
    else:
        verify_kw["return_value"] = None  # offline check passes silently

    with patch.object(cs, "dofollow_status", side_effect=lambda p: dofollow_status_map.get(p)), \
         patch.object(cs, "visibility", side_effect=lambda p: visibility_map.get(p, "active")), \
         patch.object(cs, "verify_adapter_setup", **verify_kw), \
         patch.object(cs, "publish", **publish_kw), \
         patch.object(cs, "inspect_target_anchor", **anchor_kw), \
         patch.object(cs, "_sleep", lambda *_a, **_k: None), \
         patch.object(cs, "_ssrf_check", return_value=None):
        import io
        import sys
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        exit_code = 0
        try:
            cs.main(argv)
        except SystemExit as e:
            exit_code = int(e.code) if e.code is not None else 0
        finally:
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            sys.stdout, sys.stderr = old_stdout, old_stderr
        return exit_code, stdout, stderr


def _parse_jsonl(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


# ── Verdict mapping (test-first — these define the canonical verdict logic) ──


class TestVerdictMapping:
    """Verdict classification from inspect_target_anchor return values."""

    def test_dofollow_verdict(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(page_readable=True, target_anchor_found=True, target_is_nofollow=False),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert len(receipts) == 1
        assert receipts[0]["verdict"] == "dofollow"

    def test_nofollow_verdict(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(target_anchor_found=True, target_is_nofollow=True),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert receipts[0]["verdict"] == "nofollow"

    def test_ambiguous_page_not_readable(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(page_readable=False),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert receipts[0]["verdict"] == "ambiguous"

    def test_ambiguous_anchor_not_found(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(target_anchor_found=False),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        r = receipts[0]
        assert r["verdict"] == "ambiguous"
        assert r["needs_browser_check"] is True

    def test_ambiguous_no_post_url(self):
        """Both published_url and draft_url empty → ambiguous, no inspect_target_anchor call."""
        rc, stdout, stderr = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            publish_return=_adapter_result(published_url="", draft_url=""),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        r = receipts[0]
        assert r["verdict"] == "ambiguous"
        assert r.get("reason") == "no_post_url_returned"

    def test_ambiguous_publish_failed(self):
        """publish() exception → ambiguous verdict, exit 0."""
        from backlink_publisher._util.errors import ExternalServiceError
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            publish_side_effect=ExternalServiceError("API error"),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert receipts[0]["verdict"] == "ambiguous"
        assert receipts[0].get("reason") == "publish_failed"


# ── Cohort gate ───────────────────────────────────────────────────────────────


class TestCohortGate:
    """Platform must be in dofollow=uncertain cohort."""

    def test_wrong_cohort_true(self):
        rc, stdout, stderr = _run(
            ["blogger", "--target-url", "https://mysite.com"],
            dofollow_status_map={"blogger": True},
        )
        assert rc == 1
        assert "uncertain" in stderr.lower() or "uncertain" in stdout.lower()

    def test_wrong_cohort_false(self):
        rc, stdout, stderr = _run(
            ["linkedin", "--target-url", "https://mysite.com"],
            dofollow_status_map={"linkedin": False},
        )
        assert rc == 1

    def test_unknown_platform(self):
        rc, stdout, stderr = _run(
            ["nonexistent", "--target-url", "https://mysite.com"],
            dofollow_status_map={},
        )
        assert rc == 1

    def test_valid_uncertain_platform_passes(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            dofollow_status_map={"hashnode": "uncertain"},
        )
        assert rc == 0
        assert _parse_jsonl(stdout)

    def test_retired_uncertain_platform_rejected(self):
        """A platform still flagged dofollow='uncertain' but visibility='retired'
        (e.g. writeas, hashnode) is NOT canary-eligible — publishing it would
        fail on missing credentials and surface a misleading publish_failed."""
        rc, stdout, stderr = _run(
            ["writeas", "--target-url", "https://mysite.com"],
            dofollow_status_map={"writeas": "uncertain"},
            visibility_map={"writeas": "retired"},
        )
        assert rc == 1
        assert "retired" in stderr.lower()
        assert _parse_jsonl(stdout) == []

    def test_eligible_hint_excludes_retired(self):
        """The 'Eligible platforms' hint omits retired-but-uncertain platforms."""
        rc, _, stderr = _run(
            ["blogger", "--target-url", "https://mysite.com"],
            dofollow_status_map={
                "blogger": True,
                "substack": "uncertain",
                "writeas": "uncertain",
            },
            visibility_map={"writeas": "retired"},
        )
        assert rc == 1
        assert "substack" in stderr
        assert "writeas" not in stderr


# ── Credential gate ───────────────────────────────────────────────────────────


class TestCredentialGate:
    """verify_adapter_setup failure → DependencyError, exit 3."""

    def test_no_credential_exit_3(self):
        rc, _, stderr = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            verify_side_effect=DependencyError("no credential for hashnode"),
        )
        assert rc == 3
        assert "hashnode" in stderr.lower() or "credential" in stderr.lower()


# ── JSONL output shape ────────────────────────────────────────────────────────


class TestJsonlShape:
    """Verify all required fields are present in the JSONL receipt."""

    REQUIRED = {"platform", "post_url", "target_url", "verdict", "rel_tokens",
                "needs_browser_check", "delete_hint", "delete_credential",
                "fetched_at", "duration_s"}

    def test_all_fields_present(self):
        rc, stdout, _ = _run(["hashnode", "--target-url", "https://mysite.com"])
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert len(receipts) == 1
        missing = self.REQUIRED - set(receipts[0].keys())
        assert not missing, f"Missing fields: {missing}"

    def test_delete_credential_none_when_adapter_exposes_no_meta(self):
        rc, stdout, _ = _run(["hashnode", "--target-url", "https://mysite.com"])
        assert _parse_jsonl(stdout)[0]["delete_credential"] is None

    def test_delete_credential_surfaced_from_provider_meta(self):
        """edit_code in _provider_meta → receipt carries it + delete_hint includes it."""
        result = _adapter_result()
        result._provider_meta = {"edit_code": "s3cr3t", "link_attr_verification": {"x": 1}}
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            publish_return=result,
        )
        receipt = _parse_jsonl(stdout)[0]
        # Only the delete-relevant key is lifted, not the whole provider_meta.
        assert receipt["delete_credential"] == {"edit_code": "s3cr3t"}
        assert "s3cr3t" in receipt["delete_hint"]

    def test_platform_and_target_url_correct(self):
        rc, stdout, _ = _run(["hashnode", "--target-url", "https://mysite.com"])
        receipts = _parse_jsonl(stdout)
        assert receipts[0]["platform"] == "hashnode"
        assert receipts[0]["target_url"] == "https://mysite.com"

    def test_post_url_from_published_url(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            publish_return=_adapter_result(published_url="https://platform.example/pub", draft_url=""),
        )
        receipts = _parse_jsonl(stdout)
        assert receipts[0]["post_url"] == "https://platform.example/pub"

    def test_post_url_fallback_draft_url(self):
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            publish_return=_adapter_result(published_url="", draft_url="https://platform.example/draft"),
        )
        receipts = _parse_jsonl(stdout)
        assert receipts[0]["post_url"] == "https://platform.example/draft"


# ── Sleep seam ────────────────────────────────────────────────────────────────


class TestWaitAfterPublish:
    """--wait-after-publish is respected."""

    def test_default_sleep_called(self):
        calls = []
        with patch.object(cs, "dofollow_status", return_value="uncertain"), \
             patch.object(cs, "visibility", return_value="active"), \
             patch.object(cs, "verify_adapter_setup", return_value=None), \
             patch.object(cs, "publish", return_value=_adapter_result()), \
             patch.object(cs, "inspect_target_anchor", return_value=_anchor()), \
             patch.object(cs, "_ssrf_check", return_value=None), \
             patch.object(cs, "_sleep", side_effect=lambda s: calls.append(s)):
            import io, sys
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                cs.main(["hashnode", "--target-url", "https://mysite.com"])
            except SystemExit:
                pass
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
        assert calls == [15]

    def test_custom_wait_respected(self):
        calls = []
        with patch.object(cs, "dofollow_status", return_value="uncertain"), \
             patch.object(cs, "visibility", return_value="active"), \
             patch.object(cs, "verify_adapter_setup", return_value=None), \
             patch.object(cs, "publish", return_value=_adapter_result()), \
             patch.object(cs, "inspect_target_anchor", return_value=_anchor()), \
             patch.object(cs, "_ssrf_check", return_value=None), \
             patch.object(cs, "_sleep", side_effect=lambda s: calls.append(s)):
            import io, sys
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                cs.main(["hashnode", "--target-url", "https://mysite.com", "--wait-after-publish", "5"])
            except SystemExit:
                pass
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
        assert calls == [5]


# ── CI clean import ───────────────────────────────────────────────────────────


class TestCiCleanImport:
    """Module imports without network calls in socket-blocked conftest env."""

    def test_import_clean(self):
        import importlib
        importlib.reload(cs)
        assert hasattr(cs, "main")


# ── Stderr flip-hint (Plan 2026-06-05-011 Unit 2) ─────────────────────────────


class TestStderrFlipHint:
    """The new stderr summary + guided edit checklist must not regress stdout."""

    _STDOUT_KEYS = {"platform", "post_url", "target_url", "verdict", "rel_tokens",
                    "needs_browser_check", "delete_hint", "delete_credential",
                    "fetched_at", "duration_s"}

    def test_stdout_contract_unchanged(self):
        """Non-regression: stdout stays one JSONL line, same key set, same verdict,
        same non-timestamp values, exit 0 — regardless of the new stderr output."""
        rc, stdout, _ = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(target_is_nofollow=False),
        )
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert len(receipts) == 1
        r = receipts[0]
        assert set(r.keys()) == self._STDOUT_KEYS
        assert r["verdict"] == "dofollow"
        assert r["platform"] == "hashnode"
        assert r["target_url"] == "https://mysite.com"

    def test_dofollow_emits_checklist_on_stderr(self):
        rc, _, stderr = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(target_is_nofollow=False),
        )
        assert rc == 0
        assert "dofollow=True" in stderr
        assert "register(" in stderr
        assert "re-run" in stderr.lower()  # R5 caution

    def test_nofollow_emits_false_checklist_on_stderr(self):
        rc, _, stderr = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(target_anchor_found=True, target_is_nofollow=True),
        )
        assert rc == 0
        assert "dofollow=False" in stderr

    def test_ambiguous_no_checklist_on_stderr(self):
        rc, _, stderr = _run(
            ["hashnode", "--target-url", "https://mysite.com"],
            anchor_return=_anchor(page_readable=False),
        )
        assert rc == 0
        assert "register(" not in stderr  # no edit checklist for ambiguous

    def test_formatter_error_cannot_break_exit0_or_stdout(self):
        """A5/contract guard: a formatter exception must not suppress the stdout
        JSONL verdict nor the exit-0 advisory contract."""
        with patch.object(cs, "format_canary_hint", side_effect=RuntimeError("boom")):
            rc, stdout, _ = _run(["hashnode", "--target-url", "https://mysite.com"])
        assert rc == 0
        receipts = _parse_jsonl(stdout)
        assert receipts and receipts[0]["verdict"] in {"dofollow", "nofollow", "ambiguous"}
