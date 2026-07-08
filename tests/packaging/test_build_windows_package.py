"""Tests for scripts/packaging/build_windows_package.py (Unit 1 stage).

Two tiers, mirroring the `real_live_publish` pattern in
tests/test_live_publish_real.py:

  * Pure-unit tests (always run, no network, no Windows requirement): exercise
    each provisioning step's logic in isolation via monkeypatching (checksum
    verification, ._pth patching, catalog-resource assertion, pip-audit
    failure handling, the pyproject.toml <-> pin drift guard).

  * Real-network/Windows integration tests (`@pytest.mark.real_packaging_build`
    + `skipif`): actually download the embeddable zip from python.org,
    bootstrap pip, install the pinned dependencies + backlink_publisher from
    PyPI, and execute the resulting `python-embed\\python.exe`. Skipped unless
    running on win32 with `BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD=1` set —
    never runs in CI (same rationale as real_live_publish: this is slow,
    needs real network, and produces a real Windows PE binary that only
    win32 can execute).
"""

from __future__ import annotations

__tier__ = "unit"

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.packaging import build_windows_package as bwp

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Pure-unit: checksum verification ────────────────────────────────────────


def test_download_and_verify_accepts_matching_checksum(tmp_path, monkeypatch):
    payload = b"pretend-embeddable-zip-bytes"
    expected = bwp.hashlib.sha256(payload).hexdigest()

    def _fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(payload)

    monkeypatch.setattr(bwp, "_http_get_to_file", _fake_download)
    dest = tmp_path / "download.bin"
    bwp._download_and_verify("https://example.invalid/f", dest, expected, label="test file")
    assert dest.read_bytes() == payload


def test_download_and_verify_rejects_mismatched_checksum(tmp_path, monkeypatch):
    def _fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(b"corrupted-or-tampered-content")

    monkeypatch.setattr(bwp, "_http_get_to_file", _fake_download)
    dest = tmp_path / "download.bin"
    with pytest.raises(bwp.BuildError, match="Checksum mismatch"):
        bwp._download_and_verify(
            "https://example.invalid/f", dest, "0" * 64, label="test file"
        )


def test_download_and_verify_wraps_network_errors(tmp_path, monkeypatch):
    def _fake_download(url: str, dest: Path) -> None:
        raise OSError("connection reset")

    monkeypatch.setattr(bwp, "_http_get_to_file", _fake_download)
    dest = tmp_path / "download.bin"
    with pytest.raises(bwp.BuildError, match="Failed to download"):
        bwp._download_and_verify(
            "https://example.invalid/f", dest, "0" * 64, label="test file"
        )


# ── Pure-unit: provision_interpreter aborts cleanly on a bad checksum ──────


def test_provision_interpreter_checksum_failure_leaves_no_half_built_dir(
    tmp_path, monkeypatch
):
    """Error path: a corrupted/mismatched embeddable-zip download must abort
    the build with a clear error and must NOT leave a half-built output_dir
    behind (core Unit 1 error-path requirement)."""

    def _fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(b"not the real embeddable zip")

    monkeypatch.setattr(bwp, "_http_get_to_file", _fake_download)
    output_dir = tmp_path / "python-embed"

    with pytest.raises(bwp.BuildError, match="Checksum mismatch"):
        bwp.provision_interpreter(output_dir, repo_root=REPO_ROOT)

    assert not output_dir.exists()


def test_provision_interpreter_checksum_failure_does_not_clobber_existing_dir(
    tmp_path, monkeypatch
):
    """If output_dir already held a previous good build, a failed rebuild
    attempt must leave that previous build untouched rather than deleting it
    before the new build has actually succeeded."""

    def _fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(b"not the real embeddable zip")

    monkeypatch.setattr(bwp, "_http_get_to_file", _fake_download)
    output_dir = tmp_path / "python-embed"
    output_dir.mkdir()
    (output_dir / "sentinel-from-previous-good-build.txt").write_text("keep me")

    with pytest.raises(bwp.BuildError, match="Checksum mismatch"):
        bwp.provision_interpreter(output_dir, repo_root=REPO_ROOT)

    assert (output_dir / "sentinel-from-previous-good-build.txt").is_file()


