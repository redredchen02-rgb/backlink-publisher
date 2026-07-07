"""scripts/launcher.ps1 mojibake fix -- static-content regression guard.

Windows PowerShell 5.1 (Desktop edition) decodes a BOM-less .ps1 file's
literal characters using the system ANSI code page at *parse* time, before
[Console]::OutputEncoding has any effect. A real behavioral test needs an
actual non-UTF-8-locale Windows PowerShell host (infeasible on this repo's
ubuntu-only CI), so this asserts the two static invariants that keep the
fix in place: the UTF-8 BOM survives, and the OutputEncoding line survives.
"""
from __future__ import annotations

__tier__ = "unit"
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_PS1 = _REPO_ROOT / "scripts" / "launcher.ps1"

_UTF8_BOM = b"\xef\xbb\xbf"


def test_launcher_ps1_has_utf8_bom():
    raw = _LAUNCHER_PS1.read_bytes()
    assert raw.startswith(_UTF8_BOM), (
        "scripts/launcher.ps1 lost its UTF-8 BOM -- PowerShell 5.1 will "
        "mis-decode its literal Chinese strings under a non-UTF-8 system "
        "code page again if this file is ever re-saved without it."
    )


def test_launcher_ps1_sets_console_output_encoding():
    body = _LAUNCHER_PS1.read_text(encoding="utf-8-sig")
    assert "[Console]::OutputEncoding" in body
    assert "UTF8" in body
