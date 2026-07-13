"""Legacy static-JS modules must import every api helper they call (audit [17]).

copilot.js called postJson() but imported only fetchJson from ./lib/api.js, so the
bare postJson reference threw ReferenceError at runtime (caught + surfaced as an
error to any operator who had bound an LLM key). This guard asserts every
static/js module imports (or locally defines) each api helper it invokes, so the
class cannot regress.
"""
from __future__ import annotations

__tier__ = "unit"

import re
from pathlib import Path

import pytest

_API_HELPERS = ("fetchJson", "postJson", "putJson", "deleteJson", "patchJson")
_JS_ROOT = Path(__file__).resolve().parent.parent / "webui_app" / "static" / "js"

_IMPORT_BRACES = re.compile(r"import\s*\{([^}]*)\}\s*from", re.DOTALL)
_LOCAL_DEF = re.compile(r"\b(?:function|const|let|var)\s+(\w+)")


def _js_files() -> list[Path]:
    return sorted(p for p in _JS_ROOT.rglob("*.js") if "node_modules" not in p.parts)


def _imported_or_defined(src: str) -> set[str]:
    names: set[str] = set()
    for brace in _IMPORT_BRACES.findall(src):
        for token in brace.split(","):
            token = token.strip()
            if not token:
                continue
            # handle `foo as bar` -> the local binding is `bar`
            local = token.split(" as ")[-1].strip()
            names.add(local)
    names.update(_LOCAL_DEF.findall(src))
    return names


@pytest.mark.parametrize("js", _js_files(), ids=lambda p: p.name)
def test_static_js_imports_every_api_helper_it_calls(js: Path):
    src = js.read_text(encoding="utf-8")
    available = _imported_or_defined(src)
    missing = [
        h for h in _API_HELPERS
        if re.search(rf"\b{h}\s*\(", src) and h not in available
    ]
    assert not missing, (
        f"{js.relative_to(_JS_ROOT.parent.parent)} calls {missing} but never imports "
        f"them (add to the './lib/api.js' import) — ReferenceError at runtime."
    )
