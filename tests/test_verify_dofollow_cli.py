"""Tests for ``verify-dofollow <slug>`` CLI (U4, CLI-first scope).

Covers: queue read, verify_link_attributes call, verdict logic, and
catalog YAML write-back.  Network and filesystem writes are mocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def queue_path(config_dir: Path) -> Path:
    return config_dir / "verify-queue.jsonl"


@pytest.fixture
def built_in_catalog(config_dir: Path) -> Path:
    """Simulate the built-in catalog dir structure."""
    cat = config_dir / "built_in_catalog"
    cat.mkdir(parents=True, exist_ok=True)
    return cat


def _write_queue(queue_path: Path, entries: list[dict]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _write_catalog_yaml(catalog_dir: Path, slug: str, dofollow: object) -> Path:
    path = catalog_dir / f"{slug}.yaml"
    data = {
        slug: {
            "endpoint": "https://example.com/submit",
            "auth_type": "none",
            "content_field": "body",
            "csrf_prefetch": False,
            "csrf_field_names": [],
            "permalink_via": "redirect",
            "permalink_arg": "Location",
            "min_delay_s": 0.0,
            "dofollow": dofollow,
            "rationale": "x" * 80,
            "referral_value": "low",
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFindLatestForSlug:
    """Internal helper that reads the queue JSONL."""

    def test_missing_queue_returns_none(self, config_dir: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_latest_for_slug

        q = config_dir / "verify-queue.jsonl"
        assert _find_latest_for_slug(q, "txtfyi") is None

    def test_empty_queue_returns_none(self, queue_path: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_latest_for_slug

        _write_queue(queue_path, [])
        assert _find_latest_for_slug(queue_path, "txtfyi") is None

    def test_returns_latest_url_for_slug(self, queue_path: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_latest_for_slug

        _write_queue(queue_path, [
            {"slug": "txtfyi", "published_url": "https://old.example.com",
             "ts_utc": "2026-01-01T00:00:00Z"},
            {"slug": "other", "published_url": "https://other.example.com",
             "ts_utc": "2026-06-01T00:00:00Z"},
            {"slug": "txtfyi", "published_url": "https://latest.example.com",
             "ts_utc": "2026-06-05T12:00:00Z"},
        ])
        assert _find_latest_for_slug(queue_path, "txtfyi") == "https://latest.example.com"

    def test_ignores_malformed_lines(self, queue_path: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_latest_for_slug

        _write_queue(queue_path, [
            {"slug": "txtfyi", "published_url": "https://valid.example.com",
             "ts_utc": "2026-06-05T12:00:00Z"},
        ])
        # Manually append a malformed line.
        with open(queue_path, "a") as f:
            f.write("not-json\n")
        assert _find_latest_for_slug(queue_path, "txtfyi") == "https://valid.example.com"


class TestFindCatalogPath:
    """Internal helper that resolves the catalog YAML path."""

    def test_returns_built_in_path(self, config_dir: Path, built_in_catalog: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_catalog_path
        from backlink_publisher.config.loader import _config_dir

        _write_catalog_yaml(built_in_catalog, "txtfyi", "uncertain")
        # Point _config_dir at config_dir so built-in lookup works.
        # We patch the function inside verify_dofollow's scope so it sees
        # the same built-in-catalog path generation logic.
        path = _find_catalog_path("txtfyi", config_dir)
        assert path is not None
        assert path.exists()

    def test_user_override_precedes_built_in(self, config_dir: Path, built_in_catalog: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_catalog_path

        _write_catalog_yaml(built_in_catalog, "txtfyi", "uncertain")
        user_dir = config_dir / "catalog"
        _write_catalog_yaml(user_dir, "txtfyi", True)

        path = _find_catalog_path("txtfyi", config_dir)
        assert path is not None
        assert str(config_dir / "catalog") in str(path)
        assert path.exists()

    def test_unknown_slug_returns_none(self, config_dir: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _find_catalog_path
        assert _find_catalog_path("nonexistent", config_dir) is None


class TestWriteDofollowToCatalog:
    """Internal helper that writes back the dofollow verdict."""

    @pytest.mark.parametrize("source_is_built_in", [True, False])
    def test_always_writes_to_user_override_dir(
        self, config_dir: Path, built_in_catalog: Path, source_is_built_in: bool,
    ) -> None:
        from backlink_publisher.cli.verify_dofollow import _write_dofollow_to_catalog

        src_dir = built_in_catalog if source_is_built_in else config_dir / "catalog"
        src_dir.mkdir(parents=True, exist_ok=True)
        cat_path = _write_catalog_yaml(src_dir, "txtfyi", "uncertain")

        with patch(
            "backlink_publisher.cli.verify_dofollow._config_dir",
            return_value=config_dir,
        ):
            _write_dofollow_to_catalog(cat_path, "txtfyi", True)

        user_path = config_dir / "catalog" / "txtfyi.yaml"
        assert user_path.exists()
        with open(user_path) as f:
            data = yaml.safe_load(f)
        assert data["txtfyi"]["dofollow"] is True

    def test_updates_existing_user_override_in_place(
        self, config_dir: Path,
    ) -> None:
        from backlink_publisher.cli.verify_dofollow import _write_dofollow_to_catalog

        user_dir = config_dir / "catalog"
        cat_path = _write_catalog_yaml(user_dir, "txtfyi", "uncertain")

        with patch(
            "backlink_publisher.cli.verify_dofollow._config_dir",
            return_value=config_dir,
        ):
            _write_dofollow_to_catalog(cat_path, "txtfyi", False)

        assert cat_path.exists()
        with open(cat_path) as f:
            data = yaml.safe_load(f)
        assert data["txtfyi"]["dofollow"] is False

    def test_invalid_yaml_raises_exit(self, config_dir: Path) -> None:
        from backlink_publisher.cli.verify_dofollow import _write_dofollow_to_catalog

        bad_path = config_dir / "catalog" / "bad.yaml"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("not: valid: yaml: [[[")

        with pytest.raises(SystemExit):
            _write_dofollow_to_catalog(bad_path, "bad", True)


class TestCLIIntegration:
    """End-to-end CLI behaviour with mocked network and atomic write."""

    VERIFIER_PATH = (
        "backlink_publisher.cli.verify_dofollow.verify_link_attributes"
    )

    @patch("backlink_publisher.cli.verify_dofollow.atomic_write")
    def test_happy_path_dofollow_true(
        self, mock_atomic_write, config_dir: Path, queue_path: Path,
    ) -> None:
        """Known dofollow platform → verdict=True → catalog updated."""
        from backlink_publisher.cli.verify_dofollow import main as cli_main

        _write_queue(queue_path, [
            {"slug": "txtfyi", "published_url": "https://txt.fyi/~/abc123",
             "ts_utc": "2026-06-05T12:00:00Z"},
        ])

        self._write_catalog_for_test(config_dir)

        with patch(self.VERIFIER_PATH) as mock_verify:
            mock_verify.return_value = {
                "verification": "ok",
                "total_anchors": 5,
                "nofollow_anchors": 0,
                "nofollow_detected": False,
                "target_nofollow": False,
            }
            with patch(
                "backlink_publisher.cli.verify_dofollow._config_dir",
                return_value=config_dir,
            ):
                with patch.object(sys, "argv", ["verify-dofollow", "txtfyi"]):
                    cli_main()

        mock_atomic_write.assert_called_once()
        args, _ = mock_atomic_write.call_args
        assert "dofollow: true" in args[1] or "dofollow: True" in args[1]


    @patch("backlink_publisher.cli.verify_dofollow.atomic_write")
    def test_nofollow_detected_writes_false(
        self, mock_atomic_write, config_dir: Path, queue_path: Path,
    ) -> None:
        """Page-wide nofollow detected → verdict=False."""
        from backlink_publisher.cli.verify_dofollow import main as cli_main

        _write_queue(queue_path, [
            {"slug": "txtfyi", "published_url": "https://txt.fyi/~/abc123",
             "ts_utc": "2026-06-05T12:00:00Z"},
        ])

        self._write_catalog_for_test(config_dir)

        with patch(self.VERIFIER_PATH) as mock_verify:
            mock_verify.return_value = {
                "verification": "ok",
                "total_anchors": 10,
                "nofollow_anchors": 8,
                "nofollow_detected": True,
                "target_nofollow": False,
            }
            with patch(
                "backlink_publisher.cli.verify_dofollow._config_dir",
                return_value=config_dir,
            ):
                with patch.object(sys, "argv", ["verify-dofollow", "txtfyi"]):
                    cli_main()

        mock_atomic_write.assert_called_once()
        args, _ = mock_atomic_write.call_args
        assert "dofollow: false" in args[1] or "dofollow: False" in args[1]

    @patch("backlink_publisher.cli.verify_dofollow.atomic_write")
    def test_no_queue_entry_exits_cleanly(
        self, mock_atomic_write, config_dir: Path,
    ) -> None:
        """Missing queue entry → prints message, exit 0, no write."""
        from backlink_publisher.cli.verify_dofollow import main as cli_main

        with patch(
            "backlink_publisher.cli.verify_dofollow._config_dir",
            return_value=config_dir,
        ):
            with patch.object(sys, "argv", ["verify-dofollow", "txtfyi"]):
                cli_main()
        mock_atomic_write.assert_not_called()

    def test_skipped_verification_no_write(self, config_dir: Path, queue_path: Path) -> None:
        """Network failure → verification skipped → no catalog write."""
        from backlink_publisher.cli.verify_dofollow import main as cli_main

        _write_queue(queue_path, [
            {"slug": "txtfyi", "published_url": "https://txt.fyi/~/abc123",
             "ts_utc": "2026-06-05T12:00:00Z"},
        ])

        self._write_catalog_for_test(config_dir)

        with patch(self.VERIFIER_PATH) as mock_verify:
            mock_verify.return_value = {
                "verification": "skipped",
                "reason": "HTTP 500",
            }
            with patch(
                "backlink_publisher.cli.verify_dofollow._config_dir",
                return_value=config_dir,
            ):
                with patch(
                    "backlink_publisher.cli.verify_dofollow.atomic_write"
                ) as mock_write:
                    with patch.object(sys, "argv", ["verify-dofollow", "txtfyi"]):
                        cli_main()

        mock_write.assert_not_called()

    def test_non_catalog_platform_skips_write(
        self, config_dir: Path, queue_path: Path,
    ) -> None:
        """Slug with no catalog YAML → no write-back attempted."""
        from backlink_publisher.cli.verify_dofollow import main as cli_main

        _write_queue(queue_path, [
            {"slug": "blogger", "published_url": "https://blogger.example.com/post",
             "ts_utc": "2026-06-05T12:00:00Z"},
        ])

        with patch(self.VERIFIER_PATH) as mock_verify:
            mock_verify.return_value = {
                "verification": "ok",
                "total_anchors": 3,
                "nofollow_anchors": 0,
                "nofollow_detected": False,
                "target_nofollow": False,
            }
            with patch(
                "backlink_publisher.cli.verify_dofollow._config_dir",
                return_value=config_dir,
            ):
                with patch(
                    "backlink_publisher.cli.verify_dofollow.atomic_write"
                ) as mock_write:
                    with patch.object(sys, "argv", ["verify-dofollow", "blogger"]):
                        cli_main()

        mock_write.assert_not_called()

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _write_catalog_for_test(config_dir: Path) -> None:
        """Write a minimal txtfyi catalog YAML into the test-built-in location."""
        built_in = (
            Path(__file__).resolve().parent.parent
            / "src" / "backlink_publisher"
            / "publishing" / "adapters" / "catalog"
        )
        target = built_in / "txtfyi.yaml"
        if target.exists():
            return  # use the real file
        # Fallback: write to a temp location that _find_catalog_path can find
        # by patching the module-level path. For simplicity, we use the
        # user-override dir.
        user_dir = config_dir / "catalog"
        _write_catalog_yaml(user_dir, "txtfyi", "uncertain")
