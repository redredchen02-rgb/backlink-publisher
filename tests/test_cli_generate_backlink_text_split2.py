"""Split 2: LLM orchestration, corrective re-prompt, transport error, credential redaction,
edge-case validation.

Extracted from ``test_cli_generate_backlink_text.py`` (Plan 2026-06-23-005 U4).
"""

from __future__ import annotations
__tier__ = "unit"

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"


# ── _make_comment_text / _make_article_text (also needed here) ────────────────

def _make_comment_text(link_url: str, link_text: str) -> str:
    """Build ~45-word comment containing exactly one Markdown link (within 30-80 bound)."""
    filler = (
        "This article provides excellent insights into digital marketing and "
        "modern SEO practices. The content is well-researched and thoughtfully "
        "written, offering practical advice for professionals who want to improve "
        "their online presence and drive more organic traffic to their websites."
    )
    return f"{filler} [{link_text}]({link_url}) is an excellent resource."


def _make_article_text(link_url: str, link_text: str) -> str:
    """Build ~210-word article body containing exactly one Markdown link."""
    para = (
        "Digital marketing has evolved significantly over the past decade with "
        "search engine optimization becoming a critical component of any successful "
        "online strategy. Businesses must adapt to changing algorithms and user "
        "behavior patterns to maintain their competitive edge in the marketplace. "
    )
    return para * 4 + f"[{link_text}]({link_url}) is an excellent resource. " + para


# ══════════════════════════════════════════════════════════════════════════════
# Unit 5: Orchestration + dry-run + redaction + docs
# ══════════════════════════════════════════════════════════════════════════════


# ── _run_generate (Unit 3/5) ──────────────────────────────────────────────────


