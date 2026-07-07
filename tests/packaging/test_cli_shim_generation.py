"""Tests for the Unit 2 stage of scripts/packaging/build_windows_package.py
(CLI shim generation from pyproject.toml's [project.scripts]).

Two tiers, mirroring tests/packaging/test_build_windows_package.py (Unit 1):

  * Pure-unit tests (always run, no network, no Windows requirement): parse
    the real pyproject.toml, generate shims into a temp dir, and check their
    content/count. The existence check itself spawns a real subprocess
    (against the interpreter running pytest) but that's pure local import
    resolution -- no network, no Windows-only executable involved, so these
    run cross-platform in CI.

  * Real-network/Windows integration tests (`@pytest.mark.real_packaging_build`
    + `skipif`, reusing the same gate as Unit 1): provision a real
    python-embed/, generate shims against it, and actually execute a
    generated .bat via `cmd /c` -- this is the test that directly proves the
    "python -m silently no-ops for ~10 commands" bug the plan exists to fix
    is actually closed. Skipped unless win32 + BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD=1.
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


# ── Pure-unit: [project.scripts] parsing ────────────────────────────────────


def test_parse_project_scripts_reads_real_pyproject():
    scripts = bwp._parse_project_scripts(REPO_ROOT)
    assert isinstance(scripts, dict)
    assert scripts["bp"] == "backlink_publisher.cli.bp:main"
    assert scripts["backup-state"] == "backlink_publisher.cli.admin.state_backup:backup_main"
    assert scripts["restore-state"] == "backlink_publisher.cli.admin.state_backup:restore_main"


def test_parse_project_scripts_raises_on_empty_table(tmp_path):
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    (fake_repo / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(bwp.BuildError, match="No \\[project.scripts\\]"):
        bwp._parse_project_scripts(fake_repo)


def test_split_script_target_happy_path():
    module, function = bwp._split_script_target("backlink_publisher.cli.bp:main")
    assert module == "backlink_publisher.cli.bp"
    assert function == "main"


@pytest.mark.parametrize("bad_target", ["no-colon-here", ":missing-module", "missing-func:"])
def test_split_script_target_rejects_malformed(bad_target):
    with pytest.raises(bwp.BuildError, match="Malformed"):
        bwp._split_script_target(bad_target)


# ── Pure-unit: shim rendering ────────────────────────────────────────────────


def test_render_cli_shim_bat_uses_dash_c_not_dash_m():
    content = bwp._render_cli_shim_bat("backlink_publisher.cli.bp", "main")
    assert '-c "import sys; from backlink_publisher.cli.bp import main; sys.exit(main())"' in content
    assert "-m backlink_publisher.cli.bp" not in content
    assert "-m " not in content


def test_render_cli_shim_bat_has_chcp_and_pythonpath():
    content = bwp._render_cli_shim_bat("backlink_publisher.cli.bp", "main")
    assert "chcp 65001" in content
    assert "PYTHONPATH=%~dp0..\\..\\app" in content


def test_render_cli_shim_bat_calls_python_embed_relative_path():
    content = bwp._render_cli_shim_bat("backlink_publisher.cli.bp", "main")
    assert "%~dp0..\\..\\python-embed\\python.exe" in content
    assert "%*" in content


def test_render_cli_shim_bat_distinguishes_two_functions_same_module():
    """backup-state / restore-state map two different functions from the
    SAME state_backup.py module -- the exact case `-m` cannot express."""
    backup = bwp._render_cli_shim_bat(
        "backlink_publisher.cli.admin.state_backup", "backup_main"
    )
    restore = bwp._render_cli_shim_bat(
        "backlink_publisher.cli.admin.state_backup", "restore_main"
    )
    assert "backup_main()" in backup
    assert "restore_main()" not in backup
    assert "restore_main()" in restore
    assert "backup_main()" not in restore


# ── Pure-unit: generate_cli_shims happy path against the real pyproject ────


def test_generate_cli_shims_happy_path_against_real_pyproject(tmp_path):
    """One .bat per [project.scripts] entry, correct names, correct count --
    the direct check for the plan's Unit 2 Verification requirement."""
    output_dir = tmp_path / "pkg"
    expected_scripts = bwp._parse_project_scripts(REPO_ROOT)

    cli_shims_dir = bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)

    assert cli_shims_dir == output_dir / "scripts" / "cli-shims"
    generated = sorted(p.stem for p in cli_shims_dir.glob("*.bat"))
    assert generated == sorted(expected_scripts)
    assert len(generated) == len(expected_scripts)


