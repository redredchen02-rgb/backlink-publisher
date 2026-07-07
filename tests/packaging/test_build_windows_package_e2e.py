"""Tests for the Unit 5 stage of scripts/packaging/build_windows_package.py
(full build orchestration: provision -> shims -> assemble -> launch/helper
scripts -> docs -> zip + checksum).

Three tiers, mirroring the pattern established by Units 1-3's own test
files:

  * Pure-unit tests (always run, no network, no real build): exercise
    `build_package()`'s control flow -- numbered progress, wipe-before-build
    idempotency, failure propagation, and the zip/checksum contract -- by
    monkeypatching the expensive stage functions (`provision_interpreter`,
    `generate_cli_shims`, `assemble_package`, `copy_launch_scripts`,
    `copy_helper_scripts`, `copy_docs`) rather than running them for real.

  * Idempotency regression test: confirms a stray nested-duplicate leftover
    from a prior broken build (the plan's motivating bug --
    `dist/backlink-publisher-v0.5.0-win64/backlink-publisher-v0.5.1-win64/`)
    is wiped before a fresh build starts.

  * Real end-to-end test (`@pytest.mark.real_packaging_build`, gated behind
    `BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD=1` + win32, never runs in CI):
    runs the full CLI for real, confirms the zip + checksum, extracts to a
    brand-new temp path that has never existed on this machine before (the
    plan's R4 portability check), and actually launches `launch-webui.bat`
    and a CLI shim from that extracted location. This is the single most
    important test in the whole plan -- see the plan's Unit 5 Verification
    section.
"""

from __future__ import annotations

__tier__ = "unit"

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

import pytest

from scripts.packaging import build_windows_package as bwp

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Pure-unit: build_package() control flow (mocked stages) ────────────────


def _make_fake_pyproject(repo_root: Path, *, version: str = "9.9.9") -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text(
        f'[project]\nname = "backlink-publisher"\nversion = "{version}"\n',
        encoding="utf-8",
    )


def _mock_all_stages(monkeypatch, *, fail_at: str | None = None) -> list[str]:
    """Monkeypatch every build_package() stage function with a cheap no-op
    that creates just enough on-disk structure for the next stage / the
    final zip step to look plausible, recording call order in `calls`.
    Raises `bwp.BuildError` at the named stage (if any) instead of running
    its fake effect -- used to prove failure propagation without needing a
    real (slow) provision/npm-build/etc.
    """
    calls: list[str] = []

    def _record(name):
        def _decorator(real_effect):
            def _stage(*args, **kwargs):
                calls.append(name)
                if name == fail_at:
                    raise bwp.BuildError(f"simulated failure at {name}")
                return real_effect(*args, **kwargs)

            return _stage

        return _decorator

    @_record("provision_interpreter")
    def _fake_provision(output_dir, *, repo_root=None, version=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "python.exe").write_bytes(b"fake-python-exe")
        return output_dir

    @_record("generate_cli_shims")
    def _fake_shims(output_dir, *, repo_root=None, verify_python_exe=None):
        final_dir = Path(output_dir) / "scripts" / "cli-shims"
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "bp.bat").write_text("@echo off\n", encoding="utf-8")
        return final_dir

    @_record("assemble_package")
    def _fake_assemble(pkg_dir, *, repo_root=None):
        app_dir = Path(pkg_dir) / "app"
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "webui.py").write_text("app = object()\n", encoding="utf-8")
        return pkg_dir

    @_record("copy_launch_scripts")
    def _fake_launch_scripts(pkg_dir):
        scripts_dir = Path(pkg_dir) / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "launch-webui.bat").write_text("@echo off\n", encoding="utf-8")

    @_record("copy_helper_scripts")
    def _fake_helper_scripts(pkg_dir):
        scripts_dir = Path(pkg_dir) / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "install-playwright.bat").write_text("@echo off\n", encoding="utf-8")

    @_record("copy_docs")
    def _fake_docs(pkg_dir):
        pkg_dir = Path(pkg_dir)
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "README.md").write_text("# fake\n", encoding="utf-8")

    monkeypatch.setattr(bwp, "provision_interpreter", _fake_provision)
    monkeypatch.setattr(bwp, "generate_cli_shims", _fake_shims)
    monkeypatch.setattr(bwp, "assemble_package", _fake_assemble)
    monkeypatch.setattr(bwp, "copy_launch_scripts", _fake_launch_scripts)
    monkeypatch.setattr(bwp, "copy_helper_scripts", _fake_helper_scripts)
    monkeypatch.setattr(bwp, "copy_docs", _fake_docs)

    return calls


