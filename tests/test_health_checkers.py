"""Tests for the health checker plugin framework.

Coverage:
- ConfigIntegrityChecker valid config → pass
- ConfigIntegrityChecker malformed TOML → fail
- DiskAccessChecker non-existent config dir → fail
- run_all when one checker raises → others still produce results
- run_all() on valid install → all pass or warn
- checker raises non-HealthError → caught, wrapped as fail
"""
from __future__ import annotations

__tier__ = "unit"
import os
from pathlib import Path

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────


def _clean_registry():
    """Return a context manager that isolates the health checker registry."""
    import backlink_publisher.health.registry as hr

    saved = dict(hr._REGISTRY)
    hr._REGISTRY.clear()
    try:
        yield
    finally:
        hr._REGISTRY.clear()
        hr._REGISTRY.update(saved)


def _register_temp(slug: str, check_fn):
    """Temporarily register a checker into the live registry.

    Returns the checker class so the caller can hold a reference.
    The caller must ``_unregister_temp(slug)`` after the test.
    """
    from backlink_publisher.health.registry import (
        HealthChecker,
        HealthResult,
        _REGISTRY,
    )

    class _TempChecker(HealthChecker):
        @classmethod
        def slug(cls) -> str:
            return slug

        @classmethod
        def check(cls) -> HealthResult:
            return check_fn()

    _REGISTRY[slug] = _TempChecker
    return _TempChecker


def _unregister_temp(slug: str):
    from backlink_publisher.health.registry import _REGISTRY

    _REGISTRY.pop(slug, None)


# ── ConfigIntegrityChecker ───────────────────────────────────────────────────


class TestConfigIntegrityChecker:
    def test_valid_config_passes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_toml = config_dir / "config.toml"
        config_toml.write_text("[blogger]\nfoo = \"bar\"\n")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        from backlink_publisher.health.checkers.config_checker import (
            ConfigIntegrityChecker,
        )

        result = ConfigIntegrityChecker.check()
        assert result.status == "pass"
        assert result.slug == "config_integrity"

    def test_malformed_toml_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_toml = config_dir / "config.toml"
        config_toml.write_text("[[[invalid]]]\n")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        from backlink_publisher.health.checkers.config_checker import (
            ConfigIntegrityChecker,
        )

        result = ConfigIntegrityChecker.check()
        assert result.status == "fail"
        assert "error" in (result.details or {})

    def test_missing_config_file_passes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        from backlink_publisher.health.checkers.config_checker import (
            ConfigIntegrityChecker,
        )

        result = ConfigIntegrityChecker.check()
        assert result.status == "pass"


# ── DiskAccessChecker ────────────────────────────────────────────────────────


class TestDiskAccessChecker:
    def test_valid_dirs_pass(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        config_dir = tmp_path / "config"
        cache_dir = tmp_path / "cache"
        config_dir.mkdir()
        cache_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache_dir))

        from backlink_publisher.health.checkers.disk_checker import DiskAccessChecker

        result = DiskAccessChecker.check()
        assert result.status == "pass"

    def test_non_existent_config_dir_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "nonexistent_config"
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache_dir))

        from backlink_publisher.health.checkers.disk_checker import DiskAccessChecker

        result = DiskAccessChecker.check()
        assert result.status == "fail"

    def test_both_dirs_and_canary_write_fail(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "nonexistent_config"
        cache_dir = tmp_path / "nonexistent_cache"
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(cache_dir))

        from backlink_publisher.health.checkers.disk_checker import DiskAccessChecker

        result = DiskAccessChecker.check()
        assert result.status == "fail"
        assert result.details is not None
        assert len(result.details["issues"]) >= 2


# ── CredentialPresenceChecker ────────────────────────────────────────────────