def test_provision_interpreter_unknown_version_aborts_before_any_download(
    tmp_path, monkeypatch
):
    """An unpinned Python version must fail fast (no hardcoded hash to trust)
    without attempting any network call."""
    called = False

    def _fake_download(url: str, dest: Path) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(bwp, "_http_get_to_file", _fake_download)
    with pytest.raises(bwp.BuildError, match="No pinned SHA-256"):
        bwp.provision_interpreter(
            tmp_path / "out", repo_root=REPO_ROOT, version="3.11.999"
        )
    assert called is False


# ── Pure-unit: ._pth patching ────────────────────────────────────────────────


_REAL_PTH_TEMPLATE = (
    "python311.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n"
)


def test_patch_pth_file_enables_site_and_adds_site_packages(tmp_path):
    embed_dir = tmp_path / "embed"
    embed_dir.mkdir()
    (embed_dir / "python311._pth").write_text(_REAL_PTH_TEMPLATE, encoding="utf-8")

    pth_path = bwp._patch_pth_file(embed_dir, "3.11.9")

    content = pth_path.read_text(encoding="utf-8")
    assert "#import site" not in content
    assert "import site" in content
    assert "Lib\\site-packages" in content


def test_patch_pth_file_missing_file_raises(tmp_path):
    embed_dir = tmp_path / "embed"
    embed_dir.mkdir()
    with pytest.raises(bwp.BuildError, match="_pth file not found"):
        bwp._patch_pth_file(embed_dir, "3.11.9")


def test_add_and_remove_build_tools_path_roundtrip(tmp_path):
    embed_dir = tmp_path / "embed"
    embed_dir.mkdir()
    pth_path = embed_dir / "python311._pth"
    pth_path.write_text(_REAL_PTH_TEMPLATE, encoding="utf-8")
    bwp._patch_pth_file(embed_dir, "3.11.9")

    build_tools_dir = tmp_path / "_build_tools"
    bwp._add_build_tools_path(pth_path, build_tools_dir)
    assert str(build_tools_dir) in pth_path.read_text(encoding="utf-8")

    bwp._remove_build_tools_path(pth_path, build_tools_dir)
    final = pth_path.read_text(encoding="utf-8")
    assert str(build_tools_dir) not in final
    # Permanent changes survive the roundtrip.
    assert "import site" in final
    assert "Lib\\site-packages" in final


# ── Pure-unit: catalog resource assertion ───────────────────────────────────


def _make_fake_catalog(root: Path, filenames: list[str]) -> Path:
    catalog_dir = root / "publishing" / "adapters" / "catalog"
    catalog_dir.mkdir(parents=True)
    for name in filenames:
        (catalog_dir / name).write_text("slug: {}\n", encoding="utf-8")
    return catalog_dir


def test_assert_catalog_resources_passes_when_all_present(tmp_path):
    src_repo = tmp_path / "repo"
    _make_fake_catalog(src_repo / "src" / "backlink_publisher", ["txtfyi.yaml"])
    site_packages = tmp_path / "site-packages"
    _make_fake_catalog(site_packages / "backlink_publisher", ["txtfyi.yaml"])

    bwp._assert_catalog_resources(site_packages, src_repo)  # must not raise


def test_assert_catalog_resources_fails_when_installed_copy_missing(tmp_path):
    src_repo = tmp_path / "repo"
    _make_fake_catalog(src_repo / "src" / "backlink_publisher", ["txtfyi.yaml"])
    site_packages = tmp_path / "site-packages"
    # Installed site-packages has NO catalog dir at all (simulates pip
    # silently dropping the resource files).
    (site_packages / "backlink_publisher").mkdir(parents=True)

    with pytest.raises(bwp.BuildError, match="Catalog resource file"):
        bwp._assert_catalog_resources(site_packages, src_repo)


def test_assert_catalog_resources_against_real_repo_source_dir(tmp_path):
    """Sanity: the real repo's catalog dir has at least one .yaml file, so
    the assertion has something real to check (guards against the check
    silently becoming a no-op if the source catalog dir is ever emptied)."""
    site_packages = tmp_path / "site-packages"
    real_catalog_dir = (
        REPO_ROOT / "src" / "backlink_publisher" / "publishing" / "adapters" / "catalog"
    )
    real_yaml_names = sorted(p.name for p in real_catalog_dir.glob("*.yaml"))
    assert real_yaml_names, "expected at least one catalog *.yaml in the real repo"
    _make_fake_catalog(site_packages / "backlink_publisher", real_yaml_names)

    bwp._assert_catalog_resources(site_packages, REPO_ROOT)  # must not raise