def test_generate_cli_shims_bp_bat_content(tmp_path):
    output_dir = tmp_path / "pkg"
    cli_shims_dir = bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)

    bp_bat = (cli_shims_dir / "bp.bat").read_text(encoding="utf-8")
    assert '-c "import sys; from backlink_publisher.cli.bp import main; sys.exit(main())"' in bp_bat
    assert "-m backlink_publisher.cli.bp" not in bp_bat


def test_generate_cli_shims_every_shim_has_chcp_and_pythonpath(tmp_path):
    output_dir = tmp_path / "pkg"
    cli_shims_dir = bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)

    bat_files = list(cli_shims_dir.glob("*.bat"))
    assert bat_files, "expected at least one generated shim"
    for bat_path in bat_files:
        content = bat_path.read_text(encoding="utf-8")
        assert "chcp 65001" in content, f"{bat_path.name} missing chcp 65001"
        assert "PYTHONPATH=" in content, f"{bat_path.name} missing PYTHONPATH assignment"


# ── Pure-unit: existence check catches a broken target ─────────────────────


def test_check_script_targets_resolvable_passes_for_real_targets():
    scripts = bwp._parse_project_scripts(REPO_ROOT)
    # Keep this fast: check only a small real subset rather than all 49.
    subset = {name: scripts[name] for name in ("bp", "platform-health")}
    bwp._check_script_targets_resolvable(
        subset, python_exe=Path(sys.executable), repo_root=REPO_ROOT
    )  # must not raise


def test_check_script_targets_resolvable_raises_on_broken_module():
    broken = {"totally-broken-cmd": "backlink_publisher.cli.nonexistent_module_xyz:main"}
    with pytest.raises(bwp.BuildError, match="totally-broken-cmd"):
        bwp._check_script_targets_resolvable(
            broken, python_exe=Path(sys.executable), repo_root=REPO_ROOT
        )


def test_check_script_targets_resolvable_raises_on_missing_function():
    broken = {"bp-but-wrong-func": "backlink_publisher.cli.bp:this_function_does_not_exist"}
    with pytest.raises(bwp.BuildError, match="bp-but-wrong-func"):
        bwp._check_script_targets_resolvable(
            broken, python_exe=Path(sys.executable), repo_root=REPO_ROOT
        )


def test_generate_cli_shims_aborts_on_injected_broken_target(tmp_path, monkeypatch):
    """Error path (task-specified technique): monkeypatch the parsed scripts
    dict to inject a deliberately-broken target, rather than needing a real
    broken pyproject.toml on disk. Keep the injected dict small so this test
    stays fast (avoids running the existence check against all 49 real
    targets)."""

    def _fake_parse(repo_root: Path) -> dict[str, str]:
        return {
            "bp": "backlink_publisher.cli.bp:main",
            "broken-cmd": "backlink_publisher.cli.nonexistent_module_xyz:main",
        }

    monkeypatch.setattr(bwp, "_parse_project_scripts", _fake_parse)

    output_dir = tmp_path / "pkg"
    with pytest.raises(bwp.BuildError, match="broken-cmd"):
        bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)

    # Staging-then-move pattern (mirrors provision_interpreter): a failed
    # existence check must not leave a half-built cli-shims/ dir behind.
    assert not (output_dir / "scripts" / "cli-shims").exists()


