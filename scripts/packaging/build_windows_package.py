"""Windows portable-package builder.

Produces a fully self-contained, relocatable ``python-embed/`` directory (an
official Python embeddable interpreter with ``backlink_publisher`` and its
core runtime dependencies installed) that does NOT depend on any host Python
installation. This is the build-time tool referenced by
``docs/plans/2026-07-07-006-feat-windows-portable-package-plan.md``.

Implements Unit 1 (interpreter provisioning, ``provision_interpreter``),
Unit 2 (CLI shim generation, ``generate_cli_shims``), Unit 3 (SPA build +
package assembly, ``assemble_package``), and Unit 5 (full build
orchestration + zip/checksum output, ``build_package``, wired up as the
``main()`` CLI entrypoint at the bottom of this file). Unit 4's doc/script
templates live under ``scripts/packaging/templates/`` and are copied in by
Unit 5's ``copy_docs``/``copy_launch_scripts``/``copy_helper_scripts``.

Note on ``webui.py`` vs ``serve.py``: the plan's original Output Structure
text names ``webui.py`` as the WebUI entrypoint copied into ``app/``. Since
that text was written, ``serve.py`` landed on ``main`` as the intended
production entrypoint (wraps the same Flask ``app`` in ``waitress`` instead
of Werkzeug's dev server). ``assemble_package`` copies BOTH into ``app/`` —
``serve.py`` does ``from webui import app``, so ``webui.py`` must still be
present alongside it.

Why an official *embeddable* interpreter rather than a copied ``venv/``: see
"已驗證的關鍵發現" in the plan — a regular ``venv`` created by ``uv`` (or any
tool) records the build machine's base-Python path in ``pyvenv.cfg`` and
cannot be moved to a machine that never had that exact Python installed. The
embeddable zip from python.org is explicitly designed to be redistributed
standalone.

Usage (full build)::

    python scripts/packaging/build_windows_package.py [--version X.Y.Z]

``--version`` is optional and overrides the package version used to name
the output directory/zip; it defaults to ``[project].version`` in
``pyproject.toml`` (see ``package_dir_name``).

Run via the project's own Python (any interpreter satisfying
``requires-python = ">=3.11"`` — this script itself does not need to run
under the embeddable interpreter it produces).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
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


# Network-touching steps (download, pip install, pip-audit, npm) get a
# generous but finite timeout so a stalled connection produces a clear
# BuildError instead of hanging the build indefinitely with no diagnostic.
_NETWORK_TIMEOUT_S = 300

# Purely local, no-network subprocess calls (e.g. the CLI-shim existence
# check) don't need the network-scale allowance but should still have some
# bound rather than none.
_LOCAL_SUBPROCESS_TIMEOUT_S = 60


def _utf8_child_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of *base_env* (or `os.environ` if `None`) with
    `PYTHONIOENCODING` forced to `"utf-8"`.

    A local copy of `backlink_publisher._util.subprocess_env.utf8_child_env`
    (same fix, same rationale) rather than an import of it: this build
    script is intentionally stdlib-only so a maintainer can run it with
    nothing but `python scripts/packaging/build_windows_package.py`, without
    first needing `PYTHONPATH=src` or an editable install of the package it
    is packaging. On Windows, a Python child process whose stdout/stderr is
    a pipe (not a real console) falls back to the system ANSI codepage for
    its own text I/O unless `PYTHONIOENCODING` forces otherwise — the same
    bug class fixed for the runtime app in
    docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md.
    """
    env = dict(base_env) if base_env is not None else os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _rmtree_long_path_safe(path: Path, *, retries: int = 5, retry_delay_s: float = 1.0) -> None:
    """`shutil.rmtree` wrapper that tolerates Windows' classic 260-character
    `MAX_PATH` limit AND transiently locked files, with retry/backoff.

    Discovered during Unit 5's real end-to-end testing: this build's own
    `python-embed/Lib/site-packages/.../__pycache__/*.pyc` paths are deeply
    nested (package name + submodule path + compiled-cache suffix), and
    combined with a sufficiently long repo checkout path (e.g. this repo's
    own `.worktrees/<branch>/` layout), the full path can exceed 260
    characters. Plain `shutil.rmtree` then fails with
    `FileNotFoundError: [WinError 3]` (`ERROR_PATH_NOT_FOUND`) even though
    the file is right there, because the classic (non-extended) Win32 path
    APIs silently refuse anything longer than `MAX_PATH`.

    Prefixing an absolute Windows path with `\\\\?\\` opts into the
    "extended-length path" API, which supports paths up to ~32,767
    characters regardless of the system's `LongPathsEnabled` registry
    setting — scoped to just this call, so it needs no elevated/
    administrator access (unlike enabling long paths system-wide).

    Also retries on `PermissionError` (`WinError 32`,
    `ERROR_SHARING_VIOLATION`) with a short backoff: directly observed
    during this feature's own development that a `.pyc` file under
    `__pycache__` can still be held open momentarily by a just-killed
    Python process, an antivirus real-time scanner, or the Windows Search
    indexer, causing a spurious rmtree failure on an otherwise-legitimate
    idempotent rebuild. Previously this had to be worked around manually by
    the operator; a bounded retry closes that gap in the shipped code.
    """
    path = Path(path)
    if sys.platform == "win32":
        resolved = str(path.resolve())
        target = resolved if resolved.startswith("\\\\?\\") else f"\\\\?\\{resolved}"
    else:
        target = str(path)
    last_exc: PermissionError | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(target)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(retry_delay_s)
    raise BuildError(
        f"Could not remove {path} after {retries} attempts — a file inside it "
        f"is still locked by another process (antivirus scanner, search "
        f"indexer, or a not-yet-exited prior build). Close any process that "
        f"might be holding it open and re-run the build."
    ) from last_exc


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
    """Thin wrapper around urlopen — isolated so tests can monkeypatch it
    without touching the real network (e.g. to simulate a corrupted download
    for the checksum-mismatch error path).

    Uses `urlopen(..., timeout=...)` rather than `urlretrieve` (which has no
    timeout parameter at all) so a stalled connection raises promptly
    instead of hanging the build indefinitely.
    """
    with (
        urllib.request.urlopen(url, timeout=_NETWORK_TIMEOUT_S) as response,  # noqa: S310 (fixed https:// URLs only)
        open(dest, "wb") as fh,
    ):
        shutil.copyfileobj(response, fh)


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
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_utf8_child_env(),
        timeout=_NETWORK_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise BuildError(
            f"get-pip.py bootstrap failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def _run_embedded_pip(python_exe: Path, pip_args: list[str], *, step_label: str) -> None:
    cmd = [str(python_exe), "-m", "pip", *pip_args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_utf8_child_env(),
        timeout=_NETWORK_TIMEOUT_S,
    )
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
        _run_pip_audit_cmd(cmd, env=_utf8_child_env())
        return

    # Fallback install goes into a TemporaryDirectory (not a bare
    # tempfile.mkdtemp(), which was never cleaned up) so every build run
    # that hits this path doesn't leak a directory into the OS temp dir.
    with tempfile.TemporaryDirectory(prefix="bp-pip-audit-tool-") as tool_dir_str:
        tool_dir = Path(tool_dir_str)
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
        install_result = subprocess.run(
            install_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_utf8_child_env(),
            timeout=_NETWORK_TIMEOUT_S,
        )
        if install_result.returncode != 0:
            raise BuildError(
                "pip-audit is not importable in the current interpreter and "
                f"the fallback install into a throwaway directory failed "
                f"(exit {install_result.returncode}):\n"
                f"--- stdout ---\n{install_result.stdout}\n--- stderr ---\n{install_result.stderr}"
            )
        cmd = [sys.executable, "-m", "pip_audit", "--path", str(site_packages)]
        env = _utf8_child_env()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(tool_dir) + (os.pathsep + existing if existing else "")
        _run_pip_audit_cmd(cmd, env=env)


def _run_pip_audit_cmd(cmd: list[str], *, env: dict[str, str]) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=_NETWORK_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise BuildError(
            "pip-audit found known vulnerabilities (or failed to run) against "
            "the provisioned site-packages — aborting build rather than "
            "shipping a package with a known CVE.\n"
            f"--- pip-audit stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


# ── Unit 2: CLI shim generation ─────────────────────────────────────────────
#
# For each `[project.scripts]` entry in pyproject.toml, generate a
# `scripts/cli-shims/<name>.bat` in the OUTPUT package directory that calls
# the exact `module:function` target against the shipped
# `python-embed\python.exe`. See generate_cli_shims() for the full rationale
# (console-script .exe are not portable; `python -m <module>` silently no-ops
# for ~10 of the 49 modules with no `__main__` guard).


def _parse_project_scripts(repo_root: Path) -> dict[str, str]:
    """Parse `[project.scripts]` from `repo_root/pyproject.toml`.

    Returns `{name: "module.path:function"}`, e.g.
    `{"bp": "backlink_publisher.cli.bp:main"}`. Reads the live table (not a
    hardcoded count) so this naturally stays in sync as commands are
    added/removed — see the plan's Risks table.
    """
    pyproject_path = repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})
    if not scripts:
        raise BuildError(
            f"No [project.scripts] entries found in {pyproject_path} — "
            f"check the repo layout before trusting this check."
        )
    return dict(scripts)


