"""Codebase invariant: text-mode I/O must declare encoding= (audit cp950 cluster).

On the project's target platform (zh-TW Windows, cp950 locale) Python text I/O
without an explicit ``encoding=`` uses the locale default (cp950), not UTF-8:
- ``open(path)`` / ``Path.read_text()`` / ``Path.write_text()`` in text mode crash
  with UnicodeDecodeError (read) or produce mojibake (write) on non-ASCII UTF-8.
- ``subprocess.run/Popen/check_output(..., text=True)`` (or ``universal_newlines=
  True``) without ``encoding=`` locale-decode the child's stdout/stderr — git/gh
  output with Chinese branch names, filenames, PR titles, emoji etc. crashes.

This project has a documented history of exactly these crashes. This AST guard
scans production code and fails on any text-mode I/O missing ``encoding=`` so the
whole class cannot regress. Genuine exceptions go in ``_ALLOW`` with a reason.
"""
from __future__ import annotations

__tier__ = "unit"

import ast
from pathlib import Path

import pytest

_ROOTS = ["src/backlink_publisher", "webui_app", "webui_store"]

# (repo-relative path, 1-indexed line) pairs that are intentionally exempt.
# Keep this empty unless a site provably cannot carry non-ASCII AND cannot take
# an encoding= (document why).
_ALLOW: set[tuple[str, int]] = set()

_SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _kw(call: ast.Call, name: str) -> ast.keyword | None:
    for k in call.keywords:
        if k.arg == name:
            return k
    return None


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_os_open(func: ast.expr) -> bool:
    """True for ``os.open(...)`` — a low-level fd open (returns int, no encoding)."""
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )


def _dot_open_is_file(call: ast.Call) -> bool:
    """For ``receiver.open(...)``, decide it's a pathlib FILE open (mode arg) vs a
    non-file open like ``session.open(url)`` / ``page.open(url)``. The first arg
    of Path.open is the MODE (short string of rwaxbt+); a URL/long string is not."""
    if not call.args:
        return True  # p.open() -> default text mode "r"
    a = call.args[0]
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        s = a.value
        return len(s) <= 4 and all(c in "rwaxbt+" for c in s)
    return True  # non-constant mode (a variable) -> assume a file open


def _open_is_binary(call: ast.Call, mode_argpos: int) -> bool:
    """Return True if an open()/pathlib .open() call is binary mode (mode has 'b').

    ``mode_argpos`` is the positional index of the mode arg: 1 for builtin
    ``open(path, mode)``, 0 for ``path.open(mode)``.
    """
    mode_node: ast.expr | None = None
    m = _kw(call, "mode")
    if m is not None:
        mode_node = m.value
    elif len(call.args) > mode_argpos:
        mode_node = call.args[mode_argpos]
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return "b" in mode_node.value
    return False  # default mode "r" is text


def _violations_in(path: Path, rel: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        has_encoding = _kw(node, "encoding") is not None
        is_attr = isinstance(func, ast.Attribute)
        fname = func.attr if is_attr else (func.id if isinstance(func, ast.Name) else "")
        # encoding= may be passed positionally; check both. The signature index
        # of the encoding parameter differs per call, so pass it in.
        def _has_enc(enc_idx: int) -> bool:
            return has_encoding or len(node.args) > enc_idx
        # Builtin open(file, mode, buffering, encoding, ...) — encoding at 3, mode at 1.
        is_builtin_open = isinstance(func, ast.Name) and func.id == "open"
        # pathlib path.open(mode, buffering, encoding, ...) — encoding at 2, mode at 0.
        # Exclude urllib OpenerDirector.open(req, timeout=...): a timeout= kwarg
        # marks a network open (Path.open never takes timeout=), not file I/O.
        is_path_open = (
            is_attr and fname == "open" and _kw(node, "timeout") is None
            and not _is_os_open(func) and _dot_open_is_file(node)
        )
        if is_builtin_open and not _has_enc(3) and not _open_is_binary(node, 1):
            out.append((node.lineno, "open() text-mode without encoding="))
        elif is_path_open and not _has_enc(2) and not _open_is_binary(node, 0):
            out.append((node.lineno, "Path.open() text-mode without encoding="))
        # Path.read_text(encoding, errors) — encoding at 0.
        elif is_attr and fname == "read_text" and not _has_enc(0):
            out.append((node.lineno, "read_text() without encoding="))
        # Path.write_text(data, encoding, errors, newline) — encoding at 1.
        elif is_attr and fname == "write_text" and not _has_enc(1):
            out.append((node.lineno, "write_text() without encoding="))
        # subprocess.* text-mode (text=True kwarg is subprocess-specific).
        elif is_attr and fname in _SUBPROCESS_CALLS and not has_encoding:
            if _is_true(node.keywords and next((k.value for k in node.keywords if k.arg == "text"), None)) \
               or _is_true(next((k.value for k in node.keywords if k.arg == "universal_newlines"), None)):
                out.append((node.lineno, f"subprocess {fname}(text=True) without encoding="))
    return out


def _all_violations() -> list[str]:
    root = _repo_root()
    found: list[str] = []
    for r in _ROOTS:
        base = root / r
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(root).as_posix()
            for lineno, why in _violations_in(py, rel):
                if (rel, lineno) in _ALLOW:
                    continue
                found.append(f"{rel}:{lineno}: {why}")
    return sorted(found)


def test_no_text_mode_io_without_encoding():
    violations = _all_violations()
    assert not violations, (
        "text-mode I/O without encoding= (cp950 crash risk on zh-TW Windows). "
        "Add encoding=\"utf-8\" (reads/writes) or encoding=\"utf-8\", errors=\"replace\" "
        "(subprocess), or add to _ALLOW with a reason:\n  "
        + "\n  ".join(violations)
    )