# ── Pure-unit: ensure_app_dir_importable (the PYTHONPATH-doesn't-work fix) ─
#
# CRITICAL FINDING made while implementing this unit: the embeddable
# interpreter's ._pth file causes PYTHONPATH to be silently ignored
# entirely (verified empirically against a real provisioned python-embed/ --
# sys.path was byte-identical with and without PYTHONPATH set). The fix is
# to append a relative "..\app" line directly into the interpreter's own
# ._pth file, which IS honored. These tests use a fake ._pth file (no real
# interpreter needed) to check the file-editing logic in isolation; the
# real proof that this actually makes webui_store importable against a real
# python-embed/ is the real_packaging_build-gated integration tests below.


def _make_fake_python_embed(root: Path, pth_filename: str = "python311._pth") -> Path:
    embed_dir = root / "python-embed"
    embed_dir.mkdir(parents=True)
    (embed_dir / pth_filename).write_text(
        "python311.zip\r\nLib\\site-packages\r\n.\r\n\r\n"
        "# Uncomment to run site.main() automatically\r\nimport site\r\n",
        encoding="utf-8",
    )
    return embed_dir


def test_find_interpreter_pth_file_locates_the_pth(tmp_path):
    embed_dir = _make_fake_python_embed(tmp_path)
    found = bwp._find_interpreter_pth_file(embed_dir)
    assert found == embed_dir / "python311._pth"


def test_find_interpreter_pth_file_raises_if_missing(tmp_path):
    embed_dir = tmp_path / "python-embed"
    embed_dir.mkdir()
    with pytest.raises(bwp.BuildError, match="No \\*\\._pth file"):
        bwp._find_interpreter_pth_file(embed_dir)


def test_ensure_app_dir_importable_appends_relative_app_line(tmp_path):
    embed_dir = _make_fake_python_embed(tmp_path)
    bwp.ensure_app_dir_importable(embed_dir)

    content = (embed_dir / "python311._pth").read_text(encoding="utf-8")
    assert "..\\app" in content.splitlines()
    # The pre-existing "import site" line (Unit 1's own patch) must survive.
    assert "import site" in content


def test_ensure_app_dir_importable_is_idempotent(tmp_path):
    embed_dir = _make_fake_python_embed(tmp_path)
    bwp.ensure_app_dir_importable(embed_dir)
    bwp.ensure_app_dir_importable(embed_dir)

    content = (embed_dir / "python311._pth").read_text(encoding="utf-8")
    assert content.count("..\\app") == 1


def test_generate_cli_shims_auto_patches_pth_when_python_embed_present(tmp_path):
    """generate_cli_shims must call ensure_app_dir_importable automatically
    when python-embed/ already exists at the conventional sibling location
    -- the real Unit 5 orchestration order (Unit 1 then Unit 2)."""
    output_dir = tmp_path / "pkg"
    _make_fake_python_embed(output_dir)

    bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)

    content = (output_dir / "python-embed" / "python311._pth").read_text(encoding="utf-8")
    assert "..\\app" in content.splitlines()


def test_generate_cli_shims_skips_pth_patch_when_no_python_embed(tmp_path):
    """Standalone use (no python-embed/ present, e.g. this unit's own fast
    tests) must not error just because there's no interpreter to patch."""
    output_dir = tmp_path / "pkg"
    cli_shims_dir = bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)  # must not raise
    assert cli_shims_dir.is_dir()
    assert not (output_dir / "python-embed").exists()


# ── Pure-unit: launcher templates exist and carry required guards ──────────

_TEMPLATES_DIR = REPO_ROOT / "scripts" / "packaging" / "templates"


@pytest.mark.parametrize("template_name", ["launch-webui.bat.tmpl", "launch-cli.bat.tmpl"])
def test_launcher_template_has_utf8_and_pushd_and_pythonpath_guards(template_name):
    content = (_TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    assert "chcp 65001" in content
    assert "pushd" in content
    assert "PYTHONPATH=" in content

    # No actual "cd /d" *command* (REM commentary explaining the pushd
    # choice may still mention it) -- cd /d can't target a UNC path, pushd
    # can (see the plan's Key Technical Decisions).
    command_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().upper().startswith("REM")
    ]
    assert not any(line.upper().startswith("CD /D") for line in command_lines)