def test_build_package_happy_path_produces_zip_and_checksum(tmp_path, monkeypatch):
    fake_repo = tmp_path / "repo"
    _make_fake_pyproject(fake_repo)
    calls = _mock_all_stages(monkeypatch)

    zip_path = bwp.build_package(repo_root=fake_repo)

    assert calls == [
        "provision_interpreter",
        "generate_cli_shims",
        "assemble_package",
        "copy_launch_scripts",
        "copy_helper_scripts",
        "copy_docs",
    ]
    assert zip_path.name == "backlink-publisher-v9.9.9-win64.zip"
    assert zip_path.is_file()
    assert zip_path.parent == fake_repo / "dist"  # sibling of pkg_dir, not nested inside it

    sha256_path = zip_path.with_name(zip_path.name + ".sha256")
    assert sha256_path.is_file()
    hash_value, _, filename = sha256_path.read_text(encoding="utf-8").strip().partition("  ")
    assert filename == zip_path.name
    assert hash_value == bwp._sha256_file(zip_path)

    pkg_dir = fake_repo / "dist" / "backlink-publisher-v9.9.9-win64"
    assert pkg_dir.is_dir()
    assert (pkg_dir / "python-embed" / "python.exe").is_file()
    assert (pkg_dir / "app" / "webui.py").is_file()
    assert (pkg_dir / "scripts" / "launch-webui.bat").is_file()
    assert (pkg_dir / "scripts" / "install-playwright.bat").is_file()
    assert (pkg_dir / "README.md").is_file()


def test_build_package_honors_version_override(tmp_path, monkeypatch):
    fake_repo = tmp_path / "repo"
    _make_fake_pyproject(fake_repo, version="1.0.0")
    _mock_all_stages(monkeypatch)

    zip_path = bwp.build_package(repo_root=fake_repo, version="2.5.0")
    assert zip_path.name == "backlink-publisher-v2.5.0-win64.zip"


# ── Error path: any stage failure aborts the build with no zip produced ────


@pytest.mark.parametrize(
    "fail_at",
    [
        "provision_interpreter",
        "generate_cli_shims",
        "assemble_package",
        "copy_launch_scripts",
    ],
)
def test_build_package_stage_failure_propagates_and_produces_no_zip(
    tmp_path, monkeypatch, fail_at
):
    fake_repo = tmp_path / "repo"
    _make_fake_pyproject(fake_repo)
    _mock_all_stages(monkeypatch, fail_at=fail_at)

    with pytest.raises(bwp.BuildError, match=f"simulated failure at {fail_at}"):
        bwp.build_package(repo_root=fake_repo)

    dist_dir = fake_repo / "dist"
    zips = list(dist_dir.glob("*.zip")) if dist_dir.exists() else []
    assert zips == [], "a failed build must never leave a .zip behind"


def test_main_reports_build_failure_clearly_and_leaves_no_zip(tmp_path, monkeypatch, capsys):
    fake_repo = tmp_path / "repo"
    _make_fake_pyproject(fake_repo)
    monkeypatch.setattr(bwp, "REPO_ROOT", fake_repo)
    _mock_all_stages(monkeypatch, fail_at="assemble_package")

    exit_code = bwp.main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "BUILD FAILED" in captured.err
    assert "simulated failure at assemble_package" in captured.err

    dist_dir = fake_repo / "dist"
    zips = list(dist_dir.glob("*.zip")) if dist_dir.exists() else []
    assert zips == []


# ── Idempotency: stray nested-duplicate leftover is wiped before rebuild ───


