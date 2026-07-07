"""Tests for the Unit 3 stage of scripts/packaging/build_windows_package.py
(SPA build + package assembly into `pkg_dir/app/`).

Two tiers, mirroring tests/packaging/test_build_windows_package.py (Unit 1)
and tests/packaging/test_cli_shim_generation.py (Unit 2):

  * Pure-unit tests (always run, no network, no real npm build): exercise
    `assemble_package`'s copy/cleanup logic and `build_spa`'s error paths by
    monkeypatching `_npm_executable`/`subprocess.run`/`build_spa` rather than
    invoking a real (slow) `npm ci && npm run build`.

  * Real-build integration tests (`@pytest.mark.real_packaging_build`,
    reusing the same marker/gate as Units 1-2 — registered in pyproject.toml
    and never runs in CI): actually run `npm ci && npm run build` against
    the real `frontend/` and assert the assembled `app/webui_app/spa_dist/`
    came from that real build, not a stale pre-existing one. Skipped unless
    `BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD=1` is set. Unlike Units 1-2's
    real tests, this does NOT also require win32 — `npm`/Vite build
    cross-platform, so this can run wherever Node.js is installed.
"""

from __future__ import annotations

__tier__ = "unit"

import os
from pathlib import Path
import shutil
import time

import pytest

from scripts.packaging import build_windows_package as bwp

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Pure-unit: npm detection / _run_npm_step ────────────────────────────────


def test_build_spa_raises_distinct_error_when_npm_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_npm_executable", lambda: None)
    with pytest.raises(bwp.BuildError, match="npm was not found on PATH"):
        bwp.build_spa(tmp_path / "frontend")


def test_build_spa_error_message_distinguishes_missing_npm_from_build_failure(
    tmp_path, monkeypatch
):
    """The 'npm not found' message must not be confusable with a build-script
    failure message — different failure modes, different diagnosis."""
    monkeypatch.setattr(bwp, "_npm_executable", lambda: None)
    with pytest.raises(bwp.BuildError) as excinfo:
        bwp.build_spa(tmp_path / "frontend")
    message = str(excinfo.value)
    assert "npm ci" not in message
    assert "npm run build" not in message
    assert "exit" not in message  # no exit-code language — this never ran a process


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_build_spa_raises_on_npm_ci_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_npm_executable", lambda: "npm")
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(returncode=1, stdout="", stderr="ci failed: lockfile drift")

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)
    with pytest.raises(bwp.BuildError, match=r"npm ci.*failed"):
        bwp.build_spa(tmp_path / "frontend")

    assert len(calls) == 1  # must not proceed to `npm run build` after `npm ci` fails
    assert calls[0] == ["npm", "ci"]


def test_build_spa_raises_on_npm_run_build_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_npm_executable", lambda: "npm")
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["npm", "ci"]:
            return _FakeCompletedProcess(returncode=0)
        return _FakeCompletedProcess(returncode=1, stdout="", stderr="Vite build error: syntax error")

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)
    with pytest.raises(bwp.BuildError, match=r"npm run build.*failed"):
        bwp.build_spa(tmp_path / "frontend")

    assert calls == [["npm", "ci"], ["npm", "run", "build"]]


def test_build_spa_raises_if_index_html_missing_after_reported_success(tmp_path, monkeypatch):
    """Defensive: npm reports success but the expected output file isn't
    there (e.g. misconfigured build.outDir) -- must not silently proceed."""
    monkeypatch.setattr(bwp, "_npm_executable", lambda: "npm")

    def _fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()

    with pytest.raises(bwp.BuildError, match="was not produced"):
        bwp.build_spa(frontend_dir)