def _split_script_target(target: str) -> tuple[str, str]:
    """Split a `"module.path:function"` [project.scripts] value into its parts."""
    module, sep, function = target.partition(":")
    module = module.strip()
    function = function.strip()
    if not sep or not module or not function:
        raise BuildError(
            f"Malformed [project.scripts] target {target!r} — expected "
            f"'module.path:function'."
        )
    return module, function


def _render_cli_shim_bat(module: str, function: str) -> str:
    """Render the body of one `scripts/cli-shims/<name>.bat`.

    Invokes the exact `module:function` pyproject.toml target via
    `-c "from <module> import <function>; <function>()"` against the shipped
    `python-embed\\python.exe` — deliberately NOT `python -m <module>`, which
    would silently import-and-exit without calling anything for the ~10 CLI
    modules that have no ``if __name__ == "__main__":`` guard (see
    `generate_cli_shims`'s docstring / the plan's Key Technical Decisions),
    and cannot express `backup-state`/`restore-state` mapping two different
    functions from the same `state_backup.py` module.

    `PYTHONPATH` is set to `<pkg_dir>\\app` (derived from the shim's own path
    via `%~dp0..\\..`, since shims live at `scripts\\cli-shims\\<name>.bat`)
    so CLI modules that import `webui_store` at module load time (e.g.
    `dispatch_backlinks.py`) resolve correctly — `webui_store` lives under
    `app\\`, not in `python-embed`'s `site-packages`.

    `chcp 65001 >nul` guards against the non-UTF-8-console encoding crash
    fixed in `docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`.

    The call is wrapped in `sys.exit(...)`, not a bare `<function>()` --
    without it, `comment`, `phase0-seal`, and `weights` (whose `main()`
    intentionally `return`s an int rather than calling `sys.exit()` itself,
    relying on their own `if __name__ == "__main__": sys.exit(main())`
    guard) would always report exit code 0 through this shim regardless of
    their actual return value, since `python -c` discards a bare
    expression's value. This is safe for the other ~46 targets too: their
    `main()` already calls `sys.exit()`/raises `SystemExit` internally, so
    `<function>()` never returns a value to the wrapping `sys.exit()` call
    in the first place.
    """
    call = f"import sys; from {module} import {function}; sys.exit({function}())"
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "setlocal\r\n"
        "set \"PYTHONPATH=%~dp0..\\..\\app\"\r\n"
        f"\"%~dp0..\\..\\python-embed\\python.exe\" -c \"{call}\" %*\r\n"
        "set \"EXITCODE=%ERRORLEVEL%\"\r\n"
        "endlocal & exit /b %EXITCODE%\r\n"
    )


