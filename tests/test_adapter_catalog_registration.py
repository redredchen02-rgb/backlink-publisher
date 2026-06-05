"""U3 — Auto-scan registration: catalog YAML → registered platform.

Headline success criterion: a fixture ``.yaml`` in a catalog dir appears
in ``registered_platforms()`` after ``register_catalog_entries()`` is
called, with zero Python edits to ``adapters/__init__.py`` beyond the
auto-scan wiring already committed.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
import yaml

from backlink_publisher.publishing import registry as _registry_mod
from backlink_publisher.publishing.adapters import (
    _CATALOG_AUTO_REGISTERED,
    register_catalog_entries,
)


def _save_registry(keys: set[str]) -> dict:
    """Snapshot selected keys from ``_REGISTRY`` for later restore."""
    reg = _registry_mod._REGISTRY
    return {k: reg[k] for k in keys if k in reg}


def _restore_registry(saved: dict, touched: set[str]) -> None:
    """Restore previously snapshot keys, removing any test-added leftovers.

    For each key in ``touched``: restore its original value if it was in
    the snapshot, or remove it from the registry if it was not present before
    the test ran. Only ``touched`` keys are modified — real registered
    platforms are unaffected.
    """
    reg = _registry_mod._REGISTRY
    for k in touched:
        if k in saved:
            reg[k] = saved[k]
        else:
            reg.pop(k, None)


class TestAutoRegistration:
    """Registering a fixture YAML catalog entry."""

    _TEST_SLUG = "test-ureg-platform"
    _TEST_SLUG_2 = "test-ureg-override"

    def _make_entry(self, slug: str, **overrides: object) -> dict:
        entry = {
            "endpoint": "https://test.example.com/submit",
            "auth_type": "none",
            "content_field": "body",
            "csrf_prefetch": False,
            "csrf_field_names": [],
            "permalink_via": "redirect",
            "permalink_arg": "Location",
            "min_delay_s": 0.0,
            "dofollow": True,
        }
        entry.update(overrides)
        return entry

    def _write_catalog(
        self, directory: Path, slug: str, entry: dict
    ) -> Path:
        path = directory / f"{slug}.yaml"
        with open(path, "w") as f:
            yaml.dump({slug: entry}, f)
        return path

    @pytest.fixture(autouse=True)
    def _cleanup_registry(self):
        """Save and restore any slugs this test class touches."""
        touched = {
            self._TEST_SLUG,
            self._TEST_SLUG_2,
            f"{self._TEST_SLUG}-instance",  # registered by test_registered_adapter_is_config_driven_instance
        }
        saved = _save_registry(touched)
        # Also save any keys _CATALOG_AUTO_REGISTERED may have from earlier
        # auto-registration at import time (should be empty in practice).
        cat_saved = set(_CATALOG_AUTO_REGISTERED)
        _CATALOG_AUTO_REGISTERED.clear()
        yield
        _restore_registry(saved, touched)
        # Restore catalog-auto-registered set for process lifetime consistency.
        _CATALOG_AUTO_REGISTERED.clear()
        _CATALOG_AUTO_REGISTERED.update(cat_saved)

    def test_fixture_yaml_appears_in_registered_platforms(self, tmp_path):
        """A YAML fixture auto-registers with zero Python edits."""
        entry = self._make_entry(self._TEST_SLUG)
        self._write_catalog(tmp_path, self._TEST_SLUG, entry)

        register_catalog_entries(built_in_dir=str(tmp_path))

        assert self._TEST_SLUG in _registry_mod.registered_platforms()
        assert _registry_mod.dofollow_status(self._TEST_SLUG) is True
        assert self._TEST_SLUG in _CATALOG_AUTO_REGISTERED

    def test_user_dir_overrides_built_in(self, tmp_path):
        """User-config dir slug wins over built-in (last-write-wins semantics
        for the same slug in the catalog, before hand-written-adapter check)."""
        built_in = tmp_path / "built_in"
        user = tmp_path / "user"
        built_in.mkdir()
        user.mkdir()

        built_in_entry = self._make_entry(
            self._TEST_SLUG_2, dofollow="uncertain",
            rationale="x" * 80,
            referral_value="low",
        )
        user_entry = self._make_entry(
            self._TEST_SLUG_2, dofollow=True,
        )
        self._write_catalog(built_in, self._TEST_SLUG_2, built_in_entry)
        self._write_catalog(user, self._TEST_SLUG_2, user_entry)

        register_catalog_entries(
            built_in_dir=str(built_in),
            user_config_dir=str(user),
        )

        assert _registry_mod.dofollow_status(self._TEST_SLUG_2) is True

    def test_already_registered_platform_is_not_overwritten(self, tmp_path):
        """A catalog entry cannot overwrite a hand-written adapter."""
        # txtfyi is already registered by hand.  A catalog entry for it
        # should be silently skipped.
        entry = self._make_entry(
            "txtfyi", dofollow=True,  # hand-written says "uncertain"
        )
        self._write_catalog(tmp_path, "txtfyi", entry)

        register_catalog_entries(built_in_dir=str(tmp_path))

        # txtfyi's dofollow status should remain "uncertain" (hand-written wins)
        # rather than being flipped to True by the catalog entry.
        assert _registry_mod.dofollow_status("txtfyi") == "uncertain"

    def test_malformed_yaml_raises_during_scan(self, tmp_path):
        """A badly formed catalog YAML propagates validation errors."""
        path = tmp_path / "bad.yaml"
        path.write_text("bad: [unclosed")

        with pytest.raises(Exception, match="YAML parse error"):
            register_catalog_entries(built_in_dir=str(tmp_path))

    def test_unknown_top_level_key_rejected(self, tmp_path):
        """A YAML entry with an unknown field raises validation error."""
        entry = self._make_entry(self._TEST_SLUG, nonexistent_field="boom")
        self._write_catalog(tmp_path, self._TEST_SLUG, entry)

        with pytest.raises(Exception, match="nonexistent_field"):
            register_catalog_entries(built_in_dir=str(tmp_path))

    def test_empty_catalog_dir_does_not_error(self, tmp_path):
        """An empty catalog directory (no YAML files) is a no-op."""
        register_catalog_entries(built_in_dir=str(tmp_path))
        # No exception is the success condition.

    def test_registered_adapter_is_config_driven_instance(self, tmp_path):
        """The registered publisher is a ConfigDrivenAdapter instance."""
        entry = self._make_entry(f"{self._TEST_SLUG}-instance")
        self._write_catalog(tmp_path, f"{self._TEST_SLUG}-instance", entry)

        register_catalog_entries(built_in_dir=str(tmp_path))

        entry_data = _registry_mod._REGISTRY[f"{self._TEST_SLUG}-instance"]
        from backlink_publisher.publishing.adapters.config_driven import (
            ConfigDrivenAdapter,
        )
        adapter = entry_data.publishers[0]
        assert isinstance(adapter, ConfigDrivenAdapter)
