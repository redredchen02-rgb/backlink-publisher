"""U6 (plan 2026-06-22-001): the top-level facade ``import backlink_publisher``
exposes a resolvable, lazy public API.

Mirrors ``test_config_public_api_resolvable.py``: a cold subprocess proves every
``__all__`` name resolves (no stale re-export), that the package import is LAZY
(merely importing it must NOT register adapters or pull the adapter graph — that
would revive a known cycle and slow every importer), and that the entry points
delegate rather than reimplement.
"""

from __future__ import annotations

__tier__ = "unit"

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"


def _python_subprocess(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_SRC_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )


def test_all_names_resolve_in_fresh_process() -> None:
    """Every entry in ``backlink_publisher.__all__`` is ``getattr``-able after a
    cold import (catches a lazy-branch typo or a deleted re-export target)."""
    result = _python_subprocess(
        "import sys, backlink_publisher as bp; "
        "missing = [n for n in bp.__all__ if not hasattr(bp, n)]; "
        "print('MISSING:', missing) if missing else print('OK'); "
        "sys.exit(1 if missing else 0)"
    )
    assert result.returncode == 0, (
        f"backlink_publisher.__all__ has unresolvable names.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_import_is_lazy_no_eager_adapter_registration() -> None:
    """``import backlink_publisher`` must NOT register adapters or import the
    adapter graph — the registry stays empty until ``register_all_adapters()`` /
    an explicit adapter import. Proves the facade is lazy (no cycle, no eager
    side effects)."""
    result = _python_subprocess(
        "import sys, backlink_publisher; "
        "from backlink_publisher.publishing.registry import registered_platforms; "
        "n = len(registered_platforms()); "
        "print('REGISTERED:', n); "
        "sys.exit(0 if n == 0 else 1)"
    )
    assert result.returncode == 0, (
        f"`import backlink_publisher` eagerly registered adapters (registry not "
        f"empty) — the facade leaked a non-lazy import.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_error_classes_carry_exit_codes() -> None:
    """The exported error taxonomy keeps its per-class exit-code contract."""
    import backlink_publisher as bp

    assert bp.UsageError.exit_code == 1
    assert bp.InputValidationError.exit_code == 2
    assert bp.DependencyError.exit_code == 3
    assert bp.AuthExpiredError.exit_code == 3  # DependencyError family
    assert bp.ExternalServiceError.exit_code == 4
    assert bp.AntiBotChallengeError.exit_code == 4  # ExternalServiceError family
    assert bp.InternalError.exit_code == 5
    assert bp.RegistryError.exit_code == 5
    assert bp.PipelineError.exit_code == 5  # base default


def test_dispatch_delegates_to_adapters_publish() -> None:
    """``backlink_publisher.dispatch`` IS the low-level single-payload adapter
    publisher — zero reimplementation."""
    import backlink_publisher as bp
    from backlink_publisher.publishing.adapters import publish as adapters_publish

    assert bp.dispatch is adapters_publish


def test_pipeline_entry_points_delegate_to_sdk() -> None:
    """``plan``/``validate``/``publish`` at the root ARE the sdk thin wrappers."""
    import backlink_publisher as bp
    from backlink_publisher import sdk

    assert bp.plan is sdk.plan
    assert bp.validate is sdk.validate
    assert bp.publish is sdk.publish


def test_unknown_attribute_raises_attribute_error() -> None:
    """``__getattr__`` must raise AttributeError for unknown names (not KeyError /
    silent None) so ``hasattr`` and ``from bp import X`` behave correctly."""
    import backlink_publisher as bp

    try:
        bp.does_not_exist  # noqa: B018
    except AttributeError:
        pass
    else:
        raise AssertionError("expected AttributeError for unknown facade attribute")