# Driver script executed in a single subprocess by
# `_check_script_targets_resolvable` to check every [project.scripts] target
# in one process launch (instead of one subprocess per target — ~49x fewer
# spawns). Reads `[[name, module, function], ...]` as JSON from argv[1] and
# reports every failure (not just the first) so a broken build tells you
# everything wrong with pyproject.toml in one pass.
_EXISTENCE_CHECK_DRIVER_SRC = '''\
import importlib
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    targets = json.load(fh)

failures = []
for name, module, function in targets:
    try:
        mod = importlib.import_module(module)
        getattr(mod, function)
    except Exception as exc:  # noqa: BLE001 -- report every failure, don't stop at the first
        failures.append(f"{name} ({module}:{function}): {type(exc).__name__}: {exc}")

if failures:
    print("\\n".join(failures))
    sys.exit(1)
sys.exit(0)
'''


def _check_script_targets_resolvable(
    scripts: dict[str, str], *, python_exe: Path, repo_root: Path
) -> None:
    """Verify every `[project.scripts]` `module:function` target actually
    resolves (module importable, attribute exists) — raises `BuildError`
    (listing every failing target) rather than letting a build ship a shim
    that is guaranteed to fail at runtime.

    Runs ONE subprocess against `python_exe`, importing every target in turn,
    with `PYTHONPATH=<repo_root>` — `repo_root` contains `webui_store/` at
    its top level, which is exactly what Unit 3 later copies into the
    package's `app/`; checking against it here proves the same import will
    resolve once assembled, without making Unit 2 depend on Unit 3 running
    first.

    `python_exe` is deliberately a parameter rather than hardcoded to the
    just-provisioned `python-embed\\python.exe`: this check only proves
    import *resolvability* (catches typos/renames in pyproject.toml), which
    is interpreter-agnostic as long as `backlink_publisher` is installed —
    `generate_cli_shims` defaults it to `sys.executable` (the interpreter
    running this build script) so the check works without requiring Unit 1
    to have already run, and without needing a Windows-only executable to
    exist. Callers that want the extra rigor of checking against the literal
    shipped interpreter can pass `verify_python_exe=<output_dir>/python-embed/python.exe`
    (see `generate_cli_shims`).
    """
    targets = [
        (name, *_split_script_target(target)) for name, target in sorted(scripts.items())
    ]

    env = _utf8_child_env()
    env["PYTHONPATH"] = str(repo_root)

    with tempfile.TemporaryDirectory(prefix="bp-shim-check-") as tmp_str:
        tmp = Path(tmp_str)
        driver_path = tmp / "_check_targets.py"
        driver_path.write_text(_EXISTENCE_CHECK_DRIVER_SRC, encoding="utf-8")
        targets_path = tmp / "targets.json"
        targets_path.write_text(json.dumps(targets), encoding="utf-8")

        result = subprocess.run(
            [str(python_exe), str(driver_path), str(targets_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_LOCAL_SUBPROCESS_TIMEOUT_S,
        )

    if result.returncode != 0:
        raise BuildError(
            "CLI shim existence check failed — the following [project.scripts] "
            f"target(s) could not be resolved against {python_exe}; refusing "
            f"to ship shim(s) guaranteed to fail at runtime:\n"
            f"{result.stdout.strip()}\n{result.stderr.strip()}"
        )


def _find_interpreter_pth_file(python_embed_dir: Path) -> Path:
    """Locate the single `*._pth` file inside a provisioned `python-embed/`
    directory (named e.g. `python311._pth` — derived from the interpreter's
    version, but found by globbing here rather than recomputing the filename
    from a version string, so this doesn't need to know which Python version
    was provisioned)."""
    candidates = sorted(python_embed_dir.glob("*._pth"))
    if not candidates:
        raise BuildError(
            f"No *._pth file found in {python_embed_dir} — expected the "
            f"provisioned python-embed/ interpreter's ._pth file (see "
            f"provision_interpreter / _patch_pth_file, Unit 1)."
        )
    return candidates[0]


def ensure_app_dir_importable(python_embed_dir: Path) -> None:
    """Make `<pkg_dir>/app/` importable by every process spawned from the
    provisioned `python-embed/python.exe` — both the CLI shims and the
    WebUI launcher need `webui_app`/`webui_store` (which Unit 3 copies into
    `app/`, a sibling of `python-embed/`) on `sys.path`.

    CRITICAL FINDING (verified 2026-07-07 against a real provisioned
    python-embed/, not assumed from documentation): the official embeddable
    interpreter's `._pth` file causes Python to IGNORE the `PYTHONPATH`
    environment variable *entirely* — confirmed empirically that
    `sys.path` is byte-identical with and without `PYTHONPATH` set for a
    `._pth`-patched interpreter. Even running a script directly
    (`python.exe app\\webui.py`) does NOT auto-add the script's own
    directory to `sys.path` when a `._pth` file is present, unlike normal
    CPython. This invalidates the plan's Key Technical Decision text of
    relying on `set PYTHONPATH=<pkg_dir>\\app` in the generated `.bat`
    files to make `app\\` importable — that `set PYTHONPATH=...` line is
    kept in the generated shims/launchers anyway (harmless, and correct if
    they were ever pointed at a normal, non-`._pth`-restricted Python for
    local testing) but it is NOT what makes the shipped package work.

    The mechanism `._pth`-restricted interpreters DO honor: `._pth` files
    support literal relative path lines (each resolved relative to the
    `._pth` file's own directory) alongside the `import site` line Unit 1
    already uncommented. This function appends `..\\app` (relative to
    `python_embed_dir`, resolving to `<pkg_dir>\\app` given the Output
    Structure's `python-embed/` + `app/` sibling layout) to that file,
    idempotently (a no-op if already present). Non-existent path entries in
    a `._pth` file are silently ignored at interpreter startup, so calling
    this before `app/` physically exists (i.e. before Unit 3 assembles it)
    is safe — the entry only starts mattering once `app/` is actually there.
    """
    pth_path = _find_interpreter_pth_file(python_embed_dir)
    content = pth_path.read_text(encoding="utf-8")
    existing_lines = {line.strip() for line in content.splitlines()}
    if "..\\app" in existing_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "..\\app\n"
    pth_path.write_text(content, encoding="utf-8")


def generate_cli_shims(
    output_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    verify_python_exe: Path | None = None,
) -> Path:
    """Generate one `scripts/cli-shims/<name>.bat` per `[project.scripts]`
    entry into `output_dir` (the same in-progress package build directory
    Unit 1's `provision_interpreter` populates with `python-embed/`, and Unit
    3 later populates with `app/`).

    Does NOT use pip-generated console-script `.exe` (they hardcode the build
    machine's absolute interpreter path into their shebang, breaking R4 —
    relocatability) and does NOT use `python -m <module>` (silently
    import-and-exits for the ~10 modules with no `__main__` guard, and cannot
    express `backup-state`/`restore-state` mapping two functions from one
    module). Instead each shim calls the exact `module:function` target from
    pyproject.toml directly — see `_render_cli_shim_bat`.

    All shims are written to a scratch temp directory first; after every
    shim is written, `_check_script_targets_resolvable` verifies each target
    actually resolves, and only once that passes are the shims moved into
    `output_dir/scripts/cli-shims/` — mirrors `provision_interpreter`'s
    staging pattern so a failed build does not leave a half-built
    `cli-shims/` directory behind.

    If `output_dir/python-embed/` already exists (i.e. Unit 1's
    `provision_interpreter(output_dir / "python-embed", ...)` has already
    run — the expected Unit 5 orchestration order), this also calls
    `ensure_app_dir_importable` on it, since generated shims are only
    actually usable once that patch is applied (see its docstring for why
    `PYTHONPATH` alone does not suffice). If `python-embed/` doesn't exist
    yet, this step is skipped (not an error) — that only happens when
    calling `generate_cli_shims` standalone/in isolation (e.g. this
    function's own unit tests), not in the real build order.

    Returns the `output_dir/scripts/cli-shims/` path.
    """
    output_dir = Path(output_dir)
    repo_root = Path(repo_root)
    python_exe = Path(verify_python_exe) if verify_python_exe is not None else Path(sys.executable)

    scripts = _parse_project_scripts(repo_root)

    with tempfile.TemporaryDirectory(prefix="bp-cli-shims-build-") as tmp_str:
        staging_dir = Path(tmp_str) / "cli-shims"
        staging_dir.mkdir()

        for name, target in scripts.items():
            module, function = _split_script_target(target)
            shim_path = staging_dir / f"{name}.bat"
            shim_path.write_text(_render_cli_shim_bat(module, function), encoding="utf-8")

        _check_script_targets_resolvable(scripts, python_exe=python_exe, repo_root=repo_root)

        final_dir = output_dir / "scripts" / "cli-shims"
        if final_dir.exists():
            _rmtree_long_path_safe(final_dir)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_dir), str(final_dir))

    python_embed_dir = output_dir / "python-embed"
    if python_embed_dir.is_dir():
        ensure_app_dir_importable(python_embed_dir)

    return final_dir