# ── Pure-unit: pip-audit failure handling (mocked subprocess) ──────────────


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_pip_audit_aborts_on_known_vulnerabilities(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_pip_audit_available", lambda: True)

    fake_cve_output = (
        "Found 1 known vulnerability in 1 package\n"
        "Name     Version ID             Fix Versions\n"
        "-------- ------- -------------- ------------\n"
        "requests 2.25.0  PYSEC-2023-74  2.31.0\n"
    )

    def _fake_run(cmd, **kwargs):
        assert "pip_audit" in cmd
        return _FakeCompletedProcess(returncode=1, stdout=fake_cve_output)

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)

    with pytest.raises(bwp.BuildError, match="known vulnerabilities"):
        bwp._run_pip_audit(tmp_path / "site-packages")


def test_run_pip_audit_passes_when_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_pip_audit_available", lambda: True)

    def _fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(returncode=0, stdout="No known vulnerabilities found")

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)

    bwp._run_pip_audit(tmp_path / "site-packages")  # must not raise


def test_run_pip_audit_falls_back_to_throwaway_install_when_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(bwp, "_pip_audit_available", lambda: False)
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "install" in cmd:
            return _FakeCompletedProcess(returncode=0)
        return _FakeCompletedProcess(returncode=0, stdout="No known vulnerabilities found")

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)
    bwp._run_pip_audit(tmp_path / "site-packages")

    assert len(calls) == 2
    assert "install" in calls[0]
    assert "pip_audit" in calls[1]


def test_run_pip_audit_fallback_install_failure_aborts(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_pip_audit_available", lambda: False)

    def _fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(returncode=1, stderr="could not reach PyPI")

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)

    with pytest.raises(bwp.BuildError, match="pip-audit is not importable"):
        bwp._run_pip_audit(tmp_path / "site-packages")


# ── Pure-unit: pyproject.toml <-> pin drift guard ───────────────────────────


def test_pins_cover_real_pyproject_dependencies():
    """The pins in this script must currently match the real repo's
    pyproject.toml — regression guard against future silent drift."""
    bwp._assert_pins_cover_pyproject_dependencies(REPO_ROOT)  # must not raise


def test_pins_detect_missing_pin(tmp_path):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text(
        '[project]\ndependencies = ["some-brand-new-package>=1.0"]\n',
        encoding="utf-8",
    )
    with pytest.raises(bwp.BuildError, match="Missing pins"):
        bwp._assert_pins_cover_pyproject_dependencies(fake_repo)


def test_pins_detect_stale_extra_pin(tmp_path):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    # A pyproject.toml declaring none of PINNED_DEPENDENCIES' packages makes
    # every current pin "stale" relative to it.
    (fake_repo / "pyproject.toml").write_text(
        '[project]\ndependencies = []\n', encoding="utf-8"
    )
    with pytest.raises(bwp.BuildError, match="stale pins"):
        bwp._assert_pins_cover_pyproject_dependencies(fake_repo)


def test_normalize_pkg_name_handles_underscore_and_case():
    assert bwp._normalize_pkg_name("Flask_Limiter") == "flask-limiter"
    assert bwp._normalize_pkg_name("PyYAML") == "pyyaml"


# ── Pure-unit: requirements file generation ─────────────────────────────────


def test_write_pinned_requirements_contains_all_pins(tmp_path):
    dest = tmp_path / "requirements.txt"
    bwp._write_pinned_requirements(dest)
    content = dest.read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert len(lines) == len(bwp.PINNED_DEPENDENCIES)
    for name, version in bwp.PINNED_DEPENDENCIES.items():
        assert f"{name}=={version}" in lines


# ── Pure-unit: main() CLI wrapper ───────────────────────────────────────────
#
# main() was rewritten in Unit 5 from a Unit-1-only "--output-dir" stub
# (documented in this module's own docstring as deliberately temporary) into
# the full build_package() orchestration entrypoint — see
# tests/packaging/test_build_windows_package_e2e.py for the rest of Unit 5's
# main()/build_package() coverage. These two tests now mock build_package
# directly (the function main() actually calls) rather than
# provision_interpreter (which main() no longer calls on its own).