def test_launch_webui_template_has_port_fallback_range():
    content = (_TEMPLATES_DIR / "launch-webui.bat.tmpl").read_text(encoding="utf-8")
    assert "8888" in content
    assert "8907" in content


def test_launch_cli_template_prepends_cli_shims_to_path():
    content = (_TEMPLATES_DIR / "launch-cli.bat.tmpl").read_text(encoding="utf-8")
    assert "cli-shims" in content
    assert "PATH=" in content


# ── Real network + Windows integration tests (opt-in, never run in CI) ─────
#
# Reuses the exact gate from tests/packaging/test_build_windows_package.py.

_REAL_ENV = "BACKLINK_PUBLISHER_REAL_PACKAGING_BUILD"


def _real_packaging_build_enabled() -> bool:
    return os.environ.get(_REAL_ENV) == "1"


_real_skip = pytest.mark.skipif(
    sys.platform != "win32" or not _real_packaging_build_enabled(),
    reason=(
        "Real shim execution needs Windows (to run cmd /c *.bat) and a real "
        "provisioned python-embed/ (real network access downloading from "
        f"python.org + PyPI); set {_REAL_ENV}=1 on such a machine to run. "
        "Never runs in CI."
    ),
)


def _utf8_subprocess_env() -> dict[str, str]:
    """Force PYTHONIOENCODING=utf-8 for child processes whose stdout/stderr
    we capture via a pipe.

    `chcp 65001` inside the shims sets the *console* codepage, which is
    what makes real interactive double-click usage correct -- but when
    stdout is redirected to a pipe (as subprocess.PIPE does here, and as
    happens for any programmatic capture), Python's own text-I/O encoding
    falls back to the system ANSI codepage (cp950 on this machine) rather
    than being influenced by chcp at all. This is exactly the failure mode
    documented in `backlink_publisher._util.subprocess_env.utf8_child_env`
    (docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md) --
    reusing the same fix here rather than reimplementing it.
    """
    try:
        from backlink_publisher._util.subprocess_env import utf8_child_env

        return utf8_child_env()
    except ImportError:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return env


