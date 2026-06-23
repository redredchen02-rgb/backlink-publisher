"""U7 (plan 2026-06-22-001): the core package must NOT import webui_app.

Permanent layering guard — the protection that was missing when the 3 reverse
edges crept in. After U2 (reverse edges → core) and U5a (PipelineAPI + cli_runner
relocated to core ``sdk/``), there are ZERO ``core → webui_app`` import edges, so
the allowlist is EMPTY.

The guard is AST-based: it parses imports and so ignores docstrings/comments that
merely *mention* ``webui_app`` (there are several "Extracted from webui_app/…"
provenance notes in core), and it catches BOTH top-level and in-function imports
(the way the old edges hid). ``webui_store`` is a legitimate core dependency
(~10 modules: ``canary/store.py``, ``cli/dispatch_backlinks.py``, …) and is
explicitly NOT matched — the guard keys on ``webui_app`` only.
"""

from __future__ import annotations

__tier__ = "unit"

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE = _REPO_ROOT / "src" / "backlink_publisher"

# Keep EMPTY. A new entry is a layering violation to fix (move shared logic into
# core or webui_store), not an allowlist to grow. See docs/architecture/sdk-layering.md.
_ALLOWLIST: set[str] = set()


def _webui_app_offenders(tree: ast.AST, rel: str) -> list[str]:
    """Return ``f'{rel}:{lineno}'`` for every ABSOLUTE webui_app import in *tree*.

    Matches ``import webui_app[.x]`` and ``from webui_app[.x] import …``. Ignores
    relative imports (``node.level > 0`` — core is not a sibling of webui_app so a
    relative import can never reach it) and ``webui_store`` (different package).
    """
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "webui_app" or alias.name.startswith("webui_app."):
                    offenders.append(f"{rel}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and (
                node.module == "webui_app" or node.module.startswith("webui_app.")
            ):
                offenders.append(f"{rel}:{node.lineno}")
    return offenders


def _scan_core() -> list[str]:
    offenders: list[str] = []
    for path in sorted(_CORE.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(_webui_app_offenders(tree, rel))
    return offenders


def test_core_does_not_import_webui_app() -> None:
    offenders = sorted(set(_scan_core()))
    assert set(offenders) == _ALLOWLIST, (
        "src/backlink_publisher must not import webui_app (layering guard).\n"
        "Offenders:\n  " + "\n  ".join(offenders or ["<none>"]) + "\n\n"
        "Core may depend on webui_store (state singletons) but NEVER on webui_app "
        "(the Flask app). Move the shared logic into core or webui_store. "
        "See docs/architecture/sdk-layering.md."
    )


def test_guard_detects_in_function_webui_app_import() -> None:
    """The guard isn't vacuous: a FUNCTION-LEVEL ``from webui_app…`` import (how the
    old edges hid) is reported by the same helper the real scan uses."""
    src = (
        "def f():\n"
        "    from webui_app.helpers import cli_runner\n"
        "    return cli_runner\n"
    )
    offenders = _webui_app_offenders(ast.parse(src), "synthetic.py")
    assert offenders == ["synthetic.py:2"], offenders


def test_guard_detects_plain_webui_app_import() -> None:
    offenders = _webui_app_offenders(ast.parse("import webui_app.api as a\n"), "s.py")
    assert offenders == ["s.py:1"], offenders


def test_webui_store_import_is_not_flagged() -> None:
    """``webui_store`` (a legitimate core dep) must NOT be flagged — the guard keys
    on ``webui_app`` only."""
    src = (
        "import webui_store.channel_status\n"
        "from webui_store.queue_store import QueueStore\n"
    )
    assert _webui_app_offenders(ast.parse(src), "s.py") == []


def test_relative_import_is_not_flagged() -> None:
    """A relative ``from . import x`` (level>0) can't reach webui_app and must not
    trip the guard."""
    src = "from . import sibling\nfrom ..pkg import thing\n"
    assert _webui_app_offenders(ast.parse(src), "s.py") == []
