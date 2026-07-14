"""Permanent guard: the no-domain-to-cli import contract must list every domain package.

Audit finding [03]: import-linter's ``forbidden`` contract only checks the pairs it
enumerates in ``source_modules``. The ``.importlinter`` (the file import-linter
actually reads — the ini reader wins over pyproject.toml) omitted many existing domain
packages, so a future ``from backlink_publisher.cli…`` inside any unlisted package
would ship green, silently weakening the cli→domain→_util one-way-layering invariant.

This guard enumerates the real domain packages on disk and fails if any is absent from
the contract, so new packages can't reintroduce the blind spot.
"""

from __future__ import annotations

import configparser
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src" / "backlink_publisher"
_IMPORTLINTER = _REPO / ".importlinter"

# ``cli`` is the forbidden target itself; ``sdk`` is a documented exception (it wraps
# cli in-process and is covered by an ``ignore_imports`` wildcard). Everything else
# under the package is a domain layer that must be enumerated in the contract.
_EXCLUDED = {"cli", "sdk"}


def _domain_packages() -> set[str]:
    pkgs: set[str] = set()
    for child in _SRC.iterdir():
        if not child.is_dir() or child.name == "__pycache__":
            continue
        if not any(child.glob("*.py")):
            continue
        pkgs.add(child.name)
    return pkgs - _EXCLUDED


def _source_modules(section: str) -> set[str]:
    cp = configparser.ConfigParser()
    cp.read(_IMPORTLINTER, encoding="utf-8")
    raw = cp[section]["source_modules"]
    prefix = "backlink_publisher."
    return {
        tok[len(prefix):]
        for tok in raw.split()
        if tok.startswith(prefix) and "." not in tok[len(prefix):]
    }


def test_no_domain_to_cli_contract_covers_every_domain_package() -> None:
    listed = _source_modules("importlinter:contract:no-domain-to-cli")
    missing = sorted(_domain_packages() - listed)
    assert not missing, (
        f"Domain packages missing from the no-domain-to-cli contract in "
        f".importlinter: {missing}. A forbidden contract only checks enumerated "
        f"source_modules, so an unlisted package importing cli ships undetected — "
        f"add each of these to the contract's source_modules."
    )