@pytest.fixture(scope="module")
def real_package_with_shims(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provision a real python-embed/ and generate real shims into the same
    package dir, shared by the tests below so the slow provisioning (a few
    minutes) happens once per session.

    Also stages a minimal `app/webui_store` by copying it from the repo --
    Unit 3 (package assembly) doesn't exist yet, and some CLI shims (e.g.
    dispatch-backlinks) import webui_store at module load time, so actually
    *executing* those shims needs `app/` to physically contain it, not just
    be listed in the interpreter's ._pth (see ensure_app_dir_importable's
    docstring for why PYTHONPATH alone does not make this work).

    The existence check inside generate_cli_shims deliberately uses the
    DEFAULT `verify_python_exe` (sys.executable, not python-embed's
    python.exe): checking against python-embed here would fail for
    webui_store-importing commands regardless of any ._pth patch, simply
    because `app/webui_store` doesn't exist on disk yet at this point in the
    real Unit 1 -> Unit 2 -> Unit 3 build order -- that's a separate,
    correct reason for the check to fail, distinct from what we're trying to
    prove with the tests below (that shims which import webui_store resolve
    fine once `app/` is actually populated).
    """
    if sys.platform != "win32" or not _real_packaging_build_enabled():
        pytest.skip("real packaging build not enabled — see _real_skip reason")

    try:
        from pytest_socket import enable_socket

        enable_socket()
    except ImportError:
        pass

    # NOTE: provision_interpreter's `output_dir` param IS the python-embed/
    # directory itself (python.exe lands at output_dir/python.exe directly)
    # -- NOT a package root containing a python-embed/ subdir. Callers must
    # pass a path ending in "python-embed" (matching main()'s own default:
    # `dist/_python-embed-build/python-embed`) to get the Output Structure's
    # <pkg_dir>/python-embed/python.exe layout.
    output_dir = tmp_path_factory.mktemp("real-cli-shims") / "pkg"
    bwp.provision_interpreter(output_dir / "python-embed", repo_root=REPO_ROOT)
    bwp.generate_cli_shims(output_dir, repo_root=REPO_ROOT)

    # Stand in for Unit 3's future "copy webui_store/ into app/" assembly
    # step, scoped narrowly to what these integration tests need.
    app_dir = output_dir / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / "webui_store", app_dir / "webui_store")

    return output_dir


@pytest.mark.real_packaging_build
@_real_skip
def test_real_shim_with_main_guard_runs_and_produces_output(real_package_with_shims: Path) -> None:
    """`bp` HAS a __main__ guard -- baseline: the shim mechanism itself works."""
    bp_bat = real_package_with_shims / "scripts" / "cli-shims" / "bp.bat"
    result = subprocess.run(
        ["cmd", "/c", str(bp_bat)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_utf8_subprocess_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "backlink-publisher" in result.stdout.lower() or "available commands" in result.stdout.lower()


@pytest.mark.real_packaging_build
@_real_skip
def test_real_shim_without_main_guard_runs_and_produces_output(
    real_package_with_shims: Path,
) -> None:
    """`platform-health` has NO __main__ guard in its source module -- this
    is the single most important test in this unit: it directly proves the
    'python -m silently no-ops' bug the plan review caught is fixed, by
    actually executing the shim and asserting real output + exit 0 rather
    than a silent no-op."""
    shim = real_package_with_shims / "scripts" / "cli-shims" / "platform-health.bat"
    result = subprocess.run(
        ["cmd", "/c", str(shim), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_utf8_subprocess_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), (
        "platform-health.bat produced no output at all -- this is exactly "
        "the silent-no-op failure mode `python -m` would have caused"
    )
    assert "platform" in result.stdout.lower()


@pytest.mark.real_packaging_build
@_real_skip
def test_real_shim_restore_state_without_main_guard_runs(real_package_with_shims: Path) -> None:
    """restore-state maps a second function from the SAME module as
    backup-state (state_backup.py), with no __main__ guard -- confirms the
    module:function targeting resolves the correct one of the two."""
    shim = real_package_with_shims / "scripts" / "cli-shims" / "restore-state.bat"
    result = subprocess.run(
        ["cmd", "/c", str(shim), "--list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_utf8_subprocess_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() or result.stderr.strip()


@pytest.mark.real_packaging_build
@_real_skip
def test_real_shim_dispatch_backlinks_reaches_webui_store(
    real_package_with_shims: Path,
) -> None:
    """dispatch-backlinks imports webui_store.channel_status at module load
    time. Proves `app/` is importable against the shipped python-embed/
    interpreter: the shim must get PAST the import stage without
    ModuleNotFoundError. (NOTE the mechanism that actually makes this work
    is ensure_app_dir_importable's `._pth` patch, not the shim's own
    `set PYTHONPATH=...` line -- see that function's docstring for why
    PYTHONPATH is silently ignored by the embeddable interpreter; the shim
    still sets it for compatibility if ever run under a normal Python.) It
    may still fail for other reasons (no real pipeline input piped to
    stdin, no config) -- that's fine, only the import-stage success is
    asserted here."""
    shim = real_package_with_shims / "scripts" / "cli-shims" / "dispatch-backlinks.bat"
    result = subprocess.run(
        ["cmd", "/c", str(shim), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_utf8_subprocess_env(),
    )
    combined = (result.stdout + result.stderr).lower()
    assert "modulenotfounderror" not in combined
    assert "no module named 'webui_store'" not in combined
    assert result.returncode == 0, result.stderr
