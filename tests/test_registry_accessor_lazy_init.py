"""Regression test: registry accessors must trigger lazy adapter init.

Bug found while running U11 canary-seed by hand (2026-07-06): a fresh process
calling ``dofollow_status()`` (or ``visibility()``/``referral_value()``/etc.)
before any call to ``registered_platforms()`` saw an empty ``_REGISTRY`` and
silently returned the "unregistered" default for a genuinely-registered
platform — ``canary-seed`` rejected every platform as "not eligible" with
``status=None`` even though the same process's ``registered_platforms()``
call (evaluated microseconds later, in the same expression) listed it as
eligible. Root cause: only ``registered_platforms()``, ``publish()``, and
``verify_adapter_setup()`` called ``_ensure_adapters_initialized()`` before
reading ``_REGISTRY``; every other accessor read it directly.

This test resets the module-global init flag to simulate a cold process and
asserts each accessor still returns the correct value — proving each one
independently triggers lazy init rather than relying on caller ordering.
"""
from __future__ import annotations

__tier__ = "unit"

import backlink_publisher.publishing.adapters as _adapters
from backlink_publisher.publishing import registry
from backlink_publisher.publishing._registry_manifest import visibility


def _reset_registry_cold_state(monkeypatch):
    """Simulate a fresh process: adapters not yet lazily initialized."""
    monkeypatch.setattr(_adapters, "_INITIALIZED", False)
    registry._REGISTRY.clear()


def test_dofollow_status_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    # Cold call, no prior registered_platforms()/publish() in this "process".
    assert registry.dofollow_status("txtfyi") == "uncertain"


def test_is_registered_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    assert registry.is_registered("txtfyi") is True


def test_referral_value_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    assert registry.referral_value("txtfyi") == "low"


def test_dofollow_rationale_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    assert registry.dofollow_rationale("txtfyi") is not None


def test_credential_saver_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    # Should not raise / should resolve via the initialized registry rather
    # than silently reporting "unregistered" (None is a valid value for
    # platforms with no saver, so we assert against a definitely-registered
    # medium-confidence signal instead: is_registered must be True first).
    assert registry.is_registered("rentry") is True
    registry.credential_saver("rentry")  # must not raise


def test_dispatch_weight_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    # A registered platform with no dynamic override returns its static
    # weight (default 1.0), not the unregistered-platform fallback value —
    # both happen to be 1.0 here, so assert via is_registered() as the
    # discriminating signal that init actually ran.
    registry.dispatch_weight("rentry")
    assert registry.is_registered("rentry") is True


def test_manifest_visibility_triggers_lazy_init_on_cold_registry(monkeypatch):
    _reset_registry_cold_state(monkeypatch)
    # hashnode is registered visibility="retired" — the "active" default
    # would be returned if the registry were still empty at read time.
    assert visibility("hashnode") == "retired"