def test_build_spa_returns_spa_dist_path_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr(bwp, "_npm_executable", lambda: "npm")

    frontend_dir = tmp_path / "frontend"
    spa_dist_dir = tmp_path / "webui_app" / "spa_dist"

    def _fake_run(cmd, **kwargs):
        if cmd == ["npm", "run", "build"]:
            spa_dist_dir.mkdir(parents=True)
            (spa_dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        return _FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(bwp.subprocess, "run", _fake_run)
    result = bwp.build_spa(frontend_dir)
    assert result == spa_dist_dir
    assert (result / "index.html").is_file()


# ── Pure-unit: package_dir_name / resolve_dist_package_dir ─────────────────


def test_package_dir_name_reads_real_pyproject_version():
    name = bwp.package_dir_name(REPO_ROOT)
    assert name.startswith("backlink-publisher-v")
    assert name.endswith("-win64")
    # Sanity: matches the real pinned version, not a stale hardcoded value.
    import tomllib

    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    assert name == f"backlink-publisher-v{version}-win64"


def test_package_dir_name_raises_on_missing_version(tmp_path):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(bwp.BuildError, match="No \\[project\\].version"):
        bwp.package_dir_name(fake_repo)


def test_resolve_dist_package_dir_defaults_to_repo_root_dist():
    result = bwp.resolve_dist_package_dir(REPO_ROOT)
    assert result.parent == REPO_ROOT / "dist"
    assert result.name == bwp.package_dir_name(REPO_ROOT)


def test_resolve_dist_package_dir_honors_custom_dist_dir(tmp_path):
    result = bwp.resolve_dist_package_dir(REPO_ROOT, dist_dir=tmp_path)
    assert result.parent == tmp_path
    assert result.name == bwp.package_dir_name(REPO_ROOT)


# ── Pure-unit: assemble_package copy logic (mocked SPA build) ──────────────


def _make_fake_repo(root: Path, *, with_spa_dist: bool = True) -> Path:
    """Build a minimal fake repo_root with just enough real structure for
    assemble_package's copy step (webui.py, serve.py, webui_app/, webui_store/,
    config.example.toml) — independent of the real repo so these tests don't
    need a real npm build."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "webui.py").write_text("app = object()\n", encoding="utf-8")
    (root / "serve.py").write_text("from webui import app\n", encoding="utf-8")
    (root / "config.example.toml").write_text("[example]\n", encoding="utf-8")

    webui_app_dir = root / "webui_app"
    webui_app_dir.mkdir()
    (webui_app_dir / "__init__.py").write_text("", encoding="utf-8")
    if with_spa_dist:
        spa_dist_dir = webui_app_dir / "spa_dist"
        spa_dist_dir.mkdir()
        (spa_dist_dir / "index.html").write_text("<html>fake spa</html>", encoding="utf-8")

    webui_store_dir = root / "webui_store"
    webui_store_dir.mkdir()
    (webui_store_dir / "__init__.py").write_text("", encoding="utf-8")

    return root


def _monkeypatch_fake_spa_build(monkeypatch, fake_repo: Path) -> None:
    """Make build_spa a no-op that just confirms the fake repo already has
    a spa_dist/index.html (mirroring what a real npm run build would have
    produced) — used by tests that only care about assemble_package's
    copy/cleanup logic, not build_spa's own behavior."""

    def _fake_build_spa(frontend_dir: Path) -> Path:
        spa_dist_dir = fake_repo / "webui_app" / "spa_dist"
        assert (spa_dist_dir / "index.html").is_file()
        return spa_dist_dir

    monkeypatch.setattr(bwp, "build_spa", _fake_build_spa)


def test_assemble_package_copies_all_expected_files(tmp_path, monkeypatch):
    fake_repo = _make_fake_repo(tmp_path / "repo")
    _monkeypatch_fake_spa_build(monkeypatch, fake_repo)

    pkg_dir = tmp_path / "pkg"
    result = bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    assert result == pkg_dir
    app_dir = pkg_dir / "app"
    assert (app_dir / "webui.py").is_file()
    assert (app_dir / "serve.py").is_file()
    assert (app_dir / "config.example.toml").is_file()
    assert (app_dir / "webui_app" / "spa_dist" / "index.html").is_file()
    assert (app_dir / "webui_store" / "__init__.py").is_file()


def test_assemble_package_does_not_touch_sibling_python_embed_or_scripts(tmp_path, monkeypatch):
    """Confirms assemble_package's cleanup is scoped to pkg_dir/app only --
    python-embed/ and scripts/ (populated by Units 1-2 earlier in the same
    build) must survive a call to assemble_package."""
    fake_repo = _make_fake_repo(tmp_path / "repo")
    _monkeypatch_fake_spa_build(monkeypatch, fake_repo)

    pkg_dir = tmp_path / "pkg"
    (pkg_dir / "python-embed").mkdir(parents=True)
    (pkg_dir / "python-embed" / "python.exe").write_text("fake exe", encoding="utf-8")
    (pkg_dir / "scripts" / "cli-shims").mkdir(parents=True)
    (pkg_dir / "scripts" / "cli-shims" / "bp.bat").write_text("@echo off\n", encoding="utf-8")

    bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    assert (pkg_dir / "python-embed" / "python.exe").is_file()
    assert (pkg_dir / "scripts" / "cli-shims" / "bp.bat").is_file()


def test_assemble_package_raises_if_expected_source_missing(tmp_path, monkeypatch):
    fake_repo = _make_fake_repo(tmp_path / "repo")
    _monkeypatch_fake_spa_build(monkeypatch, fake_repo)
    (fake_repo / "config.example.toml").unlink()

    with pytest.raises(bwp.BuildError, match="config.example.toml"):
        bwp.assemble_package(tmp_path / "pkg", repo_root=fake_repo)


# ── Error path: npm build failure must leave no half-populated app/ ────────


def test_assemble_package_npm_build_failure_leaves_no_app_dir(tmp_path, monkeypatch):
    fake_repo = _make_fake_repo(tmp_path / "repo")

    def _fake_build_spa_fails(frontend_dir: Path) -> Path:
        raise bwp.BuildError("`npm run build` failed (exit 1): simulated syntax error")

    monkeypatch.setattr(bwp, "build_spa", _fake_build_spa_fails)

    pkg_dir = tmp_path / "pkg"
    with pytest.raises(bwp.BuildError, match="npm run build"):
        bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    assert not (pkg_dir / "app").exists()


def test_assemble_package_npm_build_failure_does_not_disturb_existing_app_dir(
    tmp_path, monkeypatch
):
    """A failed SPA build must not touch a pre-existing (previously
    successfully assembled) app/ dir either."""
    fake_repo = _make_fake_repo(tmp_path / "repo")
    pkg_dir = tmp_path / "pkg"
    app_dir = pkg_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "sentinel-from-previous-good-build.txt").write_text("keep me", encoding="utf-8")

    def _fake_build_spa_fails(frontend_dir: Path) -> Path:
        raise bwp.BuildError("simulated npm failure")

    monkeypatch.setattr(bwp, "build_spa", _fake_build_spa_fails)

    with pytest.raises(bwp.BuildError, match="simulated npm failure"):
        bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    assert (app_dir / "sentinel-from-previous-good-build.txt").is_file()


