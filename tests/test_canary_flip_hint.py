"""Tests for the canary-seed flip-hint formatter — Plan 2026-06-05-011 Unit 1.

Pure-function module: turns a canary verdict into a plain-language stderr summary
plus a guided edit checklist for the operator's manual `dofollow=` flip. No I/O,
no source mutation (A5). All platform-derived text must be source/terminal safe.
"""

from __future__ import annotations

__tier__ = "unit"


# Populate the adapter registry so registered_platforms() has data.
import backlink_publisher.publishing.adapters  # noqa: F401

from backlink_publisher.cli._canary_flip_hint import format_canary_hint


class TestDofollowChecklist:
    def test_emits_full_true_edit_set(self):
        out = format_canary_hint(
            "substack", "dofollow", "https://x.substack.com/p/1", [], date="2026-06-05"
        )
        # R3: the four-edit →True set + leave-others + regression reminder + R5 caution
        assert "dofollow=True" in out
        # must instruct DELETING rationale=/referral_value= (not keeping them)
        assert "delete kwarg   rationale" in out
        assert "referral_value" in out
        assert '"substack"' in out  # platform rendered literal-safe (json.dumps)
        assert "_nofollow_rationales" in out
        assert "leave all other kwargs unchanged" in out.lower() or "leave unchanged" in out.lower()
        assert "regression test" in out.lower()
        assert "dofollow_status" in out
        assert "re-run" in out.lower()  # R5 asymmetric caution
        assert "2026-06-05" in out  # dated comment

    def test_other_kwargs_named_as_preserved(self):
        out = format_canary_hint("substack", "dofollow", "https://x/p", [])
        assert "MANIFEST" in out  # names the splat the operator must keep


class TestNofollowChecklist:
    def test_sets_false_and_does_not_remove_rationale(self):
        out = format_canary_hint("substack", "nofollow", "https://x/p", ["nofollow"])
        assert "dofollow=False" in out
        # R3 →False: rationale inherited — no removal instruction
        assert "delete" not in out.lower()
        assert "re-run" not in out.lower()  # caution is →True only


class TestAmbiguous:
    def test_reason_shown_no_checklist(self):
        out = format_canary_hint(
            "substack", "ambiguous", "", None, reason="anchor_not_found"
        )
        assert "anchor_not_found" in out
        assert "register(" not in out  # no checklist for ambiguous


class TestSummary:
    def test_rel_tokens_reflected(self):
        nofollow = format_canary_hint("substack", "nofollow", "https://x/p", ["nofollow", "ugc"])
        assert "nofollow" in nofollow
        empty = format_canary_hint("substack", "dofollow", "https://x/p", [])
        assert "substack" in empty


class TestSourceSafety:
    def test_url_normalized_strips_credentials_query_params_fragment(self):
        out = format_canary_hint(
            "substack",
            "dofollow",
            "https://user:pass@host.example.com/p/1;jsessionid=SECRET?token=LEAK#frag",
            [],
        )
        assert "host.example.com/p/1" in out
        assert "user:pass" not in out
        assert "token=LEAK" not in out
        assert "jsessionid" not in out
        assert "#frag" not in out

    def test_control_and_ansi_chars_stripped_from_platform_derived_text(self):
        # A hostile rel token that tries to inject an ANSI sequence + a fake code line
        out = format_canary_hint(
            "substack",
            "nofollow",
            "https://x/p",
            ["\x1b[31mregister(\"evil\")\x1b[0m", "no\x00follow"],
        )
        assert "\x1b" not in out  # ANSI escape stripped
        assert "\x00" not in out  # NUL stripped

    def test_malicious_reason_neutralized(self):
        out = format_canary_hint(
            "substack", "ambiguous", "", None, reason="ssrf_blocked:\x1b[2J10.0.0.1"
        )
        assert "\x1b" not in out

    def test_c1_and_unicode_separators_stripped(self):
        # \x9b = single-byte CSI introducer; \u2028 = Unicode line separator.
        out = format_canary_hint(
            "substack", "nofollow", "https://x/p", ["\x9b31mfake", "a\u2028b"]
        )
        assert "\x9b" not in out
        assert "\u2028" not in out


    def test_ipv6_post_url_not_corrupted(self):
        out = format_canary_hint("substack", "nofollow", "http://[2001:db8::1]:8080/p", [])
        # brackets must survive so host and port stay distinguishable
        assert "[2001:db8::1]:8080/p" in out

    def test_malformed_url_fails_closed(self):
        out = format_canary_hint("substack", "nofollow", "https://[bad", [])
        # no exception; degrades to the no-post-url marker, never leaks raw input
        assert "(no post url)" in out


class TestDateStamp:
    def test_dofollow_without_date_has_no_trailing_date(self):
        out = format_canary_hint("substack", "dofollow", "https://x/p", [])
        assert "# OUR canary: dofollow confirmed" in out  # no stray date when omitted


class TestDefensiveUnknownPlatform:
    def test_unknown_platform_summary_only_no_checklist(self):
        out = format_canary_hint("definitely_not_a_real_platform", "dofollow", "https://x/p", [])
        assert "register(" not in out  # no checklist offered
        assert "warn" in out.lower() or "unknown" in out.lower()