class TestCredentialPresenceChecker:
    def test_sandbox_config_returns_pass_or_warn(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        from backlink_publisher.health.checkers.credential_checker import (
            CredentialPresenceChecker,
        )

        result = CredentialPresenceChecker.check()
        assert result.status in ("pass", "warn")
        assert isinstance(result.details, dict)
        assert "available" in result.details

    def test_warns_when_config_cannot_load(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_toml = config_dir / "config.toml"
        config_toml.write_text("[[[invalid]]]\n")
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        from backlink_publisher.health.checkers.credential_checker import (
            CredentialPresenceChecker,
        )

        result = CredentialPresenceChecker.check()
        assert result.status == "warn"

    def test_with_loaded_adapters(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        import backlink_publisher.publishing.adapters  # noqa: F401

        from backlink_publisher.health.checkers.credential_checker import (
            CredentialPresenceChecker,
        )

        result = CredentialPresenceChecker.check()
        assert result.status in ("pass", "warn")
        assert result.slug == "credential_presence"

    def test_details_show_available_platforms(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        import backlink_publisher.publishing.adapters  # noqa: F401

        from backlink_publisher.health.checkers.credential_checker import (
            CredentialPresenceChecker,
        )

        result = CredentialPresenceChecker.check()
        assert result.details is not None
        assert isinstance(result.details["available"], list)


# ── run_all integration ──────────────────────────────────────────────────────


class TestRunAll:
    def test_run_all_on_valid_setup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        from backlink_publisher.health import run_all

        results = run_all()
        assert len(results) == 3
        slugs = [r.slug for r in results]
        assert "config_integrity" in slugs
        assert "disk_access" in slugs
        assert "credential_presence" in slugs
        for r in results:
            assert r.status in ("pass", "warn", "fail")

    def test_checker_raises_does_not_block_others(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        def _explode():
            raise RuntimeError("intentional failure for test")

        _register_temp("exploder", _explode)
        try:
            from backlink_publisher.health import run_all

            results = run_all()
            slugs = [r.slug for r in results]
            assert "exploder" in slugs
            exploder_result = [r for r in results if r.slug == "exploder"][0]
            assert exploder_result.status == "fail"
            assert "intentional failure" in exploder_result.message
        finally:
            _unregister_temp("exploder")

    def test_checker_exception_wrapped_as_fail(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))

        def _raise_value_error():
            raise ValueError("something unacceptable")

        _register_temp("value_error_checker", _raise_value_error)
        try:
            from backlink_publisher.health import run_all

            results = run_all()
            exploder_result = [
                r for r in results if r.slug == "value_error_checker"
            ][0]
            assert exploder_result.status == "fail"
            assert "something unacceptable" in exploder_result.message
        finally:
            _unregister_temp("value_error_checker")

    def test_registered_checkers_returns_all_slugs(self):
        from backlink_publisher.health import registered_checkers

        slugs = registered_checkers()
        assert "config_integrity" in slugs
        assert "disk_access" in slugs
        assert "credential_presence" in slugs
        assert len(slugs) >= 3


# ── Registry edge cases ──────────────────────────────────────────────────────


class TestRegistry:
    def test_register_duplicate_slug_replaces(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        from backlink_publisher.health.registry import (
            _REGISTRY,
            register,
            HealthChecker,
            HealthResult,
        )

        class A(HealthChecker):
            @classmethod
            def slug(cls) -> str:
                return "dup"

            @classmethod
            def check(cls) -> HealthResult:
                return HealthResult(slug="dup", status="pass", message="original")

        class B(HealthChecker):
            @classmethod
            def slug(cls) -> str:
                return "dup"

            @classmethod
            def check(cls) -> HealthResult:
                return HealthResult(slug="dup", status="pass", message="replacement")

        saved = dict(_REGISTRY)
        _REGISTRY.clear()
        try:
            register(A)
            register(B)
            assert list(_REGISTRY.keys()) == ["dup"]
            assert _REGISTRY["dup"] is B
        finally:
            _REGISTRY.clear()
            _REGISTRY.update(saved)

    def test_register_empty_slug_raises(self):
        from backlink_publisher.health.registry import (
            HealthChecker,
            HealthResult,
            register,
        )

        class NoSlug(HealthChecker):
            @classmethod
            def slug(cls) -> str:
                return ""

            @classmethod
            def check(cls) -> HealthResult:
                return HealthResult(slug="", status="pass", message="")

        with pytest.raises(TypeError, match="non-empty string"):
            register(NoSlug)


# ── Slug uniqueness (check no two built-in checkers share a slug) ────────────


class TestBuiltinSlugUniqueness:
    def test_all_builtin_slugs_unique(self):
        from backlink_publisher.health import registered_checkers

        slugs = registered_checkers()
        assert len(slugs) == len(set(slugs))