def test_assemble_package_npm_not_found_raises_build_error(tmp_path, monkeypatch):
    fake_repo = _make_fake_repo(tmp_path / "repo")
    monkeypatch.setattr(bwp, "_npm_executable", lambda: None)

    pkg_dir = tmp_path / "pkg"
    with pytest.raises(bwp.BuildError, match="npm was not found on PATH"):
        bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    assert not (pkg_dir / "app").exists()


# ── Idempotency: repeated calls don't nest, produce the same file set ──────


def test_assemble_package_twice_produces_same_file_set_without_nesting(tmp_path, monkeypatch):
    fake_repo = _make_fake_repo(tmp_path / "repo")
    _monkeypatch_fake_spa_build(monkeypatch, fake_repo)

    pkg_dir = tmp_path / "pkg"
    bwp.assemble_package(pkg_dir, repo_root=fake_repo)
    first_run_files = sorted(
        str(p.relative_to(pkg_dir)) for p in pkg_dir.rglob("*") if p.is_file()
    )

    bwp.assemble_package(pkg_dir, repo_root=fake_repo)
    second_run_files = sorted(
        str(p.relative_to(pkg_dir)) for p in pkg_dir.rglob("*") if p.is_file()
    )

    assert first_run_files == second_run_files
    # Direct check against the historical nested-duplicate-directory bug:
    # no "app" component should ever appear twice in any file's relative path.
    for rel_path in second_run_files:
        parts = Path(rel_path).parts
        assert parts.count("app") == 1, f"nested app/ directory detected: {rel_path}"


