"""U7 (plan 2026-06-22-001): the SDK facade + every console-script entry point
resolves.

Two import-time gates:
  1. The public facade symbols (``backlink_publisher.sdk`` thin functions + the
     classes, and every name in ``backlink_publisher.__all__``) are ``getattr``-able.
  2. Every ``[project.scripts]`` ``mod:func`` target imports and exposes a callable
     ``func`` — mirrors ``test_bp_registry.py``; catches a renamed/moved entry
     point (the operator would otherwise see it only at console-script launch time).
"""

from __future__ import annotations

__tier__ = "unit"

import importlib
from pathlib import Path
import tomllib

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def test_sdk_facade_symbols_resolve() -> None:
    sdk = importlib.import_module("backlink_publisher.sdk")
    for name in ("plan", "validate", "publish", "PipelineAPI", "PipeResult"):
        assert hasattr(sdk, name), f"backlink_publisher.sdk missing {name!r}"
    assert callable(sdk.plan) and callable(sdk.validate) and callable(sdk.publish)

    bp = importlib.import_module("backlink_publisher")
    unresolved = [n for n in bp.__all__ if not hasattr(bp, n)]
    assert unresolved == [], f"backlink_publisher.__all__ unresolvable: {unresolved}"


def _console_scripts() -> list[tuple[str, str, str]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str]] = []
    for cmd, target in data["project"]["scripts"].items():
        mod, _, func = target.partition(":")
        rows.append((cmd, mod, func))
    return rows


@pytest.mark.parametrize(
    "cmd,mod,func", _console_scripts(), ids=[r[0] for r in _console_scripts()]
)
def test_console_script_entrypoint_resolves(cmd: str, mod: str, func: str) -> None:
    module = importlib.import_module(mod)
    target = getattr(module, func, None)
    assert callable(target), (
        f"[project.scripts] {cmd} = {mod}:{func} does not resolve to a callable — "
        "the entry point was renamed/moved without updating pyproject.toml."
    )
