"""Phase 0 U6 — activation-readiness tripwire.

#24's real failure was an integration test that was *plain red but tolerated*
(failing, not skipped), masking a silent production no-op. This tripwire makes
the two ways a subsystem's tests can be *hidden* impossible to do silently:

  1. whole-file disappearance — a module-level ``pytestmark = skip`` or a file
     with zero ``def test_`` (collected == 0), and
  2. untracked per-test skip/xfail — a ``@pytest.mark.skip``/``xfail`` with no
     ``reason=`` (an untracked hide).

The "is it actually green?" gate itself is enforced by CI (which runs the
integration tier) + the activation runbook (``docs/runbooks/2026-06-17-activation-
readiness.md``), which requires ``pytest <subsystem files>`` to exit 0 before a
subsystem is activated. A debt-ref skip does NOT count as green — it only keeps
the red visible; activation stays blocked (see AGENTS.md activation rules).

``assert_subsystem_green(name)`` is exported for the runbook to invoke.
"""
from __future__ import annotations

__tier__ = "unit"

import ast
from pathlib import Path
import subprocess
import sys

import pytest

_TESTS_DIR = Path(__file__).parent

# Each "built-but-unrun" subsystem → the test files that must stay runnable and
# whose green-ness gates the subsystem's activation (Phase 0 plan, Context table).
SUBSYSTEMS: dict[str, list[str]] = {
    "weights": ["test_optimization_e2e.py", "test_cli_weights.py"],
    "citation": ["test_cli_probe_citations.py"],
    "enforce": ["test_reliability_enforce_seam.py", "test_reliability_decision_events.py"],
    "recheck": ["test_cli_recheck_backlinks.py", "test_recheck_events_io.py"],
}

_ALL_FILES = [(s, f) for s, files in SUBSYSTEMS.items() for f in files]


def _module_is_skipped(tree: ast.Module) -> bool:
    """True if the module carries a top-level ``pytestmark = ...skip...``."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "pytestmark" in targets and "skip" in ast.dump(node.value):
                return True
    return False


def _untracked_skips(tree: ast.Module) -> list[str]:
    """Return names of test functions whose skip/xfail marker has no reason=."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        for dec in node.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            attr = call.func if call else dec
            name = ast.dump(attr)
            if "skip" not in name and "xfail" not in name:
                continue
            # A bare marker (no call) or a call without reason= is untracked.
            has_reason = bool(
                call and any(k.arg == "reason" and k.value for k in call.keywords)
            )
            if not has_reason:
                offenders.append(node.name)
    return offenders


@pytest.mark.parametrize("subsystem,filename", _ALL_FILES, ids=[f for _, f in _ALL_FILES])
def test_subsystem_test_file_is_runnable(subsystem, filename):
    """Each subsystem test file must exist, define ≥1 test, and not be
    whole-file skipped — so CI red on it is real and can't silently vanish."""
    path = _TESTS_DIR / filename
    assert path.exists(), f"{subsystem}: missing test file {filename}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not _module_is_skipped(tree), (
        f"{subsystem}: {filename} is whole-file skipped (pytestmark) — "
        f"a hidden subsystem cannot be activated"
    )
    n_tests = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("test")
    )
    assert n_tests > 0, f"{subsystem}: {filename} collected 0 tests"


@pytest.mark.parametrize("subsystem,filename", _ALL_FILES, ids=[f for _, f in _ALL_FILES])
def test_no_untracked_skip_or_xfail(subsystem, filename):
    """A skip/xfail in a subsystem test must carry a reason= (tracked). A bare
    marker is an untracked hide — the #24-adjacent failure mode."""
    tree = ast.parse((_TESTS_DIR / filename).read_text(encoding="utf-8"))
    offenders = _untracked_skips(tree)
    assert not offenders, (
        f"{subsystem}: {filename} has untracked skip/xfail (no reason=): {offenders}. "
        f"Add reason= (with a debt-ref if deferred); a debt-ref skip still blocks "
        f"activation but at least stays visible."
    )


def assert_subsystem_green(name: str) -> None:
    """Run a subsystem's test files and raise if not all green (exit 0).

    Exported for the activation runbook. NOT invoked by the tripwire itself
    (nested pytest is slow); CI runs the integration tier and the runbook calls
    this before flipping a subsystem on. A debt-ref skip does not make it green.
    """
    files = SUBSYSTEMS.get(name)
    if not files:
        raise KeyError(f"unknown subsystem {name!r}; known: {sorted(SUBSYSTEMS)}")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *[str(_TESTS_DIR / f) for f in files]],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise AssertionError(
            f"subsystem {name!r} is NOT green — activation blocked.\n{r.stdout[-2000:]}"
        )
