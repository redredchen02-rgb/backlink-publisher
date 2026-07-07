"""Windows portable-package builder.

Produces a fully self-contained, relocatable ``python-embed/`` directory (an
official Python embeddable interpreter with ``backlink_publisher`` and its
core runtime dependencies installed) that does NOT depend on any host Python
installation. This is the build-time tool referenced by
``docs/plans/2026-07-07-006-feat-windows-portable-package-plan.md``.

Currently implements Unit 1 only: interpreter provisioning
(``provision_interpreter``). Units 2-5 (CLI shim generation, SPA build +
directory assembly, documentation, and full build orchestration / zip output)
extend this same file — the CLI entrypoint below is deliberately minimal
until Unit 5 adds the full ``dist/backlink-publisher-vX.Y.Z-win64.zip``
pipeline on top of it.

Why an official *embeddable* interpreter rather than a copied ``venv/``: see
"已驗證的關鍵發現" in the plan — a regular ``venv`` created by ``uv`` (or any
tool) records the build machine's base-Python path in ``pyvenv.cfg`` and
cannot be moved to a machine that never had that exact Python installed. The
embeddable zip from python.org is explicitly designed to be redistributed
standalone.

Usage (Unit 1 stage only, for now)::

    python scripts/packaging/build_windows_package.py --output-dir dist/_python-embed-build

Run via the project's own Python (any interpreter satisfying
``requires-python = ">=3.11"`` — this script itself does not need to run
under the embeddable interpreter it produces).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Pinned Python embeddable interpreter ────────────────────────────────────
#
# Picked to satisfy `requires-python = ">=3.11"` in pyproject.toml while
# pinning an exact, verified patch version (avoids wheel-compatibility drift
# across 3.11.x point releases).
PYTHON_VERSION = "3.11.9"

# SHA-256 of python-<version>-embed-amd64.zip, keyed by version. Cross-checked
# 2026-07-07: python.org's release pages (e.g.
# https://www.python.org/downloads/release/python-3119/) only publish an MD5
# for the "Windows embeddable package (64-bit)" file, not a SHA-256 — so this
# hash was produced by downloading the file over TLS directly from
# python.org/ftp/python/, confirming its MD5 (6d9aa08531d48fcc261ba667e2df17c4)
# matched python.org's own published MD5 for that release exactly, and only
# then computing/hardcoding the SHA-256 below. To add a new patch version:
# repeat that same cross-check (do not copy a hash from an unverified
# third-party mirror or blog post) and add an entry here.
PYTHON_EMBED_SHA256_BY_VERSION: dict[str, str] = {
    "3.11.9": "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b",
}

# ── get-pip.py bootstrap ─────────────────────────────────────────────────────
#
# Build-time only: used once to install `pip` into a throwaway directory so it
# can install the pinned dependencies + backlink_publisher into
# python-embed/Lib/site-packages, then discarded — pip itself is never copied
# into the shipped python-embed/ tree (see _bootstrap_pip / provision_interpreter).
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
# SHA-256 of get-pip.py as fetched from bootstrap.pypa.io on 2026-07-07.
# UNLIKE the versioned embeddable zip above, this URL serves the SAME path
# with content that changes whenever pip cuts a new release — this hash WILL
# go stale and need periodic refreshing (download, sanity-check the diff
# against https://github.com/pypa/get-pip's history, then update this
# constant). A mismatch here is expected background noise, not necessarily an
# attack, but the build must still abort rather than silently execute an
# unverified script with build-machine privileges.
GET_PIP_SHA256 = "a341e1a43e38001c551a1508a73ff23636a11970b61d901d9a1cad2a18f57055"

# ── Pinned core dependency versions ─────────────────────────────────────────
#
# Exact versions for THIS packaging build only — resolved 2026-07-07 against
# the open ranges in pyproject.toml's [project.dependencies] (`pip install`
# against those ranges, then read back the versions pip's resolver picked),
# and confirmed clean via `pip-audit --path` against the resolved set before
# being hardcoded here. pyproject.toml itself keeps open ranges for normal
# development installs; this dict exists so the *packaged* build is
# reproducible and doesn't drift silently as PyPI uploads new releases over
# time (see plan "建置期供應鏈完整性防護"). Re-resolve and re-audit whenever
# pyproject.toml's ranges change (see _assert_pins_cover_pyproject_dependencies,
# which fails the build loudly on drift) or when a fresh CVE sweep is wanted.
#
# NOTE: only these 16 direct dependencies are pinned — their own transitive
# dependencies are left to pip's normal resolver at build time (still gated by
# the post-install pip-audit check). This means two builds run on different
# days are not guaranteed byte-identical if a transitive package publishes a
# new compatible release in between; closing that gap would require a full
# transitive lockfile, which is out of scope for what Unit 1 asked for.
PINNED_DEPENDENCIES: dict[str, str] = {
    "markdown-it-py": "4.2.0",
    "google-api-python-client": "2.198.0",
    "google-auth-oauthlib": "1.4.0",
    "google-auth-httplib2": "0.4.0",
    "requests": "2.34.2",
    "websocket-client": "1.9.0",
    "beautifulsoup4": "4.15.0",
    "flask": "3.1.3",
    "flask-limiter": "4.1.1",
    "apscheduler": "3.11.3",
    "apiflask": "3.1.1",
    "pydantic": "2.13.4",
    "pyyaml": "6.0.3",
    "structlog": "26.1.0",
    "flask-compress": "1.24",
    "waitress": "3.0.2",
}


class BuildError(RuntimeError):
    """Raised for any provisioning failure; callers should abort with a non-zero exit."""


# ── Download + checksum verification ────────────────────────────────────────


def _embed_zip_url(version: str) -> str:
    return f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _http_get_to_file(url: str, dest: Path) -> None:
    """Thin wrapper around urlretrieve — isolated so tests can monkeypatch it
    without touching the real network (e.g. to simulate a corrupted download
    for the checksum-mismatch error path)."""
    urllib.request.urlretrieve(url, dest)  # noqa: S310 (fixed https:// URLs only)


def _download_and_verify(url: str, dest: Path, expected_sha256: str, *, label: str) -> None:
    try:
        _http_get_to_file(url, dest)
    except (OSError, urllib.error.URLError) as exc:
        raise BuildError(f"Failed to download {label} from {url}: {exc}") from exc
    if not dest.is_file():
        raise BuildError(f"Download of {label} from {url} did not produce a file at {dest}")
    actual_sha256 = _sha256_file(dest)
    if actual_sha256 != expected_sha256:
        raise BuildError(
            f"Checksum mismatch for {label} downloaded from {url}: "
            f"expected sha256={expected_sha256}, got sha256={actual_sha256}. "
            f"Aborting build — refusing to use an unverified {label}."
        )


# ── ._pth patching ───────────────────────────────────────────────────────────


def _pth_filename(version: str) -> str:
    major, minor = version.split(".")[:2]
    return f"python{major}{minor}._pth"


def _patch_pth_file(embed_dir: Path, version: str) -> Path:
    """Permanently enable ``site`` + ``Lib\\site-packages`` in the embeddable
    interpreter's ``._pth`` file.

    The official embeddable zip ships with ``import site`` commented out —
    this disables ``site.main()`` and, with it, pip / site-packages support
    entirely (a documented embeddable-package limitation; see cpython#102169).
    Without this patch nothing installed under ``Lib\\site-packages`` would
    ever be importable.
    """
    pth_path = embed_dir / _pth_filename(version)
    if not pth_path.exists():
        raise BuildError(
            f"Expected _pth file not found at {pth_path} — the embeddable zip "
            f"layout may have changed for Python {version}."
        )
    original = pth_path.read_text(encoding="utf-8")
    patched = original.replace("#import site", "import site")
    if "import site" not in patched:
        # Defensive: some future embeddable zip might not ship the commented
        # line verbatim. Don't silently no-op — make sure site gets enabled.
        patched = patched.rstrip("\n") + "\nimport site\n"
    if "Lib\\site-packages" not in patched:
        lines = patched.splitlines()
        insert_at = 1 if len(lines) > 1 else len(lines)
        lines.insert(insert_at, "Lib\\site-packages")
        patched = "\n".join(lines) + "\n"
    pth_path.write_text(patched, encoding="utf-8")
    return pth_path


def _add_build_tools_path(pth_path: Path, build_tools_dir: Path) -> None:
    """Temporarily add an absolute path entry so the embeddable interpreter
    can see a pip installed OUTSIDE Lib\\site-packages during the build.

    Kept out of Lib\\site-packages entirely (rather than bootstrapping pip
    there and stripping it afterwards) so pip/setuptools/wheel and their
    console-script shims never touch the directory that gets shipped —
    matches the plan's "get-pip.py 僅建置期使用，不隨封裝出貨" requirement
    without relying on an after-the-fact deletion step that could miss files
    or (worse) delete something a runtime dependency actually needs (e.g. a
    package that does `import pkg_resources` from setuptools).
    """
    content = pth_path.read_text(encoding="utf-8")
    content = content.rstrip("\n") + f"\n{build_tools_dir}\n"
    pth_path.write_text(content, encoding="utf-8")


def _remove_build_tools_path(pth_path: Path, build_tools_dir: Path) -> None:
    """Undo `_add_build_tools_path` before the interpreter ships."""
    lines = pth_path.read_text(encoding="utf-8").splitlines()
    filtered = [line for line in lines if line.strip() != str(build_tools_dir)]
    pth_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")


# ── pip bootstrap + installs ─────────────────────────────────────────────────


def _bootstrap_pip(python_exe: Path, get_pip_path: Path, build_tools_dir: Path) -> None:
    build_tools_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(python_exe),
        str(get_pip_path),
        "--target",
        str(build_tools_dir),
        "--no-warn-script-location",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise BuildError(
            f"get-pip.py bootstrap failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def _run_embedded_pip(python_exe: Path, pip_args: list[str], *, step_label: str) -> None:
    cmd = [str(python_exe), "-m", "pip", *pip_args]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise BuildError(
            f"{step_label} failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def _write_pinned_requirements(dest: Path) -> Path:
    lines = [f"{name}=={version}" for name, version in sorted(PINNED_DEPENDENCIES.items())]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


# ── pyproject.toml <-> pin drift guard ───────────────────────────────────────


def _normalize_pkg_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _parse_pyproject_dependency_names(repo_root: Path) -> set[str]:
    pyproject_path = repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    names: set[str] = set()
    for spec in deps:
        name = re.split(r"[<>=!~\[\s;]", spec, maxsplit=1)[0]
        names.add(_normalize_pkg_name(name))
    return names


def _assert_pins_cover_pyproject_dependencies(repo_root: Path) -> None:
    """Fail loudly if PINNED_DEPENDENCIES has drifted from pyproject.toml.

    Guards against exactly the failure mode the pinning exists to prevent:
    someone bumps/adds/removes a dependency in [project.dependencies] without
    updating (and re-auditing) the exact pin here, silently shipping an
    unpinned or stale package in the portable build.
    """
    declared = _parse_pyproject_dependency_names(repo_root)
    pinned = {_normalize_pkg_name(name) for name in PINNED_DEPENDENCIES}
    missing = sorted(declared - pinned)
    extra = sorted(pinned - declared)
    if missing or extra:
        raise BuildError(
            "PINNED_DEPENDENCIES in build_windows_package.py has drifted from "
            f"pyproject.toml [project.dependencies]. Missing pins: {missing or 'none'}; "
            f"stale pins no longer in pyproject.toml: {extra or 'none'}. "
            "Resolve + pin the affected package(s), re-run pip-audit against "
            "the resolved set, and update PINNED_DEPENDENCIES before building."
        )


# ── Catalog resource assertion ───────────────────────────────────────────────


def _assert_catalog_resources(site_packages: Path, repo_root: Path) -> None:
    """Abort the build if the catalog adapter's *.yaml resource files were
    silently dropped by `pip install --target` (see pyproject.toml's
    [tool.setuptools.package-data] declaration this guards)."""
    src_catalog_dir = (
        repo_root / "src" / "backlink_publisher" / "publishing" / "adapters" / "catalog"
    )
    expected = sorted(p.name for p in src_catalog_dir.glob("*.yaml"))
    expected += sorted(p.name for p in src_catalog_dir.glob("*.yml"))
    if not expected:
        raise BuildError(
            f"No catalog *.yaml/*.yml files found under {src_catalog_dir} to "
            f"verify against — check the repo layout before trusting this check."
        )
    installed_catalog_dir = (
        site_packages / "backlink_publisher" / "publishing" / "adapters" / "catalog"
    )
    missing = [name for name in expected if not (installed_catalog_dir / name).is_file()]
    if missing:
        raise BuildError(
            f"Catalog resource file(s) missing from installed site-packages "
            f"({installed_catalog_dir}): {missing}. pip silently drops non-.py "
            f"package data without an explicit declaration — check "
            f"[tool.setuptools.package-data] in pyproject.toml."
        )


# ── pip-audit ─────────────────────────────────────────────────────────────────


def _pip_audit_available() -> bool:
    """True if `pip_audit` is importable in the interpreter running this script."""
    return importlib.util.find_spec("pip_audit") is not None


def _run_pip_audit(site_packages: Path) -> None:
    """Run pip-audit against the provisioned site-packages dir and abort the
    build on any known vulnerability (or any failure to run the audit at all).

    Uses `--path <dir>` (confirmed via manual testing to restrict pip-audit's
    scan to that directory rather than the running environment) so it can
    audit an arbitrary target directory without needing python-embed itself
    to have pip-audit installed. Prefers the pip-audit already importable in
    the current interpreter (i.e. the operator's own `.[dev]` install); falls
    back to installing pip-audit into a throwaway directory (never touching
    the shipped site-packages) if it isn't available.
    """
    if _pip_audit_available():
        cmd = [sys.executable, "-m", "pip_audit", "--path", str(site_packages)]
        env = None
    else:
        tool_dir = Path(tempfile.mkdtemp(prefix="bp-pip-audit-tool-"))
        install_cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(tool_dir),
            "pip-audit",
        ]
        install_result = subprocess.run(install_cmd, capture_output=True, text=True, encoding="utf-8")
        if install_result.returncode != 0:
            raise BuildError(
                "pip-audit is not importable in the current interpreter and "
                f"the fallback install into a throwaway directory failed "
                f"(exit {install_result.returncode}):\n"
                f"--- stdout ---\n{install_result.stdout}\n--- stderr ---\n{install_result.stderr}"
            )
        cmd = [sys.executable, "-m", "pip_audit", "--path", str(site_packages)]
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(tool_dir) + (os.pathsep + existing if existing else "")

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    if result.returncode != 0:
        raise BuildError(
            "pip-audit found known vulnerabilities (or failed to run) against "
            "the provisioned site-packages — aborting build rather than "
            "shipping a package with a known CVE.\n"
            f"--- pip-audit stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


# ── Orchestration ─────────────────────────────────────────────────────────────


def provision_interpreter(
    output_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    version: str = PYTHON_VERSION,
) -> Path:
    """Provision a relocatable ``python-embed/`` directory at ``output_dir``.

    Contains the official Python embeddable interpreter for ``version`` with
    ``backlink_publisher`` and its pinned core dependencies installed
    (non-editable) into ``Lib\\site-packages`` — importable with zero
    dependency on any host Python installation, and safe to move to any other
    path or machine afterwards (see the plan's R4).

    All work happens in a scratch temp directory; ``output_dir`` is only
    touched (replaced, if it already exists) once every step — download
    verification, dependency install, catalog-resource assertion, and
    pip-audit — has succeeded. Any failure along the way leaves ``output_dir``
    exactly as it was found (untouched, not half-built) and raises
    ``BuildError`` with a message identifying which step failed.
    """
    output_dir = Path(output_dir)
    repo_root = Path(repo_root)

    _assert_pins_cover_pyproject_dependencies(repo_root)

    embed_sha256 = PYTHON_EMBED_SHA256_BY_VERSION.get(version)
    if embed_sha256 is None:
        raise BuildError(
            f"No pinned SHA-256 known for Python {version} embeddable zip. "
            f"Known versions: {sorted(PYTHON_EMBED_SHA256_BY_VERSION)}. Download "
            f"and verify the new version's hash yourself (see the comment above "
            f"PYTHON_EMBED_SHA256_BY_VERSION) before adding it."
        )

    with tempfile.TemporaryDirectory(prefix="bp-python-embed-build-") as tmp_str:
        tmp = Path(tmp_str)
        downloads_dir = tmp / "downloads"
        staging_dir = tmp / "python-embed"
        build_tools_dir = tmp / "_build_tools"
        downloads_dir.mkdir()

        embed_zip = downloads_dir / f"python-{version}-embed-amd64.zip"
        _download_and_verify(
            _embed_zip_url(version), embed_zip, embed_sha256, label="python embeddable zip"
        )

        staging_dir.mkdir()
        with zipfile.ZipFile(embed_zip) as zf:
            zf.extractall(staging_dir)

        python_exe = staging_dir / "python.exe"
        if not python_exe.is_file():
            raise BuildError(
                f"Expected python.exe not found at {python_exe} after extracting "
                f"the embeddable zip — archive layout may have changed."
            )

        pth_path = _patch_pth_file(staging_dir, version)

        get_pip_path = downloads_dir / "get-pip.py"
        _download_and_verify(GET_PIP_URL, get_pip_path, GET_PIP_SHA256, label="get-pip.py")

        _add_build_tools_path(pth_path, build_tools_dir)
        _bootstrap_pip(python_exe, get_pip_path, build_tools_dir)

        site_packages = staging_dir / "Lib" / "site-packages"
        requirements_file = downloads_dir / "pinned-requirements.txt"
        _write_pinned_requirements(requirements_file)

        _run_embedded_pip(
            python_exe,
            [
                "install",
                "--no-cache-dir",
                "--ignore-installed",
                "--target",
                str(site_packages),
                "-r",
                str(requirements_file),
            ],
            step_label="pinned core dependency install",
        )
        _run_embedded_pip(
            python_exe,
            [
                "install",
                "--no-cache-dir",
                "--ignore-installed",
                "--no-deps",
                "--target",
                str(site_packages),
                str(repo_root),
            ],
            step_label="backlink_publisher install",
        )

        _assert_catalog_resources(site_packages, repo_root)

        # pip/setuptools/wheel were bootstrapped OUTSIDE Lib\site-packages
        # (build_tools_dir) and were never copied in, so there is nothing to
        # strip from site_packages — just remove the temporary pth entry that
        # pointed at build_tools_dir so the shipped ._pth has no reference to
        # a path that only existed on the build machine.
        _remove_build_tools_path(pth_path, build_tools_dir)

        _run_pip_audit(site_packages)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_dir), str(output_dir))

    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Provision a portable python-embed/ interpreter with "
            "backlink_publisher + core dependencies installed (Unit 1 stage). "
            "Full build orchestration (CLI shims, SPA assembly, docs, zip "
            "output) is added on top of this by later units."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "dist" / "_python-embed-build" / "python-embed",
        help="Destination for the provisioned python-embed/ directory.",
    )
    parser.add_argument(
        "--version",
        default=PYTHON_VERSION,
        help="Pinned Python 3.11.x patch version to provision.",
    )
    args = parser.parse_args(argv)

    try:
        result_dir = provision_interpreter(args.output_dir, version=args.version)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"python-embed provisioned at: {result_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
