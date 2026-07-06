"""Tests for webui_app.services.error_report_sanitizer — Plan 2026-07-01-002 Unit 1.

Covers the three composed sanitization layers (free-text scrub_text + URL
query-token filter, structured key-name redaction, and the new exact
known-credential-value match), the per-field length cap, and the
never-raise/never-silently-drop degrade contract.

Every "should NOT contain" assertion is paired with a positive counterpart
per docs/audits/2026-05-27-recurring-trap-eradication-audit.md — a
standalone negative assertion can't distinguish "correctly redacted" from
"field silently dropped/blanked".
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

from webui_app.services import error_report_sanitizer as sanitizer


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def known_creds(tmp_path, monkeypatch):
    """Isolate BACKLINK_PUBLISHER_CONFIG_DIR to a tmp dir and write a small
    set of real per-platform credential files through the actual production
    save_* functions (not hand-rolled JSON) — so `_known_secret_values()`
    reads through the same write path real operators go through, and the
    Hatena/Tumblr per-platform field curation (Test scenario 7) is exercised
    against genuine file content."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher.config import load_config
    from webui_app.services import credential_service

    cfg = load_config()
    # Single-secret-field channel (_TOKEN_DISPATCH) — short, non-JWT,
    # non-hex-64 shape, deliberately below scrub_text's 32-char entropy floor.
    credential_service.save_token("hackmd", cfg, "hkmdShortTok9")
    # Mixed channel (_TOKEN_FIELDS_DISPATCH): hatena_id/blog_id are NOT
    # secret, only api_key is.
    credential_service.save_token_fields(
        "hatena",
        cfg,
        {
            "hatena_id": "myHatenaId",
            "blog_id": "myblog.hatenablog.com",
            "api_key": "hatenaKey789xyz",
        },
    )
    # Mixed channel: blog_identifier is NOT secret, the other four ARE.
    credential_service.save_token_fields(
        "tumblr",
        cfg,
        {
            "consumer_key": "tumblrConsumerKey1",
            "consumer_secret": "tumblrConsumerSecret1",
            "oauth_token": "tumblrOauthToken1",
            "oauth_token_secret": "tumblrOauthTokenSecret1",
            "blog_identifier": "my-blog-id.tumblr.com",
        },
    )
    return cfg


# ── 1. Happy path: bearer token redacted; non-secret field unchanged ───────


def test_bearer_token_redacted_paired_with_unchanged_name_field(known_creds):
    report = {
        "name": "TypeError",
        "message": "request failed: Authorization: Bearer abcDEF123456ghiJKL789",
    }
    result = sanitizer.sanitize_error_report(report)
    assert "Bearer abcDEF123456ghiJKL789" not in result["message"]
    assert result["name"] == "TypeError"  # paired positive: non-secret field untouched


# ── 2. Happy path: password key redacted; sibling key unchanged ────────────


def test_password_key_redacted_paired_with_sibling_key_unchanged(known_creds):
    report = {"context": {"password": "hunter2", "platform": "blogger"}}
    result = sanitizer.sanitize_error_report(report)
    assert result["context"]["password"] == "***"
    assert result["context"]["platform"] == "blogger"  # paired positive assertion


# ── 3. Happy path: exact known-secret redacted via Layer 3, even though ────
#      scrub_text alone would not catch it; shape-alike-but-unconfigured
#      string is NOT redacted (proves exact-value match, not shape guessing).


def test_known_short_credential_redacted_via_exact_value_match(known_creds):
    # Below the 32-char entropy floor and not shaped like any regex pattern
    # in scrub_text (no "Bearer "/"eyJ"/"AIza" prefix, not 64-hex) — confirms
    # scrub_text alone would not catch this.
    from backlink_publisher.events.scrubber import scrub_text

    baseline, _hits = scrub_text("my hatena token hatenaKey789xyz gives 401")
    assert "hatenaKey789xyz" in baseline  # scrub_text alone does NOT catch it

    report = {"user_description": "my hatena token hatenaKey789xyz gives 401"}
    result = sanitizer.sanitize_error_report(report)
    assert "hatenaKey789xyz" not in result["user_description"]
    assert "gives 401" in result["user_description"]  # paired: surrounding text kept


