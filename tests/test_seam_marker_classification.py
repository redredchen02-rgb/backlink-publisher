"""Self-test for the C1a seam-marker auto-classification.

Plan 2026-06-30-001 Unit C1a. Proves the ``pytest.mark.seam`` auto-
classification in ``tests/conftest.py`` (``_module_imports_seam`` /
``_path_has_seam_import``) actually fires for a test module that directly
imports one of the seam module families, does NOT fire for a module that
doesn't, and correctly honors the one-time coincidental-import exclusion
list. Mirrors the self-verifying-gate pattern of
``test_no_monolith_regrowth.py`` / ``test_no_raw_home_path_primitives.py``.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

# This file itself directly imports a seam-module family
# (backlink_publisher.events) purely to serve as the "genuine, live" canary
# case below — this is the exact scenario the C1a plan's verification step
# asks for: "a test file that imports one of the 5 seam module families but
# declares nothing else special" gets auto-classified into seam. Proves the
# mechanism end-to-end inside the real collection run, not just via a direct
# unit test of the helper function.
from backlink_publisher.events import kinds as _seam_canary_import  # noqa: F401
import pytest

from conftest import (  # type: ignore[import]
    _SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS,
    _SEAM_IMPORT_PREFIXES,
    _SEAM_REPO_ROOT,
    _module_imports_seam,
)


def test_this_module_is_auto_marked_seam(request: pytest.FixtureRequest) -> None:
    """Live canary: this file imports a seam module -> pytest.mark.seam fires."""
    assert request.node.get_closest_marker("seam") is not None, (
        "This test module imports backlink_publisher.events.kinds directly "
        "but was not auto-marked pytest.mark.seam — the C1a import-based "
        "classifier in conftest.py regressed."
    )


class _FakeModule:
    """Minimal stand-in exposing only the ``__file__`` attribute the classifier reads."""

    def __init__(self, file: Path) -> None:
        self.__file__ = str(file)


def test_module_with_seam_import_is_classified_seam(tmp_path: Path) -> None:
    seam_file = tmp_path / "test_synthetic_seam_import.py"
    seam_file.write_text(
        "from backlink_publisher.gap.engine import compute_gap\n",
        encoding="utf-8",
    )
    assert _module_imports_seam(_FakeModule(seam_file)) is True


def test_module_without_seam_import_is_not_classified_seam(tmp_path: Path) -> None:
    plain_file = tmp_path / "test_synthetic_plain.py"
    plain_file.write_text(
        "import json\n\n\ndef test_noop():\n    assert json.dumps({}) == '{}'\n",
        encoding="utf-8",
    )
    assert _module_imports_seam(_FakeModule(plain_file)) is False


def test_module_touching_all_five_families_is_classified_seam(tmp_path: Path) -> None:
    """Sanity sweep: each of the five documented families independently triggers seam."""
    samples = {
        "events": "import backlink_publisher.events\n",
        "gap": "from backlink_publisher.gap import engine\n",
        "idempotency": "import backlink_publisher.idempotency.store\n",
        "ledger": "from backlink_publisher.ledger import model\n",
        "webui_app.api": "import webui_app.api.pipeline_api\n",
    }
    for name, source in samples.items():
        f = tmp_path / f"test_synthetic_{name.replace('.', '_')}.py"
        f.write_text(source, encoding="utf-8")
        assert _module_imports_seam(_FakeModule(f)) is True, (
            f"family {name!r} sample source {source!r} was not classified seam"
        )


def test_coincidental_import_exclusion_overrides_genuine_import() -> None:
    """A file with a real seam import but a matching exclusion entry is NOT seam.

    Proves the exclusion list (C1a action 2's one-time manual classification
    pass) actually takes effect, using the real excluded file on disk so the
    classifier's repo-relative-path match fires exactly as it would in a
    live collection run.
    """
    excluded_relpath = next(iter(_SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS))
    real_file = _SEAM_REPO_ROOT / excluded_relpath
    assert real_file.exists(), (
        f"Exclusion-list entry {excluded_relpath!r} no longer exists on disk; "
        "update _SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS in conftest.py."
    )
    assert _module_imports_seam(_FakeModule(real_file)) is False


# Code-review finding, 2026-07-02: the exclusion list's own docstring says
# "shrink-only", but nothing enforced that — a new entry could be added with
# a weak/self-attested justification and no test would ever flag it. Pinning
# the exact size means any addition requires deliberately lowering (never
# just matching) this constant, forcing the PR to justify growth explicitly
# rather than let the frozenset grow silently.
_EXPECTED_COINCIDENTAL_EXCLUSION_COUNT = 1


def test_coincidental_import_exclusions_size_is_pinned() -> None:
    assert len(_SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS) == _EXPECTED_COINCIDENTAL_EXCLUSION_COUNT, (
        f"_SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS has "
        f"{len(_SEAM_COINCIDENTAL_IMPORT_EXCLUSIONS)} entries, expected "
        f"{_EXPECTED_COINCIDENTAL_EXCLUSION_COUNT}. Adding an entry requires "
        "raising this constant in the same change and explaining, in the new "
        "entry's own comment, why the import genuinely never touches seam "
        "runtime behavior (per the frozenset's own docstring contract)."
    )


def test_seam_import_prefixes_cover_the_five_documented_families() -> None:
    """Ratchet: the five module families named in the C1a plan text stay covered."""
    expected_families = {"events", "gap", "idempotency", "ledger", "webui_app.api"}
    covered = set()
    for prefix in _SEAM_IMPORT_PREFIXES:
        if prefix.startswith("backlink_publisher."):
            covered.add(prefix.removeprefix("backlink_publisher."))
        else:
            covered.add(prefix)
    assert covered == expected_families