def test_run_generate_calls_generate_link_text(monkeypatch):
    """_run_generate calls generate_link_text and emits ok record with generated_text."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-api-key-value")

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "example anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    generated = _make_comment_text("https://example.com/", "example anchor")
    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch(
            "backlink_publisher.llm.client.safe_post_json",
            return_value=(200, {"choices": [{"message": {"content": generated}}]}),
        ):
            result = _run_generate(validated, args)

    assert len(result) == 1
    assert result[0]["status"] == "ok"
    assert result[0]["generated_text"] == generated
    assert "target_url" in result[0]
    assert "anchor_text" in result[0]


def test_run_generate_external_service_error_produces_rejected(monkeypatch):
    """ExternalServiceError per record → rejected row; batch continues."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher._util.errors import ExternalServiceError
    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-api-key-value")

    validated = [
        {"target_url": "https://example.com/", "anchor_text": "a", "mode": "comment"},
        {"target_url": "https://example.org/", "anchor_text": "b", "mode": "article"},
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    call_count = 0
    ok_content = _make_article_text("https://example.org/", "b")

    def fake_post(url, headers, payload, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ExternalServiceError("LLM request failed")
        return 200, {"choices": [{"message": {"content": ok_content}}]}

    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch(
            "backlink_publisher.llm.client.safe_post_json",
            side_effect=fake_post,
        ):
            result = _run_generate(validated, args)

    assert len(result) == 2
    statuses = [r["status"] for r in result]
    assert "rejected" in statuses
    assert "ok" in statuses


# ── _make_correction_hint ─────────────────────────────────────────────────────


def test_make_correction_hint_known_reasons_not_none():
    """Known failure reasons return a non-empty correction hint string."""
    from backlink_publisher.cli._candidates import _make_correction_hint

    for reason in ("missing_link", "missing_anchor", "length_out_of_bounds", "unsafe_chars"):
        hint = _make_correction_hint(reason)
        assert hint is not None and len(hint) > 10, (
            f"_make_correction_hint({reason!r}) returned empty/None"
        )


def test_make_correction_hint_refusal_returns_none():
    """llm_refusal returns None — no re-prompt is attempted for refusals."""
    from backlink_publisher.cli._candidates import _make_correction_hint

    assert _make_correction_hint("llm_refusal") is None


def test_make_correction_hint_unknown_reason_returns_none():
    """Unknown reason returns None (no re-prompt for novel failure categories)."""
    from backlink_publisher.cli._candidates import _make_correction_hint

    assert _make_correction_hint("bogus_reason") is None


# ── Corrective re-prompt: success on second attempt ───────────────────────────


def test_corrective_reprompt_succeeds_on_second_attempt(monkeypatch):
    """First LLM response fails validation; corrective re-prompt succeeds."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key-value")

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "example anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    call_count = 0
    ok_text = _make_comment_text("https://example.com/", "example anchor")

    def fake_post(url, headers, payload, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 200, {"choices": [{"message": {"content": "bare text without link"}}]}
        return 200, {"choices": [{"message": {"content": ok_text}}]}

    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch("backlink_publisher.llm.client.safe_post_json", side_effect=fake_post):
            result = _run_generate(validated, args)

    assert call_count == 2, "Expected exactly two LLM calls (initial + re-prompt)"
    assert result[0]["status"] == "ok"
    assert result[0]["generated_text"] == ok_text


def test_corrective_reprompt_hint_appended_to_payload(monkeypatch):
    """Corrective re-prompt payload contains the correction_hint text."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key-value")

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "example anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    call_count = 0
    payloads: list[dict] = []
    ok_text = _make_comment_text("https://example.com/", "example anchor")

    def fake_post(url, headers, payload, timeout=10):
        nonlocal call_count
        call_count += 1
        payloads.append(payload)
        if call_count == 1:
            return 200, {"choices": [{"message": {"content": "bare text without link"}}]}
        return 200, {"choices": [{"message": {"content": ok_text}}]}

    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch("backlink_publisher.llm.client.safe_post_json", side_effect=fake_post):
            _run_generate(validated, args)

    assert len(payloads) == 2
    corrective_user_msg = payloads[1]["messages"][1]["content"]
    assert "correction" in corrective_user_msg.lower() or "link" in corrective_user_msg.lower()


# ── Corrective re-prompt: both attempts fail → rejected ───────────────────────


def test_corrective_reprompt_both_fail_produces_rejected(monkeypatch):
    """Both LLM attempts return invalid text → record is rejected."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key-value")

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "example anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    def fake_post(url, headers, payload, timeout=10):
        return 200, {"choices": [{"message": {"content": "bare text without link"}}]}

    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch("backlink_publisher.llm.client.safe_post_json", side_effect=fake_post):
            result = _run_generate(validated, args)

    assert result[0]["status"] == "rejected"
    assert result[0]["rejection_reason"] == "missing_link"


# ── Corrective re-prompt skipped for llm_refusal ─────────────────────────────


def test_corrective_reprompt_skipped_for_refusal(monkeypatch):
    """llm_refusal → no re-prompt attempted (refusals are not retried)."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key-value")

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "example anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    call_count = 0

    def fake_post(url, headers, payload, timeout=10):
        nonlocal call_count
        call_count += 1
        return 200, {"choices": [{"message": {"content": "I cannot help with this request."}}]}

    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch("backlink_publisher.llm.client.safe_post_json", side_effect=fake_post):
            result = _run_generate(validated, args)

    assert call_count == 1, "Refusals must not trigger a corrective re-prompt"
    assert result[0]["status"] == "rejected"
    assert result[0]["rejection_reason"] == "llm_refusal"


# ── Transport error → rejected transport_error, no bearer in stderr ───────────