def test_shape_alike_non_configured_string_not_redacted(known_creds):
    report = {"user_description": "my hatena token hatenaKeyNOTCONFIGURED gives 401"}
    result = sanitizer.sanitize_error_report(report)
    # Not an actually-configured credential -> untouched (paired with the
    # previous test's "the real one IS redacted").
    assert "hatenaKeyNOTCONFIGURED" in result["user_description"]


# ── 4. Edge case: URL query-string token filtering ──────────────────────────


def test_url_session_param_masked_page_param_kept(known_creds):
    report = {"url": "https://app.example.com/publish?session=abc123&page=2"}
    result = sanitizer.sanitize_error_report(report)
    assert "abc123" not in result["url"]
    assert "page=2" in result["url"]  # paired positive: non-secret param survives


# ── 5. Edge case: length cap with a visible (not silent) truncation marker ─


def test_long_field_truncated_with_visible_marker(known_creds):
    long_text = "a" * 5000
    report = {"message": long_text}
    result = sanitizer.sanitize_error_report(report)
    assert "<TRUNCATED:" in result["message"]
    assert result["message"].startswith("a" * 100)  # paired: content preserved up to the cap
    assert len(result["message"]) < len(long_text)


# ── 6. Error path: unexpected field shape degrades, never raises/drops ─────


class _Weird:
    """Stand-in for a value shape sanitize_error_report cannot expect
    (custom object with no dict/list/str/scalar structure)."""

    def __str__(self) -> str:
        return "weird-repr"


def test_unexpected_field_type_degrades_without_raising(known_creds):
    report = {"name": "TypeError", "weird_field": _Weird()}
    result = sanitizer.sanitize_error_report(report)  # must not raise
    assert result["sanitize_degraded"] is True
    assert result["name"] == "TypeError"  # paired: sibling field unaffected
    assert "weird_field" in result  # degraded, not silently dropped


def test_non_dict_report_degrades_without_raising():
    result = sanitizer.sanitize_error_report(["not", "a", "dict"])  # must not raise
    assert result["sanitize_degraded"] is True
    assert "raw" in result  # payload preserved (best-effort), not discarded


def test_happy_path_report_marks_not_degraded(known_creds):
    report = {"name": "TypeError", "message": "ok"}
    result = sanitizer.sanitize_error_report(report)
    assert result["sanitize_degraded"] is False
    assert result["name"] == "TypeError"  # paired: field present and correct


# ── 7. Per-platform curation: Hatena + Tumblr ───────────────────────────────


def test_hatena_identifiers_not_redacted_but_api_key_is(known_creds):
    report = {
        "user_description": (
            "hatena_id=myHatenaId blog_id=myblog.hatenablog.com "
            "api_key=hatenaKey789xyz failing"
        )
    }
    result = sanitizer.sanitize_error_report(report)
    text = result["user_description"]
    assert "hatenaKey789xyz" not in text
    assert "myHatenaId" in text  # paired: non-secret identifier kept
    assert "myblog.hatenablog.com" in text  # paired: non-secret identifier kept


def test_tumblr_blog_identifier_not_redacted_other_four_are(known_creds):
    report = {
        "user_description": (
            "consumer_key=tumblrConsumerKey1 consumer_secret=tumblrConsumerSecret1 "
            "oauth_token=tumblrOauthToken1 oauth_token_secret=tumblrOauthTokenSecret1 "
            "blog_identifier=my-blog-id.tumblr.com"
        )
    }
    result = sanitizer.sanitize_error_report(report)
    text = result["user_description"]
    assert "tumblrConsumerKey1" not in text
    assert "tumblrConsumerSecret1" not in text
    assert "tumblrOauthToken1" not in text
    assert "tumblrOauthTokenSecret1" not in text
    assert "my-blog-id.tumblr.com" in text  # paired: non-secret identifier survives


