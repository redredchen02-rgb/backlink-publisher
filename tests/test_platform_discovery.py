"""Tests for platform_discovery.py (Plan 2026-06-02-003 Unit 3).

Imports platform_discovery via sys.path (scripts/ is not a package).
All HTTP calls and probe_url are mocked; network is socket-blocked by conftest.

Track B fail-closed: SSRF guard must be importable. In tests, _check_url_for_ssrf
is patched to return None (safe) so guard is always "active" but non-blocking.
"""

from __future__ import annotations

import json
import os
import sys
import io
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# Add scripts/ to path for direct import.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import platform_discovery as pd


# ── helpers ──────────────────────────────────────────────────────────────────


def _mock_probe(verdict: str) -> dict:
    return {
        "verdict": verdict,
        "signals": [],
        "next_checks": [],
        "ssrf_guard_active": True,
    }


def _make_html(anchors: list[tuple[str, str | None]]) -> str:
    """Build minimal HTML with cross-domain <a> tags.

    anchors = [(href, rel), ...]. rel=None → no rel attribute.
    """
    tags = []
    for href, rel in anchors:
        rel_attr = f' rel="{rel}"' if rel else ""
        tags.append(f'<a href="{href}"{rel_attr}>link</a>')
    return "<html><body>" + "".join(tags) + "</body></html>"


def _make_response(status: int = 200, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = lambda: (None if status < 400 else (_ for _ in ()).throw(
        __import__("requests").HTTPError(f"HTTP {status}")
    ))
    return resp


def _run(
    argv: list[str],
    *,
    probe_return: dict | None = None,
    score_response_text: str = "",
    ssrf_return: Optional[str] = None,
    is_registered_return: bool = False,
) -> tuple[str, str]:
    """Run pd.main(argv) with all IO mocked. Returns (stdout, stderr)."""
    probe_kw = {"return_value": probe_return or _mock_probe("needs-canary")}
    score_resp = _make_response(200, score_response_text)

    with patch.object(pd, "probe_url", **probe_kw), \
         patch.object(pd, "_check_url_for_ssrf", return_value=ssrf_return), \
         patch.object(pd, "_is_registered", return_value=is_registered_return), \
         patch.object(pd, "_sleep", lambda *a: None), \
         patch("requests.get", return_value=score_resp):
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            pd.main(argv)
        except SystemExit:
            pass
        finally:
            stdout = sys.stdout.getvalue()
            stderr = sys.stderr.getvalue()
            sys.stdout, sys.stderr = old_stdout, old_stderr
    return stdout, stderr


def _parse_jsonl(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


# ── candidate-urls path ───────────────────────────────────────────────────────


class TestCandidateUrlsPath:
    """--candidate-urls reads file and enters probe directly (skipping SERP)."""

    def test_dofollow_go(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://newplatform.com/post\n")
        html = _make_html([
            (f"https://ext{i}.com/", None) for i in range(8)
        ])
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            probe_return=_mock_probe("needs-canary"),
            score_response_text=html,
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 1
        assert records[0]["verdict"] == "go"
        assert records[0]["dofollow_rate"] >= 0.8

    def test_no_go(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://nofollow-site.com/post\n")
        html = _make_html([
            (f"https://ext{i}.com/", "nofollow") for i in range(12)
        ])
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            score_response_text=html,
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 1
        assert records[0]["verdict"] == "no-go"

    def test_insufficient_sample(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://sparse.com/post\n")
        html = _make_html([
            ("https://ext1.com/", None),
            ("https://ext2.com/", None),
            ("https://ext3.com/", None),
        ])  # 3 < default min_sample_size=5
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            score_response_text=html,
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 1
        assert records[0]["verdict"] == "needs-manual"

    def test_js_shell_zero_anchors(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://js-site.com/post\n")
        # No anchors at all → 0 cross-domain
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            score_response_text="<html><body>no links here</body></html>",
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 1
        assert records[0]["verdict"] == "needs-manual"

    def test_needs_browser_tier(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://js-gated.com\n")
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            probe_return=_mock_probe("needs-browser-tier"),
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 1
        assert records[0]["verdict"] == "needs-manual"
        assert "needs-browser-tier" in (records[0].get("reason") or "")

    def test_no_go_unreachable_skipped(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://dead-site.com\n")
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            probe_return=_mock_probe("no-go-unreachable"),
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 0

    def test_already_registered_skipped(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://hashnode.com/post\n")
        stdout, _ = _run(
            ["--candidate-urls", str(url_file)],
            is_registered_return=True,
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 0

    def test_ssrf_blocked_skipped(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("http://169.254.169.254/\n")
        stdout, stderr = _run(
            ["--candidate-urls", str(url_file)],
            ssrf_return="cloud_metadata",
        )
        records = _parse_jsonl(stdout)
        assert len(records) == 0
        assert "ssrf" in stderr.lower() or "skip" in stderr.lower()


# ── JSONL output shape ────────────────────────────────────────────────────────


class TestJsonlShape:
    """Verify required fields in output records."""

    REQUIRED = {"url", "platform_type", "bot_accessible", "dofollow_rate",
                "sample_size", "verdict", "probe_at"}

    def test_all_fields_present(self, tmp_path):
        url_file = tmp_path / "urls.txt"
        url_file.write_text("https://example-platform.com\n")
        html = _make_html([(f"https://ext{i}.com/", None) for i in range(8)])
        stdout, _ = _run(["--candidate-urls", str(url_file)], score_response_text=html)
        records = _parse_jsonl(stdout)
        assert len(records) == 1
        missing = self.REQUIRED - set(records[0].keys())
        assert not missing, f"Missing fields: {missing}"


# ── Rate limiting ─────────────────────────────────────────────────────────────


class TestRateLimiting:
    """DuckDuckGo queries must have ≥2s sleep between them."""

    def test_sleep_called_between_queries(self, tmp_path):
        """Two queries → _sleep called at least once with ≥2.0."""
        queries_file = tmp_path / "queries.toml"
        queries_file.write_text(
            '[[queries]]\nquery = "free blog platform dofollow"\n\n'
            '[[queries]]\nquery = "guest post site dofollow"\n'
        )
        sleep_calls = []

        # Fake SERP response
        serp_html = (
            '<a class="result__url" href="https://fakeplatform.com/post">fakeplatform.com</a>'
        )
        serp_resp = _make_response(200, serp_html)
        score_resp = _make_response(200, "")

        with patch.object(pd, "_check_url_for_ssrf", return_value=None), \
             patch.object(pd, "_is_registered", return_value=False), \
             patch.object(pd, "probe_url", return_value=_mock_probe("no-go-unreachable")), \
             patch.object(pd, "_sleep", side_effect=sleep_calls.append), \
             patch("requests.get", return_value=serp_resp):
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            try:
                pd.main(["--queries", str(queries_file)])
            except SystemExit:
                pass
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr

        # At least one sleep call for the inter-query rate limit
        assert any(s >= pd._SERP_RATE_LIMIT_S for s in sleep_calls), (
            f"Expected sleep ≥{pd._SERP_RATE_LIMIT_S}s between queries, calls={sleep_calls}"
        )


# ── CI clean import ───────────────────────────────────────────────────────────


class TestCiCleanImport:
    """Module can be imported without triggering network calls."""

    def test_import_ok(self):
        import importlib
        importlib.reload(pd)
        assert hasattr(pd, "main")
        assert hasattr(pd, "_probe_candidate")
        assert hasattr(pd, "_score_candidate")
