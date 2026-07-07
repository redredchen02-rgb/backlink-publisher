"""R9 — single canonical launcher (plan 2026-06-04-001 Unit 11).

The repo ships exactly one launcher, ``scripts/launcher.command``, and it must
keep the Unit 2 fail-safe runtime posture (FLASK_DEBUG off by default, a pinned
persistent SECRET_KEY). This is the in-repo half of R9; the workspace-root
``Makefile`` / ``restart_webui.sh`` / ``启动WebUI.command`` rewire is an
operator ops step (those files live outside the git repo).
"""
__tier__ = "unit"

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO_ROOT / "scripts" / "launcher.command"


def test_exactly_one_command_launcher_in_repo():
    launchers = [p for p in _REPO_ROOT.rglob("*.command") if ".git" not in p.parts]
    assert launchers == [_LAUNCHER], f"expected one canonical launcher, got {launchers}"


def test_launcher_is_executable():
    import os
    assert os.access(_LAUNCHER, os.X_OK)


def test_launcher_pins_failsafe_debug_and_secret_key():
    body = _LAUNCHER.read_text(encoding="utf-8")
    # Unit 2 security invariants must survive at the launcher level.
    assert "export FLASK_DEBUG=0" in body
    assert "SECRET_KEY" in body
    assert "umask 077" in body          # secret file written 0600, not world-readable


def test_launcher_activates_lite_edition():
    # R7/R8: the canonical launcher is the one place that turns the LITE surface
    # reduction on (edition.py documents the launcher as the activation point).
    # Without this export the operator would silently get the full Pro surface.
    body = _LAUNCHER.read_text(encoding="utf-8")
    assert "export BACKLINK_PUBLISHER_LITE=1" in body


def test_launcher_self_identifies_as_canonical():
    body = _LAUNCHER.read_text(encoding="utf-8")
    assert "canonical" in body.lower()


def test_launcher_defaults_to_production_entrypoint():
    # Plan 2026-07-07-002: the dev-server warning the operator sees on every
    # launch is closed by defaulting to serve.py (waitress), not webui.py
    # (Werkzeug dev server). The override mechanism stays intact for the
    # manual crash-stub test.
    body = _LAUNCHER.read_text(encoding="utf-8")
    assert 'WEBUI_SCRIPT="${WEBUI_SCRIPT:-serve.py}"' in body