def test_known_secret_values_excludes_non_secret_identifier_fields(known_creds):
    """Direct unit check on the curation helper itself: hatena_id/blog_id/
    blog_identifier must never appear in the known-secrets set, proving the
    curation reads specific fields rather than the whole dispatch tuple."""
    values = sanitizer._known_secret_values()
    assert "hatenaKey789xyz" in values  # the actual secret IS present
    assert "myHatenaId" not in values
    assert "myblog.hatenablog.com" not in values
    assert "my-blog-id.tumblr.com" not in values


# ── The two credential sources the plan flags as "otherwise missed" ────────


def test_frw_token_redacted_via_layer3(tmp_path, monkeypatch):
    """`_util/secrets.py`'s load_frw_token() (FRW image-gen API key) is one
    of the two sources the security review found missing from a naive
    credential_service-only read — must be covered too."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    from backlink_publisher._util.secrets import write_frw_token

    write_frw_token("frwShortKey42")

    report = {"user_description": "banner gen failed with key frwShortKey42 attached"}
    result = sanitizer.sanitize_error_report(report)
    assert "frwShortKey42" not in result["user_description"]
    assert "banner gen failed" in result["user_description"]  # paired positive assertion


def test_llm_settings_api_keys_redacted_via_layer3(tmp_path, monkeypatch):
    """settings_service.py's llm-settings.json (api_key / image_gen_api_key)
    is the second source the security review found missing."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    import json

    from webui_app.services import settings_service

    settings_service.llm_settings_file().write_text(
        json.dumps({"api_key": "llmSecretAbc1", "image_gen_api_key": "imgSecretXyz2"}),
        encoding="utf-8",
    )

    report = {
        "user_description": (
            "llm test failed, key llmSecretAbc1 and img key imgSecretXyz2 both fail"
        )
    }
    result = sanitizer.sanitize_error_report(report)
    assert "llmSecretAbc1" not in result["user_description"]
    assert "imgSecretXyz2" not in result["user_description"]
    assert "llm test failed" in result["user_description"]  # paired positive assertion


# ── Additional coverage: no credentials configured (isolated empty dir) ────


def test_sanitizer_works_with_no_known_credentials_configured():
    """No known_creds fixture -- proves `_known_secret_values()` tolerates a
    completely unconfigured config dir without raising, and that scrub_text
    + key-based redaction alone still function on their own."""
    report = {
        "name": "TypeError",
        "message": "Bearer sometoken123456789012345678901234567890",
        "context": {"api_key": "sk-something", "platform": "blogger"},
    }
    result = sanitizer.sanitize_error_report(report)
    assert result["sanitize_degraded"] is False
    assert result["context"]["api_key"] == "***"
    assert result["context"]["platform"] == "blogger"  # paired positive assertion


# ── Integration: all three layers composed in one realistic report ─────────


def test_all_three_layers_compose_in_a_single_realistic_report(known_creds):
    """One full report exercising Layer 1 (scrub_text), the URL query
    filter, Layer 2 (structured key redaction), Layer 3 (exact known-secret
    match), and the length cap all at once -- proves composition, not just
    each layer in isolation."""
    report = {
        "name": "NetworkError",
        "message": "call failed: Authorization: Bearer sometoken123456789012345678901234567890",
        "stack": "x" * 4500,
        "url": "https://app.example.com/api?session=zzz999&page=3",
        "user_description": "tried again with hatenaKey789xyz but same error",
        "context": {"password": "hunter2", "channel": "hatena"},
    }
    result = sanitizer.sanitize_error_report(report)

    assert result["sanitize_degraded"] is False
    assert result["name"] == "NetworkError"  # untouched non-secret field

    assert "Bearer sometoken123456789012345678901234567890" not in result["message"]

    assert "<TRUNCATED:" in result["stack"]
    assert result["stack"].startswith("x" * 100)

    assert "zzz999" not in result["url"]
    assert "page=3" in result["url"]

    assert "hatenaKey789xyz" not in result["user_description"]
    assert "but same error" in result["user_description"]

    assert result["context"]["password"] == "***"
    assert result["context"]["channel"] == "hatena"  # non-secret, unchanged