def test_build_package_removes_stale_nested_duplicate_before_rebuild(tmp_path, monkeypatch):
    """Direct regression test for the plan's motivating bug: a prior broken
    build's stray nested-duplicate directory (and any other leftover) under
    the target pkg_dir must be wiped before the fresh build starts, not
    merged into or left alongside the new output."""
    fake_repo = tmp_path / "repo"
    _make_fake_pyproject(fake_repo)

    pkg_dir = fake_repo / "dist" / "backlink-publisher-v9.9.9-win64"
    stray_nested = pkg_dir / "backlink-publisher-v9.9.8-win64" / "leftover.txt"
    stray_nested.parent.mkdir(parents=True)
    stray_nested.write_text("stale nested duplicate from a prior broken build", encoding="utf-8")
    stray_top_level = pkg_dir / "stray-top-level-file.txt"
    stray_top_level.write_text("also stale", encoding="utf-8")

    _mock_all_stages(monkeypatch)

    bwp.build_package(repo_root=fake_repo)

    assert not stray_nested.exists()
    assert not stray_top_level.exists()
    assert not (pkg_dir / "backlink-publisher-v9.9.8-win64").exists()
    # The fresh build's own output must still be present (cleanup didn't
    # just delete everything and stop).
    assert (pkg_dir / "app" / "webui.py").is_file()


# ── Real end-to-end test (opt-in, never runs in CI) ─────────────────────────
#
# Reuses the same marker/gate as Units 1-3 (registered in pyproject.toml).

_REAL_ENV = "BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD"


def _real_packaging_build_enabled() -> bool:
    return os.environ.get(_REAL_ENV) == "1"


_real_skip = pytest.mark.skipif(
    sys.platform != "win32" or not _real_packaging_build_enabled(),
    reason=(
        "Real end-to-end build needs Windows (to execute the resulting "
        "python.exe / .bat launchers) and real network + npm access "
        f"(downloads the embeddable zip, ~60 PyPI packages, and runs a real "
        f"`npm ci && npm run build`); set {_REAL_ENV}=1 on such a machine to "
        "run. Never runs in CI -- this is the slowest test in the suite."
    ),
)


def _poll_for_launched_port(stdout_path: Path, *, timeout_s: float = 30.0) -> int:
    """Parse `launch-webui.bat`'s own "Open: http://127.0.0.1:<port>" line
    out of its redirected stdout, polling until it appears (the port-scan
    loop inside the .bat itself takes a few seconds) or `timeout_s` elapses.
    """
    deadline = time.time() + timeout_s
    pattern = re.compile(r"Open:\s*http://127\.0\.0\.1:(\d+)")
    last_seen = ""
    while time.time() < deadline:
        if stdout_path.is_file():
            last_seen = stdout_path.read_text(encoding="utf-8", errors="replace")
            match = pattern.search(last_seen)
            if match:
                return int(match.group(1))
        time.sleep(0.5)
    raise AssertionError(
        f"launch-webui.bat did not print an 'Open: http://127.0.0.1:<port>' "
        f"line within {timeout_s}s. Captured stdout so far:\n{last_seen}"
    )