# ── Unit 3: SPA build + package assembly ────────────────────────────────────
#
# Builds the Vue 3 SPA (`frontend/` -> `webui_app/spa_dist/`) and copies the
# WebUI backend code into the package's `app/` directory. Does NOT call
# provision_interpreter/generate_cli_shims itself -- that orchestration
# belongs to Unit 5, which is expected to call, in this order:
#
#   1. provision_interpreter(pkg_dir / "python-embed", repo_root=...)
#   2. generate_cli_shims(pkg_dir, repo_root=...)
#   3. assemble_package(pkg_dir, repo_root=...)
#
# `pkg_dir` is decided by Unit 5 BEFORE any of the three calls (steps 1-2
# already need it) -- see `package_dir_name` / `resolve_dist_package_dir`
# below for the version-derived-name helper Unit 5 should use to compute it.


def _npm_executable() -> str | None:
    """Locate `npm` on PATH. Isolated as its own function (rather than
    inlining `shutil.which("npm")` at each call site) so tests can
    monkeypatch just the detection step without needing a real Node.js
    install for the "npm not found" error path."""
    return shutil.which("npm")


def _run_npm_step(npm_exe: str, args: list[str], *, cwd: Path, step_label: str) -> None:
    """Run one `npm <args>` step in `cwd`, raising `BuildError` (with a
    message distinguishable from "npm not found") on a non-zero exit."""
    result = subprocess.run(
        [npm_exe, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_utf8_child_env(),
        timeout=_NETWORK_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise BuildError(
            f"{step_label} failed (exit {result.returncode}) in {cwd} — aborting the "
            f"SPA build; refusing to proceed with a stale or missing spa_dist/.\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def build_spa(frontend_dir: Path) -> Path:
    """Build the Vue 3 SPA via `npm ci && npm run build` in `frontend_dir`.

    Raises `BuildError` immediately — with a message that's clearly
    distinguishable from a build-script failure — if `npm` is not found on
    PATH at all (a different failure mode: the build machine itself is
    missing Node.js/npm, vs. the build script running but failing). Also
    raises `BuildError` if `npm ci` or `npm run build` exits non-zero, or if
    `npm run build` reports success but the expected output file is
    nonetheless missing (defensive — catches a misconfigured
    `vite.config.*` build.outDir silently diverging from where
    `webui_app/routes/spa.py` expects to find it).

    Returns the path to the built `webui_app/spa_dist/` directory (a sibling
    of `frontend_dir`'s parent's `webui_app/`, i.e.
    `frontend_dir.parent / "webui_app" / "spa_dist"` — matches
    `frontend/package.json`'s own description of the build target and what
    `webui_app/routes/spa.py` reads from).
    """
    frontend_dir = Path(frontend_dir)
    npm_exe = _npm_executable()
    if npm_exe is None:
        raise BuildError(
            "npm was not found on PATH — building the Vue 3 SPA requires "
            "Node.js/npm on the BUILD machine (only the built static output, "
            "webui_app/spa_dist/, ships to end users; Node.js itself is never "
            "part of the package). Install Node.js (https://nodejs.org) and "
            "ensure `npm` is on PATH, then re-run the build."
        )

    _run_npm_step(npm_exe, ["ci"], cwd=frontend_dir, step_label="`npm ci`")
    _run_npm_step(npm_exe, ["run", "build"], cwd=frontend_dir, step_label="`npm run build`")

    spa_dist_dir = frontend_dir.parent / "webui_app" / "spa_dist"
    index_html = spa_dist_dir / "index.html"
    if not index_html.is_file():
        raise BuildError(
            f"`npm run build` reported success but {index_html} was not "
            f"produced — check frontend/vite.config.* build.outDir still "
            f"points at ../webui_app/spa_dist (see frontend/package.json's "
            f"description field)."
        )
    return spa_dist_dir


def package_dir_name(repo_root: Path = REPO_ROOT, *, version: str | None = None) -> str:
    """Return the versioned package directory name
    `backlink-publisher-vX.Y.Z-win64` (matches the plan's Output Structure).

    `version` defaults to `None`, which reads `[project].version` from
    `repo_root/pyproject.toml`. Unit 5's CLI accepts an optional `--version`
    override (e.g. for building a package under a version number that
    hasn't been committed to pyproject.toml yet) — passing it through here
    keeps that override and the default pyproject.toml lookup on one code
    path instead of duplicating the TOML read at the call site.

    Deliberately NOT called internally by `assemble_package` — Unit 5 needs
    the same versioned name to compute `pkg_dir` BEFORE calling
    `provision_interpreter`/`generate_cli_shims` (both need `pkg_dir`
    already decided), i.e. before `assemble_package` ever runs. Exposed here
    (plus `resolve_dist_package_dir`) so Unit 5 doesn't need to reimplement
    the `pyproject.toml` version lookup.
    """
    if version is None:
        pyproject_path = repo_root / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        if not version:
            raise BuildError(f"No [project].version found in {pyproject_path}")
    return f"backlink-publisher-v{version}-win64"


def resolve_dist_package_dir(
    repo_root: Path = REPO_ROOT,
    *,
    dist_dir: Path | None = None,
    version: str | None = None,
) -> Path:
    """Compute the full versioned package output path, e.g.
    `<repo_root>/dist/backlink-publisher-v0.5.0-win64` — convenience wrapper
    around `package_dir_name` for Unit 5's orchestration. `dist_dir` defaults
    to `repo_root / "dist"` (matches the plan's Output Structure and
    `dist/`'s existing `.gitignore` entry). `version` is passed straight
    through to `package_dir_name` (see its docstring for the `--version`
    override rationale).
    """
    resolved_dist_dir = Path(dist_dir) if dist_dir is not None else repo_root / "dist"
    return resolved_dist_dir / package_dir_name(repo_root, version=version)


# Files/directories copied from repo_root into pkg_dir/app/ verbatim. Order
# matters only for readability here — copying is unconditional for each
# entry regardless of position.
_APP_COPY_ITEMS: tuple[str, ...] = (
    "webui.py",
    "serve.py",
    "webui_app",
    "webui_store",
    "config.example.toml",
)


def assemble_package(pkg_dir: Path, *, repo_root: Path = REPO_ROOT) -> Path:
    """Build the SPA and assemble `pkg_dir/app/` — the Unit 3 stage of the
    Windows portable package build.

    `pkg_dir` is taken as an already-decided package root (e.g. produced by
    `resolve_dist_package_dir`) rather than computed here, because Unit 5's
    orchestration needs the SAME `pkg_dir` for `provision_interpreter`
    (`pkg_dir / "python-embed"`) and `generate_cli_shims` (`pkg_dir`) BEFORE
    this function ever runs — see the plan's confirmed call order:
    `provision_interpreter` -> `generate_cli_shims` -> `assemble_package`.

    Steps, in order:

    1. `build_spa(repo_root / "frontend")` — runs BEFORE anything under
       `pkg_dir` is touched, so an SPA build failure (bad `npm`, failing
       build script) never leaves `pkg_dir/app/` half-populated: nothing in
       `pkg_dir` is modified until the SPA build has already fully
       succeeded.
    2. Clean-and-recreate `pkg_dir / "app"` (NOT the whole `pkg_dir` —
       `pkg_dir/python-embed` and `pkg_dir/scripts` are populated by Units 1
       and 2 earlier in the same build and must survive this call; deleting
       the whole `pkg_dir` here would destroy them). This still directly
       prevents the plan's motivating nested-duplicate-directory bug: a
       second `assemble_package` call against the same `pkg_dir` always
       replaces `app/` in place rather than nesting a new copy inside a
       stale one. Unit 5 owns the *top-level* "delete the whole versioned
       `pkg_dir` if it exists" idempotency step, run once before step 1 of
       its own orchestration (before `provision_interpreter`) — this
       function does not need to (and must not) repeat that here.
    3. Copy `webui.py`, `serve.py`, `webui_app/` (including the just-built
       `spa_dist/`), `webui_store/`, and `config.example.toml` from
       `repo_root` into `pkg_dir/app/`.

    Raises `BuildError` (propagated from `build_spa`, or raised directly
    here if an expected source file/directory is missing) on any failure.

    Returns `pkg_dir`.
    """
    pkg_dir = Path(pkg_dir)
    repo_root = Path(repo_root)
    frontend_dir = repo_root / "frontend"

    # Step 1: build the SPA fully BEFORE touching pkg_dir at all.
    build_spa(frontend_dir)

    # Step 2: clean-and-recreate pkg_dir/app only (see docstring for why not
    # the whole pkg_dir).
    app_dir = pkg_dir / "app"
    if app_dir.exists():
        _rmtree_long_path_safe(app_dir)
    app_dir.mkdir(parents=True, exist_ok=True)

    # Step 3: copy backend + built SPA into app/.
    for name in _APP_COPY_ITEMS:
        src = repo_root / name
        dest = app_dir / name
        if not src.exists():
            raise BuildError(
                f"Expected {src} to exist for packaging but it was not found — "
                f"check the repo layout before trusting assemble_package's "
                f"copy list ({_APP_COPY_ITEMS})."
            )
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    assembled_index = app_dir / "webui_app" / "spa_dist" / "index.html"
    if not assembled_index.is_file():
        raise BuildError(
            f"Assembly completed but {assembled_index} is missing — the SPA "
            f"build succeeded but its output was not copied correctly into "
            f"app/webui_app/spa_dist/."
        )

    return pkg_dir


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
            _rmtree_long_path_safe(output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging_dir), str(output_dir))

    return output_dir


# ── Unit 5: launch/helper scripts + docs + zip + checksum ───────────────────
#
# Everything below wires Units 1-4 together into the single
# `python scripts/packaging/build_windows_package.py` entrypoint described in
# the plan's Unit 5. Nothing above this section changes behavior for Units
# 1-4's own callers (their functions are used as-is, in the documented
# order: provision_interpreter -> generate_cli_shims -> assemble_package).

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# scripts/packaging/templates/<name>.bat.tmpl -> pkg_dir/scripts/<name>.bat
# (".tmpl" stripped — see launch-webui.bat.tmpl's own docstring for why these
# are plain byte-for-byte copies with no templating engine: every path
# inside them is %~dp0-relative, so nothing needs substituting at build
# time). Launch scripts and helper scripts are tracked as two separate
# tuples only for the numbered-progress-output grouping in build_package();
# the copy mechanism (_copy_bat_template) is identical for both.
_LAUNCH_SCRIPT_NAMES: tuple[str, ...] = ("launch-webui", "launch-cli")
_HELPER_SCRIPT_NAMES: tuple[str, ...] = (
    "install-playwright",
    "setup-scheduler",
    "setup-wizard",
)

# scripts/packaging/templates/<name> -> pkg_dir/<dest_name>. QUICK_START.txt
# and ONBOARDING.md copy verbatim under their own name; README-package.md is
# retitled to README.md (it's already written entirely in Traditional
# Chinese, so it doubles as the package's only README — see build_package's
# docstring for why no separate README.zh.md is generated).
# config-minimal-example.toml also copies verbatim.
_DOC_COPY_ITEMS: tuple[tuple[str, str], ...] = (
    ("QUICK_START.txt", "QUICK_START.txt"),
    ("ONBOARDING.md", "ONBOARDING.md"),
    ("README-package.md", "README.md"),
    ("config-minimal-example.toml", "config-minimal-example.toml"),
)


def _copy_template_file(template_name: str, dest: Path) -> None:
    """Copy `TEMPLATES_DIR / template_name` to `dest`, raising `BuildError`
    (not a bare `FileNotFoundError`) if the template is missing — a missing
    template means this script's own `scripts/packaging/templates/` tree is
    incomplete, which should abort the build with a clear message rather
    than a confusing traceback."""
    src = TEMPLATES_DIR / template_name
    if not src.is_file():
        raise BuildError(
            f"Expected packaging template not found at {src} — check "
            f"scripts/packaging/templates/ before trusting this build script."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _copy_bat_template(name: str, dest_dir: Path) -> None:
    """Copy `scripts/packaging/templates/<name>.bat.tmpl` to
    `dest_dir/<name>.bat` (drops the `.tmpl` suffix — see `_LAUNCH_SCRIPT_NAMES`
    / `_HELPER_SCRIPT_NAMES` docstring comment for why no templating engine
    is involved)."""
    _copy_template_file(f"{name}.bat.tmpl", dest_dir / f"{name}.bat")


def copy_launch_scripts(pkg_dir: Path) -> None:
    """Copy `launch-webui.bat` / `launch-cli.bat` into `pkg_dir/scripts/`
    (Unit 2's templates — this is the first thing that actually ships them
    into a built package; Unit 2 only wrote the source-controlled
    `.tmpl` copies)."""
    scripts_dir = Path(pkg_dir) / "scripts"
    for name in _LAUNCH_SCRIPT_NAMES:
        _copy_bat_template(name, scripts_dir)


def copy_helper_scripts(pkg_dir: Path) -> None:
    """Copy `install-playwright.bat`, `setup-scheduler.bat`, and
    `setup-wizard.bat` into `pkg_dir/scripts/` — the three scripts
    `ONBOARDING.md`/`README-package.md` promise but that no earlier unit
    had actually built (see Plan 2026-07-07-006 Unit 5's gap analysis).
    All three are real, working scripts (not stubs) — see their own
    docstring headers for what each one does and why."""
    scripts_dir = Path(pkg_dir) / "scripts"
    for name in _HELPER_SCRIPT_NAMES:
        _copy_bat_template(name, scripts_dir)


def copy_docs(pkg_dir: Path) -> None:
    """Copy Unit 4's doc templates into `pkg_dir` root per `_DOC_COPY_ITEMS`.

    No separate `README.zh.md` is generated: `README-package.md` (Unit 4's
    template) is already written entirely in Traditional Chinese, so
    copying it to `README.md` already serves Traditional-Chinese-reading
    users; a byte-identical `README.zh.md` alongside it would be pure
    duplication. (The plan's Output Structure sketch listed
    "README.md / README.zh.md" as a range declaration, not a hard
    requirement — see the plan's own line "此目錄樹是範圍宣告，非絕對限制".)
    """
    pkg_dir = Path(pkg_dir)
    for template_name, dest_name in _DOC_COPY_ITEMS:
        _copy_template_file(template_name, pkg_dir / dest_name)


def _create_zip_and_checksum(pkg_dir: Path, *, dist_dir: Path, pkg_name: str) -> Path:
    """Zip `pkg_dir` into `dist_dir/<pkg_name>.zip` (a SIBLING of `pkg_dir`,
    not nested inside it) and write `dist_dir/<pkg_name>.zip.sha256` next to
    it containing the zip's own SHA-256 (conventional `<hash>  <filename>`
    format, matching what `sha256sum -c` / PowerShell's
    `Get-FileHash | Compare-Object` style verification expects).

    Built to a staging name first (`<pkg_name>.staging.zip`), verified
    (checksum computed, sidecar written), and only THEN atomically moved
    (`os.replace`, which is atomic on Windows for same-volume renames) onto
    the real `<pkg_name>.zip` path — mirroring the staging-then-move pattern
    `provision_interpreter`/`generate_cli_shims` already use elsewhere in
    this file. Deliberately does NOT delete any pre-existing valid zip
    before the new one is confirmed good: if archive creation fails partway
    (disk full, AV lock, a prior build's zip from the same version is still
    the best available artifact) the old zip is untouched and still usable,
    rather than being deleted before its replacement is proven to exist.
    """
    dist_dir = Path(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / f"{pkg_name}.zip"
    # shutil.make_archive(base_name, "zip") always appends ".zip" to
    # base_name itself, so the staging base_name is "<pkg_name>.staging"
    # (producing "<pkg_name>.staging.zip"), not "<pkg_name>.zip.staging".
    staging_base_name = f"{pkg_name}.staging"
    staging_zip_path = dist_dir / f"{staging_base_name}.zip"
    if staging_zip_path.exists():
        staging_zip_path.unlink()

    try:
        archive_path = Path(
            shutil.make_archive(
                str(dist_dir / staging_base_name),
                "zip",
                root_dir=str(dist_dir),
                base_dir=pkg_name,
            )
        )
    except Exception as exc:
        if staging_zip_path.exists():
            staging_zip_path.unlink()
        raise BuildError(f"Failed to create zip archive at {zip_path}: {exc}") from exc

    if archive_path != staging_zip_path:
        # Defensive: shutil.make_archive is documented to return the path it
        # wrote to, which should always equal what we computed above given a
        # literal "zip" format argument — but don't silently trust that if a
        # future Python ever behaves differently.
        raise BuildError(
            f"shutil.make_archive wrote to an unexpected path {archive_path} "
            f"(expected {staging_zip_path}) — aborting rather than trusting "
            f"a zip that isn't where the rest of this script expects it."
        )

    sha256 = _sha256_file(staging_zip_path)
    sha256_path = zip_path.with_name(zip_path.name + ".sha256")
    sha256_path.write_text(f"{sha256}  {zip_path.name}\n", encoding="utf-8")

    # Both the archive and its checksum sidecar are known-good at this
    # point -- only now replace the real zip_path (os.replace is atomic on
    # Windows for a same-volume rename), so a reader can never observe a
    # half-written zip at the canonical path.
    os.replace(staging_zip_path, zip_path)

    return zip_path


_BUILD_STEP_COUNT = 7


def build_package(*, repo_root: Path = REPO_ROOT, version: str | None = None) -> Path:
    """Full Unit 5 orchestration: resolve the versioned output directory,
    wipe it if it already exists (the fix for the plan's motivating bug — a
    stale prior build produced a nested-duplicate
    `dist/backlink-publisher-v0.5.0-win64/backlink-publisher-v0.5.1-win64/`
    artifact), run Units 1-4 in order, then zip + checksum the result.

    Progress is printed as `[N/7] ...` before each step, mirroring
    `scripts/prep-release.sh`'s `N/4`-numbered style. On ANY failure
    (`BuildError` from a stage, or any other exception, wrapped as
    `BuildError` for a uniform caller contract), the partially-built
    `pkg_dir` is left in place (for inspection) but NO `.zip` is ever
    produced — the zip step only runs after every earlier step has already
    succeeded — and a message printed to stderr makes unambiguous that the
    build FAILED (a half-built `pkg_dir` must never look like a successful
    build to whoever runs this).

    Returns the path to the produced `.zip` on success.
    """
    repo_root = Path(repo_root)
    dist_dir = repo_root / "dist"
    pkg_dir = resolve_dist_package_dir(repo_root, dist_dir=dist_dir, version=version)
    pkg_name = pkg_dir.name

    print(f"Building {pkg_name} ...")
    print(f"  output directory: {pkg_dir}")

    if pkg_dir.exists():
        print(f"  Removing pre-existing {pkg_dir} (idempotent rebuild) ...")
        _rmtree_long_path_safe(pkg_dir)

    try:
        print(f"[1/{_BUILD_STEP_COUNT}] Provisioning Python interpreter...")
        provision_interpreter(pkg_dir / "python-embed", repo_root=repo_root)

        print(f"[2/{_BUILD_STEP_COUNT}] Generating CLI shims...")
        generate_cli_shims(pkg_dir, repo_root=repo_root)

        print(f"[3/{_BUILD_STEP_COUNT}] Building SPA and assembling app/...")
        assemble_package(pkg_dir, repo_root=repo_root)

        print(f"[4/{_BUILD_STEP_COUNT}] Copying launch scripts...")
        copy_launch_scripts(pkg_dir)

        print(f"[5/{_BUILD_STEP_COUNT}] Copying helper scripts...")
        copy_helper_scripts(pkg_dir)

        print(f"[6/{_BUILD_STEP_COUNT}] Copying documentation...")
        copy_docs(pkg_dir)
    except BuildError as exc:
        print(
            f"\nBUILD FAILED at: {exc}\n"
            f"Partially-built package left at: {pkg_dir}\n"
            f"This directory is NOT a usable package -- inspect it if useful, "
            f"then re-run the build once the underlying problem is fixed "
            f"(the next run will remove it automatically).",
            file=sys.stderr,
        )
        raise
    except Exception as exc:  # noqa: BLE001 -- convert to BuildError for a uniform caller contract
        print(
            f"\nBUILD FAILED with an unexpected error: {exc}\n"
            f"Partially-built package left at: {pkg_dir}\n"
            f"This directory is NOT a usable package -- inspect it if useful, "
            f"then re-run the build once the underlying problem is fixed "
            f"(the next run will remove it automatically).",
            file=sys.stderr,
        )
        raise BuildError(f"Unexpected error during build: {exc}") from exc

    print(f"[7/{_BUILD_STEP_COUNT}] Creating zip archive + checksum...")
    try:
        zip_path = _create_zip_and_checksum(pkg_dir, dist_dir=dist_dir, pkg_name=pkg_name)
    except BuildError as exc:
        print(
            f"\nBUILD FAILED at zip/checksum step: {exc}\n"
            f"Partially-built package directory (not a zip) left at: {pkg_dir}\n"
            f"No .zip was produced -- do not ship anything from this run.",
            file=sys.stderr,
        )
        raise

    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Windows portable package end-to-end: provision "
            "python-embed/, generate CLI shims, build+assemble the SPA/app, "
            "copy launch/helper scripts and docs, then zip the result with "
            "a .sha256 checksum. See "
            "docs/plans/2026-07-07-006-feat-windows-portable-package-plan.md."
        )
    )
    parser.add_argument(
        "--version",
        default=None,
        help=(
            "Override the package version used to name the output "
            "directory/zip (backlink-publisher-vX.Y.Z-win64). Defaults to "
            "[project].version in pyproject.toml."
        ),
    )
    args = parser.parse_args(argv)

    try:
        zip_path = build_package(repo_root=REPO_ROOT, version=args.version)
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    sha256_path = zip_path.with_name(zip_path.name + ".sha256")
    sha256_line = sha256_path.read_text(encoding="utf-8").strip()
    sha256_value = sha256_line.split()[0] if sha256_line else "(unavailable)"

    print("\nBuild succeeded.")
    print(f"  zip:    {zip_path}")
    print(f"  size:   {size_mb:.1f} MiB")
    print(f"  sha256: {sha256_value}")
    print(f"  (checksum file: {sha256_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
