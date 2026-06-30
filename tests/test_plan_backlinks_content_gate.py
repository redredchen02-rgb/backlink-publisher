"""Tests for plan-backlinks content fetch gate integration.

Extracted from ``test_plan_backlinks.py`` (split refactoring).

Plan 2026-05-14-007: URL content-fetch gate wired into ``_build_links``.
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest

from _plan_test_helpers import _run_plan


class TestContentFetchGate:
    """Plan 2026-05-14-007: URL content-fetch gate wired into _build_links."""

    def test_supporting_link_gate_failure_drops_link_and_keeps_row(
        self, monkeypatch,
    ):
        """One supporting URL fails the gate → article emits with the
        survivors + a density paragraph; row is NOT aborted because the
        failing URL is `kind=supporting`, not main_domain / target."""
        def _selective_batch(urls, max_workers=5):
            result = {}
            for u in urls:
                if u == "https://en.wikipedia.org":
                    result[u] = (False, "http_200_no_title", None)
                else:
                    result[u] = (True, None, "mock title")
            return result

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch",
            _selective_batch,
        )

        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        stdout, _, code = _run_plan(json.dumps(seed))
        assert code == 0
        payload = json.loads(stdout.strip())
        urls = [link["url"] for link in payload["links"]]
        assert "https://en.wikipedia.org" not in urls, (
            "gate-failed supporting URL must be dropped from links"
        )
        assert len(urls) >= 5

    def test_target_url_unreachable_aborts_row(self, monkeypatch):
        """target_url is unreachable -> row is dropped."""
        def _fail_target(url, **kwargs):
            return False, "http_404", None

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_url_has_content",
            _fail_target,
        )

        seed = {
            "target_url": "https://example.com/unreachable",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 2
        assert "unreachable" in stderr.lower()
        assert "http_404" in stderr.lower()
        assert stdout.strip() == ""

    def test_main_domain_gate_failure_aborts_row(self, monkeypatch):
        """main_domain fails the gate → row is dropped; tripwire records
        the drop under the `content_gate` bucket; exit code is 2."""
        def _fail_main(urls, max_workers=5):
            return {
                u: (
                    (False, "http_404", None)
                    if u == "https://example.com"
                    else (True, None, "mock title")
                )
                for u in urls
            }

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch",
            _fail_main,
        )

        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        stdout, stderr, code = _run_plan(json.dumps(seed))
        assert code == 2
        assert stdout.strip() == ""
        recon_lines = [
            line for line in stderr.splitlines()
            if '"msg": "plan_reconciliation"' in line
        ]
        assert recon_lines
        recon = json.loads(recon_lines[0])
        assert recon["dropped"]["content_gate"] == 1
        assert recon["dropped"]["validation"] == 0
        assert recon["dropped"]["generation"] == 0

    def test_target_gate_failure_aborts_row(self, monkeypatch):
        """target_url fails the gate → row dropped under content_gate."""
        def _fail_target(urls, max_workers=5):
            return {
                u: (
                    (False, "http_404", None)
                    if "/article" in u
                    else (True, None, "mock title")
                )
                for u in urls
            }

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch",
            _fail_target,
        )

        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        stdout, _, code = _run_plan(json.dumps(seed))
        assert code == 2
        assert stdout.strip() == ""

    def test_no_fetch_verify_flag_bypasses_gate(self, monkeypatch):
        """--no-fetch-verify skips the gate entirely."""
        call_count = {"n": 0}

        def _tracking_batch(urls, max_workers=5):
            call_count["n"] += 1
            return {u: (False, "http_404", None) for u in urls}

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch",
            _tracking_batch,
        )

        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "A",
            "publish_mode": "draft",
        }
        stdout, stderr, code = _run_plan(
            json.dumps(seed), argv=["--no-fetch-verify"],
        )
        assert code == 0
        assert stdout.strip() != ""
        assert call_count["n"] == 0
        recon_lines = [
            line for line in stderr.splitlines()
            if '"msg": "fetch_verify_disabled"' in line
        ]
        assert recon_lines

    def test_b_mode_category_link_failure_drops_only_that_link(
        self, monkeypatch, tmp_path,
    ):
        """B-mode category URL fails the gate → category link dropped;
        row keeps publishing; density paragraph compensates."""
        config_toml = (
            '[blogger]\n'
            '"https://example.com/" = "1111"\n\n'
            '[sites."https://example.com".url_categories]\n'
            'home = "https://example.com/"\n'
            'category = "https://example.com/stale-cat"\n'
        )
        bp_dir = tmp_path / "backlink-publisher"
        bp_dir.mkdir(exist_ok=True)
        (bp_dir / "config.toml").write_text(config_toml, encoding="utf-8")
        monkeypatch.setattr(
            "backlink_publisher.config._config_dir",
            lambda: bp_dir,
        )

        def _fail_category(urls, max_workers=5):
            return {
                u: (
                    (False, "http_404", None)
                    if "stale-cat" in u
                    else (True, None, "mock title")
                )
                for u in urls
            }

        monkeypatch.setattr(
            "backlink_publisher.content.fetch.verify_urls_batch",
            _fail_category,
        )

        seed = {
            "target_url": "https://example.com/article",
            "main_domain": "https://example.com",
            "language": "en",
            "platform": "medium",
            "url_mode": "B",
            "publish_mode": "draft",
        }
        stdout, _, code = _run_plan(json.dumps(seed))
        assert code == 0
        payload = json.loads(stdout.strip())
        urls = [link["url"] for link in payload["links"]]
        assert "https://example.com/stale-cat" not in urls