def _poll_for_http_200(url: str, *, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                if resp.status == 200:
                    return
                last_error = AssertionError(f"got HTTP {resp.status} from {url}")
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
        time.sleep(1)
    raise AssertionError(f"{url} never returned HTTP 200 within {timeout_s}s: {last_error}")


@pytest.mark.real_packaging_build
@_real_skip
def test_real_build_extract_launch_and_cli_shim_end_to_end(tmp_path_factory):
    """The single most important test in the whole plan: build the real
    package, extract it onto a path that has NEVER existed on this machine
    before (R4's portability requirement), launch the real
    `launch-webui.bat`, poll it for an HTTP 200, then confirm a CLI shim
    also runs from that same extracted location -- all without depending on
    anything from the build machine's Python/Node installation once the zip
    exists.
    """
    # This suite blocks real network access by default (pytest-socket,
    # autouse) -- opt back in for this one test, matching the pattern
    # already established by test_build_windows_package.py's
    # real_provisioned_python_embed fixture.
    try:
        from pytest_socket import enable_socket

        enable_socket()
    except ImportError:
        pass

    build_started_at = time.time()

    # ── 1. Real build ────────────────────────────────────────────────────
    zip_path = bwp.build_package(repo_root=REPO_ROOT)
    build_elapsed = time.time() - build_started_at
    print(f"\n[real e2e] build_package() took {build_elapsed:.1f}s -> {zip_path}")

    assert zip_path.is_file()
    sha256_path = zip_path.with_name(zip_path.name + ".sha256")
    assert sha256_path.is_file()
    recorded_hash, _, filename = sha256_path.read_text(encoding="utf-8").strip().partition("  ")
    assert filename == zip_path.name
    actual_hash = bwp._sha256_file(zip_path)
    assert recorded_hash == actual_hash, (
        "the .sha256 file's recorded hash does not match the zip's real "
        "computed hash -- a user verifying their download would see a "
        "mismatch"
    )

    # ── 2. Extract onto a path that has never existed on this machine ─────
    # tempfile.mkdtemp() always mints a brand-new directory name -- this
    # satisfies the plan's R4 "extract to a path that never existed before"
    # portability check without needing a second machine/VM.
    extract_root = Path(tempfile.mkdtemp(prefix="bwp-real-e2e-extract-"))
    print(f"[real e2e] extracting to never-before-existing path: {extract_root}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_root)

    pkg_name = zip_path.stem  # backlink-publisher-vX.Y.Z-win64
    extracted_pkg_dir = extract_root / pkg_name
    assert extracted_pkg_dir.is_dir()
    launch_webui_bat = extracted_pkg_dir / "scripts" / "launch-webui.bat"
    bp_shim_bat = extracted_pkg_dir / "scripts" / "cli-shims" / "bp.bat"
    assert launch_webui_bat.is_file()
    assert bp_shim_bat.is_file()

    # ── 3. Launch launch-webui.bat for real and poll for HTTP 200 ─────────
    webui_stdout_path = extract_root / "webui-stdout.log"
    webui_stderr_path = extract_root / "webui-stderr.log"
    webui_proc = subprocess.Popen(
        ["cmd", "/c", str(launch_webui_bat)],
        cwd=str(launch_webui_bat.parent),
        stdout=open(webui_stdout_path, "wb"),
        stderr=open(webui_stderr_path, "wb"),
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        port = _poll_for_launched_port(webui_stdout_path, timeout_s=30.0)
        print(f"[real e2e] launch-webui.bat reports port {port}")
        _poll_for_http_200(f"http://127.0.0.1:{port}/", timeout_s=45.0)
        print(f"[real e2e] http://127.0.0.1:{port}/ responded 200 OK")
    finally:
        # taskkill /T kills the whole process tree -- launch-webui.bat spawns
        # python-embed\python.exe serve.py as a child, which would otherwise
        # keep the port bound after this test exits.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(webui_proc.pid)],
            capture_output=True,
            text=True,
        )
        webui_proc.wait(timeout=15)

    # ── 4. A CLI shim also runs from the same extracted location ──────────
    bp_result = subprocess.run(
        ["cmd", "/c", str(bp_shim_bat)],
        cwd=str(bp_shim_bat.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        # errors="replace": bp.bat's grouped command listing intermixes
        # console-codepage bytes that chcp 65001 (set inside the .bat) does
        # not fully normalize on piped/redirected stdout (a real Windows
        # gotcha, not specific to this repo -- see docs/plans/2026-07-03-001
        # -fix-windows-webui-encoding-crash-plan.md for the same class of
        # issue in production code). Without this, a stray non-UTF-8 byte
        # crashes subprocess.run's internal reader thread and silently
        # leaves bp_result.stdout as None instead of raising a clear error.
        errors="replace",
        timeout=30,
    )
    print(f"[real e2e] bp.bat exit={bp_result.returncode}")
    assert bp_result.returncode == 0, (
        f"bp.bat failed from the extracted package -- stdout:\n{bp_result.stdout}\n"
        f"stderr:\n{bp_result.stderr}"
    )
    assert "plan-backlinks" in bp_result.stdout, (
        "expected bp.bat's grouped command listing to mention plan-backlinks "
        f"-- got:\n{bp_result.stdout}"
    )

    shutil.rmtree(extract_root, ignore_errors=True)
