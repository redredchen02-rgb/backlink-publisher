"""Permanent guard: SPA and legacy Jinja must persist theme under the same key.

Audit finding [39]: the Vue SPA store used localStorage key 'bp-theme' while the
legacy Jinja theme.js used 'backlink-publisher-theme'. Both drive <html data-theme>
over the shared tokens.css, but neither read the other's key, so in this dual-stack
app the theme silently reset on every SPA<->Jinja crossing (card deep-links, nav
search entries, sidenav legacy links all trigger full cross-boundary navigation).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TS = _REPO / "frontend" / "src" / "stores" / "theme.ts"
_JS = _REPO / "webui_app" / "static" / "js" / "theme.js"


def _primary_key(path: Path, varname: str) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"const\s+{varname}\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert m, f"{varname} not found in {path.name}"
    return m.group(1)


def test_spa_and_legacy_theme_use_same_storage_key() -> None:
    ts_key = _primary_key(_TS, "STORAGE_KEY")
    js_key = _primary_key(_JS, "THEME_KEY")
    assert ts_key == js_key, (
        f"SPA theme store persists under {ts_key!r} but legacy theme.js uses "
        f"{js_key!r}; the theme silently resets on every SPA<->Jinja navigation. "
        f"Standardize both on one canonical localStorage key."
    )