def test_transport_error_produces_rejected_and_no_bearer_in_stderr(
    monkeypatch, capsys
):
    """ExternalServiceError → rejected transport_error; bearer token not in stderr."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher._util.errors import ExternalServiceError
    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    sentinel = "test-bearer-sentinel-do-not-log"
    monkeypatch.setenv("BACKLINK_LLM_API_KEY", sentinel)

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=0,
    )

    def fake_post(url, headers, payload, timeout=10):
        return 500, {"error": "internal error"}

    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch("backlink_publisher.llm.client.safe_post_json", side_effect=fake_post):
            result = _run_generate(validated, args)

    captured = capsys.readouterr()
    assert result[0]["status"] == "rejected"
    assert result[0]["rejection_reason"] == "transport_error"
    assert sentinel not in captured.err, (
        "Bearer sentinel appeared in stderr — CLI-level redaction failed"
    )


# ── Output field allowlist: no endpoint/key/env-var-name in ok records ────────


def test_output_records_contain_no_credentials(monkeypatch):
    """ok records must not contain endpoint, key, or env-var-name (R16)."""
    import argparse
    import unittest.mock as mock

    from backlink_publisher.cli.plan.generate_backlink_text import _run_generate

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "super-secret-key-value")

    validated = [
        {
            "target_url": "https://example.com/",
            "anchor_text": "example anchor",
            "mode": "comment",
        }
    ]
    args = argparse.Namespace(
        endpoint="https://api.openai.com/v1",
        api_key_env="BACKLINK_LLM_API_KEY",
        model="gpt-4",
        temperature=0.4,
        timeout=60,
        retries=1,
    )

    ok_text = _make_comment_text("https://example.com/", "example anchor")
    with mock.patch(
        "backlink_publisher.llm.http_guard.guard_llm_endpoint",
        return_value=(None, None),
    ):
        with mock.patch(
            "backlink_publisher.llm.client.safe_post_json",
            return_value=(200, {"choices": [{"message": {"content": ok_text}}]}),
        ):
            result = _run_generate(validated, args)

    assert result[0]["status"] == "ok"
    rec_text = json.dumps(result[0])
    assert "super-secret-key-value" not in rec_text
    assert "https://api.openai.com/v1" not in rec_text
    assert "BACKLINK_LLM_API_KEY" not in rec_text


# ── All records rejected → exit 0 ────────────────────────────────────────────


def test_all_records_rejected_exit_0(monkeypatch, capsys):
    """All records rejected (invalid_record) → still exit 0 (R14b)."""
    import io

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key")

    from backlink_publisher.cli.generate_backlink_text import main

    stdin_text = json.dumps([
        {"mode": "comment"},                      # missing target_url, anchor_text
        {"target_url": "https://x.com/", "mode": "comment"},  # missing anchor_text
    ])

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        exit_code = None
        try:
            main([])
        except SystemExit as exc:
            exit_code = exc.code
    finally:
        sys.stdin = old_stdin

    if exit_code is None:
        exit_code = 0
    assert exit_code == 0

    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.strip().splitlines()]
    assert all(r["status"] == "rejected" for r in records)


# ── Happy path (mock): mixed ok/rejected → exit 0 ────────────────────────────


def test_main_happy_path_mixed_output(monkeypatch, capsys):
    """main(): valid + invalid records produce mixed ok/rejected output, exit 0."""
    import io
    import unittest.mock as mock

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key-value")

    from backlink_publisher.cli.generate_backlink_text import main

    ok_text = _make_comment_text("https://example.com/", "good anchor")
    stdin_text = "\n".join([
        json.dumps({
            "target_url": "https://example.com/",
            "anchor_text": "good anchor",
            "mode": "comment",
        }),
        json.dumps({
            "target_url": "not-https://bad/",
            "anchor_text": "anchor",
            "mode": "comment",
        }),
    ])

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        with mock.patch(
            "backlink_publisher.llm.http_guard.guard_llm_endpoint",
            return_value=(None, None),
        ):
            with mock.patch(
                "backlink_publisher.llm.client.safe_post_json",
                return_value=(200, {"choices": [{"message": {"content": ok_text}}]}),
            ):
                try:
                    main(["--endpoint", "https://api.openai.com/v1", "--model", "gpt-4"])
                except SystemExit as exc:
                    assert exc.code == 0
    finally:
        sys.stdin = old_stdin

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().splitlines() if l.strip()]
    records = [json.loads(line) for line in lines]
    statuses = {r["status"] for r in records}
    assert "ok" in statuses
    assert "rejected" in statuses


# ── Integration: no config write during full run ───────────────────────────────


def test_no_config_write_during_generate(monkeypatch, tmp_path):
    """generate-backlink-text must not call save_config (R16 / stateless)."""
    import io
    import unittest.mock as mock

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key-value")
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))

    from backlink_publisher.cli.generate_backlink_text import main

    ok_text = _make_comment_text("https://example.com/", "anchor")
    stdin_text = json.dumps({
        "target_url": "https://example.com/",
        "anchor_text": "anchor",
        "mode": "comment",
    })

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)

    save_config_calls: list = []
    with mock.patch(
        "backlink_publisher.config.save_config",
        side_effect=lambda *a, **kw: save_config_calls.append((a, kw)),
    ):
        with mock.patch(
            "backlink_publisher.llm.http_guard.guard_llm_endpoint",
            return_value=(None, None),
        ):
            with mock.patch(
                "backlink_publisher.llm.client.safe_post_json",
                return_value=(200, {"choices": [{"message": {"content": ok_text}}]}),
            ):
                try:
                    main(["--endpoint", "https://api.openai.com/v1", "--model", "gpt-4"])
                except SystemExit:
                    pass
                finally:
                    sys.stdin = old_stdin

    assert save_config_calls == [], (
        "generate-backlink-text must not call save_config — it is a read-only tool"
    )


# ── Security: endpoint userinfo → secret not in any stderr line ───────────────


def test_userinfo_endpoint_secret_not_in_stderr(monkeypatch, capsys):
    """--endpoint with user:secret@host → DependencyError; secret not in stderr."""
    import io

    monkeypatch.setenv("BACKLINK_LLM_API_KEY", "test-key")

    from backlink_publisher.cli.generate_backlink_text import main

    secret = "mysecretpassword"
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps({
        "target_url": "https://example.com/",
        "anchor_text": "anchor",
        "mode": "comment",
    }))
    try:
        with pytest.raises(SystemExit) as exc_info:
            main([
                "--endpoint", f"https://user:{secret}@api.openai.com/v1",
                "--model", "gpt-4",
            ])
    finally:
        sys.stdin = old_stdin

    assert exc_info.value.code == 3
    captured = capsys.readouterr()
    assert secret not in captured.err, (
        "userinfo secret leaked into stderr — must be redacted/excluded"
    )


# ── Additional edge cases ─────────────────────────────────────────────────────


def test_validate_generated_text_length_out_of_bounds_article_too_long():
    """Article body > 400 words → length_out_of_bounds (TST-001)."""
    from backlink_publisher.cli._candidates import _validate_generated_text

    filler_word = "word"
    filler = (" ".join([filler_word] * 210) + " ")
    link = "[example anchor](https://example.com/)"
    text = filler + link + " " + filler
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="article",
    )
    assert result == {"ok": False, "reason": "length_out_of_bounds"}


def test_validate_generated_text_length_out_of_bounds_comment_too_long():
    """Comment body > 80 words → length_out_of_bounds (TST-002)."""
    from backlink_publisher.cli._candidates import _validate_generated_text

    filler_word = "word"
    filler = " ".join([filler_word] * 44)
    link = "[example anchor](https://example.com/)"
    text = filler + " " + link + " " + filler
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
    )
    assert result == {"ok": False, "reason": "length_out_of_bounds"}


def test_cli_dry_run_no_http_call(capsys, monkeypatch):
    """--dry-run: HTTP must never be called regardless of valid input (TST-003)."""
    import io
    import unittest.mock as mock

    from backlink_publisher.cli.generate_backlink_text import main

    record = json.dumps({
        "target_url": "https://example.com/",
        "anchor_text": "example anchor",
        "mode": "comment",
    })

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(record)
    try:
        with mock.patch("backlink_publisher.llm.client.safe_post_json") as mock_post:
            try:
                main(["--dry-run"])
            except SystemExit as exc:
                assert exc.code in (None, 0)
            assert mock_post.call_count == 0, (
                f"HTTP was called {mock_post.call_count} time(s) during dry-run — must be zero"
            )
    finally:
        sys.stdin = old_stdin


def test_validate_generated_text_multiple_extra_links_stripped():
    """Multiple extra links to different domains → all stripped; stripped_extra_links counts them (TST-004)."""
    from backlink_publisher.cli._candidates import _validate_generated_text

    base_text = _make_comment_text("https://example.com/", "example anchor")
    extra1 = "[spam1](https://spam1.com/a)"
    extra2 = "[spam2](https://spam2.net/b)"
    text = extra1 + " " + base_text + " " + extra2
    result = _validate_generated_text(
        text,
        target_url="https://example.com/",
        anchor_text="example anchor",
        mode="comment",
    )
    assert result["ok"] is True
    assert result["stripped_extra_links"] == 2
    assert "spam1.com" not in result["text"]
    assert "spam2.net" not in result["text"]
    assert "example.com" in result["text"]


def test_cli_help_banner_subprocess():
    """python -m backlink_publisher.cli.generate_backlink_text --help emits usage."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_SRC_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    result = subprocess.run(
        [sys.executable, "-m", "backlink_publisher.cli.plan.generate_backlink_text", "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        timeout=15,
    )
    combined = result.stdout + result.stderr
    assert combined.strip(), "--help produced no output"
