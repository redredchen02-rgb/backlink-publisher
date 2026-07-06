"""Plan 2026-05-25-002 Unit 2a/2b — visibility reverse-lookup wiring.

Unit 2a: ``webui_app.binding_status.hidden_from_ui()`` (and its PEP 562
``HIDDEN_FROM_UI`` alias) reflects the registry manifest ``visibility``
field dynamically.

Unit 2b: ``config._toml_utils._save_config_known_roots()`` (and its PEP
562 ``_SAVE_CONFIG_KNOWN_ROOTS`` alias) derives from registered non-retired
platforms + fixed non-platform roots (targets, image_gen).
"""
from __future__ import annotations

__tier__ = "unit"
from typing import Any

import pytest

from backlink_publisher.publishing.adapters.base import AdapterResult
from backlink_publisher.publishing.registry import (
    _BIND_BY_PLATFORM,
    _POLICY_BY_PLATFORM,
    _REGISTRY,
    _UI_META_BY_PLATFORM,
    _VISIBILITY_BY_PLATFORM,
    Publisher,
    register,
)


class _Fake(Publisher):
    def publish(
        self, payload: dict[str, Any], mode: str, config: Any
    ) -> AdapterResult:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _snapshot():
    snaps = [
        (_REGISTRY, dict(_REGISTRY)),
        (_UI_META_BY_PLATFORM, dict(_UI_META_BY_PLATFORM)),
        (_BIND_BY_PLATFORM, dict(_BIND_BY_PLATFORM)),
        (_POLICY_BY_PLATFORM, dict(_POLICY_BY_PLATFORM)),
        (_VISIBILITY_BY_PLATFORM, dict(_VISIBILITY_BY_PLATFORM)),
    ]
    try:
        yield
    finally:
        for store, snap in snaps:
            store.clear()
            store.update(snap)


class TestHiddenFromUiFunction:
    def test_retired_platforms_appear_in_hidden_from_ui(self) -> None:
        # hashnode and writeas were retired in plan 008.
        import backlink_publisher.publishing.adapters  # noqa: F401
        from webui_app.binding_status import hidden_from_ui

        hidden = hidden_from_ui()
        assert "hashnode" in hidden
        assert "writeas" in hidden

    def test_includes_visibility_hidden_platform(self) -> None:
        from webui_app.binding_status import hidden_from_ui

        register("vis_hidden", _Fake, dofollow=True, visibility="hidden")
        assert "vis_hidden" in hidden_from_ui()

    def test_includes_visibility_retired_platform(self) -> None:
        from webui_app.binding_status import hidden_from_ui

        register("vis_retired", _Fake, dofollow=True, visibility="retired")
        assert "vis_retired" in hidden_from_ui()

    def test_excludes_experimental(self) -> None:
        # Experimental is NOT in the HIDDEN set — UI may surface it
        # behind an opt-in toggle. HIDDEN_FROM_UI specifically means
        # "card never appears in the default dashboard view".
        from webui_app.binding_status import hidden_from_ui

        register("vis_exp", _Fake, dofollow=True, visibility="experimental")
        assert "vis_exp" not in hidden_from_ui()


class TestPep562ModuleAlias:
    """Existing readers do ``from .binding_status import HIDDEN_FROM_UI``
    and treat it as a frozenset. The PEP 562 ``__getattr__`` hook keeps
    that interface working without forcing a function-call migration."""

    def test_module_level_HIDDEN_FROM_UI_returns_frozenset(self) -> None:
        from webui_app import binding_status

        assert isinstance(binding_status.HIDDEN_FROM_UI, frozenset)

    def test_module_level_HIDDEN_FROM_UI_is_dynamic(self) -> None:
        # Two accesses around a register() call must observe the new
        # value — this is the load-bearing property that lets Unit 2a
        # drop the static constant without breaking existing readers.
        from webui_app import binding_status

        before = binding_status.HIDDEN_FROM_UI
        register("vis_dyn", _Fake, dofollow=True, visibility="hidden")
        after = binding_status.HIDDEN_FROM_UI
        assert "vis_dyn" not in before
        assert "vis_dyn" in after

    def test_attribute_error_on_unknown_name(self) -> None:
        from webui_app import binding_status

        with pytest.raises(AttributeError, match="has no attribute"):
            binding_status.NONEXISTENT_NAME  # type: ignore[attr-defined]


# ── Unit 2b: _save_config_known_roots() ──────────────────────────────────────


class TestSaveConfigKnownRootsFunction:
    """_save_config_known_roots() derives from registry — no hand-maintained set."""

    def test_contains_fixed_non_platform_roots(self) -> None:
        from backlink_publisher.config._toml_utils import _save_config_known_roots
        import backlink_publisher.publishing.adapters  # noqa: F401

        roots = _save_config_known_roots()
        assert "targets" in roots
        assert "image_gen" in roots

    def test_contains_active_registered_platforms(self) -> None:
        from backlink_publisher.config._toml_utils import _save_config_known_roots
        import backlink_publisher.publishing.adapters  # noqa: F401
        from backlink_publisher.publishing.registry import active_platforms

        roots = _save_config_known_roots()
        for name in active_platforms():
            assert name in roots, f"active platform {name!r} missing from known_roots"

    def test_excludes_retired_platform(self) -> None:
        from backlink_publisher.config._toml_utils import _save_config_known_roots

        register("retired_plat", _Fake, dofollow=True, visibility="retired")
        assert "retired_plat" not in _save_config_known_roots()

    def test_includes_active_and_experimental(self) -> None:
        from backlink_publisher.config._toml_utils import _save_config_known_roots

        register("exp_plat", _Fake, dofollow=True, visibility="experimental")
        assert "exp_plat" in _save_config_known_roots()


class TestSaveConfigKnownRootsPep562Alias:
    """PEP 562 __getattr__ alias keeps legacy import path working."""

    def test_module_level_alias_returns_frozenset(self) -> None:
        from backlink_publisher.config import _toml_utils

        assert isinstance(_toml_utils._SAVE_CONFIG_KNOWN_ROOTS, frozenset)

    def test_alias_is_dynamic(self) -> None:
        from backlink_publisher.config import _toml_utils

        before = _toml_utils._SAVE_CONFIG_KNOWN_ROOTS
        register("dyn_plat", _Fake, dofollow=True)
        after = _toml_utils._SAVE_CONFIG_KNOWN_ROOTS
        assert "dyn_plat" not in before
        assert "dyn_plat" in after

    def test_attribute_error_on_unknown_name(self) -> None:
        from backlink_publisher.config import _toml_utils

        with pytest.raises(AttributeError, match="has no attribute"):
            _toml_utils.NONEXISTENT_ATTR  # type: ignore[attr-defined]