def test_main_returns_nonzero_and_prints_error_on_build_failure(monkeypatch, capsys):
    def _fake_build_package(*, repo_root, version):
        raise bwp.BuildError("simulated failure for CLI test")

    monkeypatch.setattr(bwp, "build_package", _fake_build_package)
    exit_code = bwp.main([])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "simulated failure for CLI test" in captured.err


def test_main_returns_zero_on_success(tmp_path, monkeypatch, capsys):
    zip_path = tmp_path / "backlink-publisher-v9.9.9-win64.zip"
    zip_path.write_bytes(b"fake zip content")
    sha256_path = zip_path.with_name(zip_path.name + ".sha256")
    sha256_path.write_text(
        f"{bwp._sha256_file(zip_path)}  {zip_path.name}\n", encoding="utf-8"
    )

    def _fake_build_package(*, repo_root, version):
        return zip_path

    monkeypatch.setattr(bwp, "build_package", _fake_build_package)
    exit_code = bwp.main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Build succeeded" in captured.out
    assert str(zip_path) in captured.out


# ── Real network + Windows integration tests (opt-in, never run in CI) ─────

_REAL_ENV = "BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD"


def _real_packaging_build_enabled() -> bool:
    return os.environ.get(_REAL_ENV) == "1"


_real_skip = pytest.mark.skipif(
    sys.platform != "win32" or not _real_packaging_build_enabled(),
    reason=(
        "Real python-embed provisioning needs Windows (to execute the "
        "resulting python.exe) and real network access (downloads the "
        f"embeddable zip from python.org + ~60 packages from PyPI); set "
        f"{_REAL_ENV}=1 on such a machine to run. Never runs in CI."
    ),
)


@pytest.fixture(scope="module")
def real_provisioned_python_embed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provision ONE real python-embed/ dir, shared by the tests below so the
    slow real download + pip install (a few minutes) happens once per session.

    Only ever actually runs when the consuming test's skipif condition has
    already passed (win32 + BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD=1) —
    double-guarded here too so this fixture is inert by default even if a
    future test forgets the marker.
    """
    if sys.platform != "win32" or not _real_packaging_build_enabled():
        pytest.skip("real packaging build not enabled — see _real_skip reason")

    try:
        from pytest_socket import enable_socket

        enable_socket()
    except ImportError:
        pass

    output_dir = tmp_path_factory.mktemp("real-python-embed") / "python-embed"
    bwp.provision_interpreter(output_dir, repo_root=REPO_ROOT)
    return output_dir


@pytest.mark.real_packaging_build
@_real_skip
def test_real_provision_imports_succeed(real_provisioned_python_embed: Path) -> None:
    python_exe = real_provisioned_python_embed / "python.exe"
    result = subprocess.run(
        [str(python_exe), "-c", "import backlink_publisher, flask, waitress"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.real_packaging_build
@_real_skip
def test_real_provision_catalog_yaml_present(real_provisioned_python_embed: Path) -> None:
    catalog_dir = (
        real_provisioned_python_embed
        / "Lib"
        / "site-packages"
        / "backlink_publisher"
        / "publishing"
        / "adapters"
        / "catalog"
    )
    assert (catalog_dir / "txtfyi.yaml").is_file()


@pytest.mark.real_packaging_build
@_real_skip
def test_real_provision_pip_not_shipped(real_provisioned_python_embed: Path) -> None:
    """get-pip.py bootstrap must be build-time only — pip/setuptools/wheel
    must not end up inside the shipped Lib/site-packages."""
    site_packages = real_provisioned_python_embed / "Lib" / "site-packages"
    shipped_names = {p.name.split("-")[0].lower() for p in site_packages.iterdir()}
    assert "pip" not in shipped_names


@pytest.mark.real_packaging_build
@_real_skip
def test_real_provision_portable_after_move(
    real_provisioned_python_embed: Path, tmp_path: Path
) -> None:
    """Core Unit 1 / R4 property: move the whole tree to a different path and
    confirm imports still work — direct proof of the venv-was-not-portable
    bug this plan exists to fix."""
    moved = tmp_path / "moved-to-a-different-path" / "python-embed"
    shutil.copytree(real_provisioned_python_embed, moved)
    python_exe = moved / "python.exe"
    result = subprocess.run(
        [str(python_exe), "-c", "import backlink_publisher"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
