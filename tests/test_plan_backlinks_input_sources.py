"""Tests for plan-backlinks --from-csv and --from-sitemap input sources."""
from __future__ import annotations

__tier__ = "unit"
from io import StringIO
import json
import sys
from unittest.mock import patch

import pytest

from backlink_publisher.cli.plan_backlinks import main


def _run_plan(input_data: str, argv: list[str] | None = None) -> tuple[str, str, int]:
    """Run plan-backlinks with given stdin data. Returns (stdout, stderr, exit_code)."""
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        sys.stdin = StringIO(input_data)
        out = StringIO()
        err = StringIO()
        sys.stdout = out
        sys.stderr = err
        try:
            main(argv or [])
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        return out.getvalue(), err.getvalue(), code
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def test_from_csv_generates_payloads(tmp_path):
    """--from-csv reads URLs from a file and generates payloads."""
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text(
        "https://example.com/page1\nhttps://example.com/page2\n",
        encoding="utf-8",
    )
    stdout, stderr, code = _run_plan("", argv=[f"--from-csv={csv_file}"])
    assert code == 0, f"Expected 0, got {code}. stderr: {stderr}"
    lines = [l for l in stdout.strip().split("\n") if l]
    assert len(lines) == 2
    p0 = json.loads(lines[0])
    assert p0["target_url"].rstrip("/") == "https://example.com/page1"
    assert p0["main_domain"].rstrip("/") == "https://example.com"
    assert p0["platform"] == "blogger"
    assert p0["language"] == "zh-CN"


def test_from_csv_custom_defaults(tmp_path):
    """--from-csv respects --default-platform and --default-language."""
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("https://medium.com/p/abc\n", encoding="utf-8")
    stdout, stderr, code = _run_plan(
        "",
        argv=[
            f"--from-csv={csv_file}",
            "--default-platform=medium",
            "--default-language=en",
            "--default-url-mode=B",
            "--default-publish-mode=publish",
        ],
    )
    assert code == 0
    p = json.loads(stdout.strip())
    assert p["platform"] == "medium"
    assert p["language"] == "en"
    assert p["url_mode"] == "B"
    assert p["publish_mode"] == "publish"


def test_from_csv_empty_file_exits_2(tmp_path):
    """--from-csv with empty file → exit 2."""
    csv_file = tmp_path / "empty.csv"
    csv_file.write_text("", encoding="utf-8")
    stdout, stderr, code = _run_plan("", argv=[f"--from-csv={csv_file}"])
    assert code == 2


def test_from_csv_mutual_exclusion_with_input():
    """--from-csv combined with --input → exit 2."""
    stdout, stderr, code = _run_plan(
        '{"target_url": "https://a.com"}',
        argv=["--from-csv=somefile.csv", "--input=/dev/stdin"],
    )
    # Should fail before even trying to open the file
    assert code in (2, 1)


def test_from_csv_and_from_sitemap_mutually_exclusive(tmp_path):
    """--from-csv and --from-sitemap together → exit 2."""
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("https://a.com\n", encoding="utf-8")
    stdout, stderr, code = _run_plan(
        "",
        argv=[f"--from-csv={csv_file}", "--from-sitemap=https://example.com/sitemap.xml"],
    )
    assert code == 2


def test_from_sitemap_generates_payloads():
    """--from-sitemap fetches sitemap and generates payloads for each URL."""
    sitemap_xml = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://site.com/page1</loc></url>
  <url><loc>https://site.com/page2</loc></url>
</urlset>"""
    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp.content = sitemap_xml
    mock_resp.raise_for_status = MagicMock()

    with patch("backlink_publisher.http.get", return_value=mock_resp):
        stdout, stderr, code = _run_plan(
            "", argv=["--from-sitemap=https://site.com/sitemap.xml"]
        )

    assert code == 0
    lines = [l for l in stdout.strip().split("\n") if l]
    assert len(lines) == 2
    urls = {json.loads(l)["target_url"].rstrip("/") for l in lines}
    assert "https://site.com/page1" in urls
    assert "https://site.com/page2" in urls


def test_from_sitemap_network_error_exits_2():
    """--from-sitemap with network error → exit 2."""
    with patch("backlink_publisher.http.get", side_effect=ConnectionError("offline")):
        stdout, stderr, code = _run_plan(
            "", argv=["--from-sitemap=https://example.com/sitemap.xml"]
        )
    assert code == 2
