#!/usr/bin/env python3
"""Scan src/backlink_publisher/ for orphan .py files with no import references."""

import os
import re
import sys

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
PKG = os.path.join(SRC, "backlink_publisher")
TESTS = os.path.join(os.path.dirname(__file__), "..", "tests")
PYPROJECT = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")


def _get_module_path(file_path: str) -> str:
    rel = os.path.relpath(file_path, PKG)
    if rel.endswith(".py"):
        rel = rel[:-3]
    return "backlink_publisher." + rel.replace(os.sep, ".")


def _get_entry_point_modules() -> set[str]:
    modules: set[str] = set()
    try:
        with open(PYPROJECT) as f:
            content = f.read()
    except FileNotFoundError:
        return modules
    in_scripts = False
    for line in content.splitlines():
        if line.strip() == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts:
            if line.startswith("["):
                break
            m = re.match(r'\s*[\w-]+\s*=\s*"([^"]+)"', line)
            if m:
                mod = m.group(1).rsplit(":", 1)[0]
                modules.add(mod)
    return modules


def _collect_all_py_files(root: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".py") and fn != "py.typed":
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                files[rel] = full
    return files


def _file_is_imported(module: str, stem: str,
                      search_roots: list[str],
                      self_path: str) -> bool:
    parts = module.split(".")
    parent_module = ".".join(parts[:-1]) if len(parts) > 1 else ""
    patterns = [
        f"import {module}",
        f"from {module} import",
        re.compile(rf"from\s+\.+(?:\w+\.)*{re.escape(stem)}\b"),
        re.compile(rf"from\s+\.+\s+import\s+{re.escape(stem)}\b"),
        re.compile(rf"from\s+\.+\S+\s+import\s+{re.escape(stem)}\b"),
    ]
    if parent_module:
        patterns.append(f"from {parent_module} import {stem}")
    for root in search_roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                if os.path.samefile(full, self_path):
                    continue
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue
                for p in patterns:
                    if isinstance(p, re.Pattern):
                        if p.search(content):
                            return True
                    elif p in content:
                        return True
    return False


def scan() -> list[str]:
    entry_points = _get_entry_point_modules()
    all_files = _collect_all_py_files(PKG)
    search_roots = [SRC, TESTS]

    orphans: list[str] = []
    for rel_path, full_path in sorted(all_files.items()):
        base = os.path.basename(rel_path)
        if base == "__init__.py" or base == "conftest.py" or base.startswith("test_"):
            continue
        module = _get_module_path(full_path)
        if module in entry_points:
            continue
        stem = os.path.splitext(base)[0]
        if not _file_is_imported(module, stem, search_roots, full_path):
            orphans.append(rel_path)
    return orphans


if __name__ == "__main__":
    orphans = scan()
    for o in orphans:
        print(o)
    if orphans:
        print(f"\nFound {len(orphans)} orphan file(s)", file=sys.stderr)
        sys.exit(1)