def test_assemble_package_twice_replaces_stale_app_content(tmp_path, monkeypatch):
    """A file left behind by a previous run under app/ (e.g. a deleted repo
    file) must not survive into the second run's output."""
    fake_repo = _make_fake_repo(tmp_path / "repo")
    _monkeypatch_fake_spa_build(monkeypatch, fake_repo)

    pkg_dir = tmp_path / "pkg"
    bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    stale_file = pkg_dir / "app" / "webui_app" / "stale_leftover.txt"
    stale_file.write_text("should not survive", encoding="utf-8")
    assert stale_file.is_file()

    bwp.assemble_package(pkg_dir, repo_root=fake_repo)

    assert not stale_file.exists()


# ── Real-build integration tests (opt-in, never run in CI) ─────────────────
#
# Reuses the same marker/gate as Units 1-2 (registered in pyproject.toml).
# Unlike those, this doesn't require win32 -- npm/Vite build cross-platform.

_REAL_ENV = "BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD"


def _real_packaging_build_enabled() -> bool:
    return os.environ.get(_REAL_ENV) == "1"


_real_skip = pytest.mark.skipif(
    not _real_packaging_build_enabled(),
    reason=(
        "Real SPA assembly needs a real `npm ci && npm run build` against "
        f"frontend/ (network + Node.js); set {_REAL_ENV}=1 to run. Never "
        "runs in CI."
    ),
)


@pytest.mark.real_packaging_build
@_real_skip
def test_real_assemble_package_happy_path(tmp_path):
    """Full real assembly: real npm build + real copy against the real repo.
    Asserts the resulting app/ contains everything the plan's Output
    Structure expects."""
    # Force-delete any pre-existing webui_app/spa_dist/ in the repo first so
    # there is nothing stale to accidentally reuse (it's gitignored, so this
    # is safe and matches what a clean checkout would have).
    real_spa_dist = REPO_ROOT / "webui_app" / "spa_dist"
    if real_spa_dist.exists():
        shutil.rmtree(real_spa_dist)

    build_started_at = time.time()

    pkg_dir = tmp_path / "pkg"
    result = bwp.assemble_package(pkg_dir, repo_root=REPO_ROOT)

    assert result == pkg_dir
    app_dir = pkg_dir / "app"
    assert (app_dir / "webui.py").is_file()
    assert (app_dir / "serve.py").is_file()
    assert (app_dir / "config.example.toml").is_file()
    assert (app_dir / "webui_store" / "__init__.py").is_file()

    index_html = app_dir / "webui_app" / "spa_dist" / "index.html"
    assert index_html.is_file()
    # Direct proof this came from the real build just triggered, not a stale
    # pre-existing file: mtime must be at/after when this test started the
    # build (the real repo's copy was force-deleted above, so any survivor
    # here was necessarily (re)created by build_spa during this test run).
    assert index_html.stat().st_mtime >= build_started_at - 1


@pytest.mark.real_packaging_build
@_real_skip
def test_real_build_spa_produces_real_vite_output(tmp_path):
    """Narrower real-build check directly on build_spa: confirms the built
    index.html references hashed asset files (a real Vite build fingerprint,
    not a hand-authored stub)."""
    real_spa_dist = REPO_ROOT / "webui_app" / "spa_dist"
    if real_spa_dist.exists():
        shutil.rmtree(real_spa_dist)

    result = bwp.build_spa(REPO_ROOT / "frontend")

    assert result == real_spa_dist
    index_html = (result / "index.html").read_text(encoding="utf-8")
    assert "<div id=" in index_html or "<script" in index_html
    assert any(result.glob("assets/*"))
