"""Tests for scripts/optimize_static.py."""

from __future__ import annotations

import pathlib
import textwrap

from scripts.optimize_static import _minify_css, _minify_js


def test_minify_css_removes_comments() -> None:
    src = "/* header */ body { color: red; } /* footer */"
    result = _minify_css(src)
    assert "/*" not in result
    assert "body" in result


def test_minify_css_removes_extra_whitespace() -> None:
    src = "body   {  color :  red;  }"
    result = _minify_css(src)
    # Should compress spaces around braces/colons/semicolons
    assert "  " not in result


def test_minify_css_strips_trailing_semicolon_in_block() -> None:
    src = "div { margin: 0; padding: 0; }"
    result = _minify_css(src)
    assert result == "div{margin:0;padding:0}"


def test_minify_js_removes_single_line_comments() -> None:
    src = textwrap.dedent("""\
        // this is a comment
        var x = 1;
    """)
    result = _minify_js(src)
    assert "//" not in result
    assert "var x = 1" in result or "var x=1" in result


def test_minify_js_removes_block_comments() -> None:
    src = "/* block */ var x = 1; /* end */"
    result = _minify_js(src)
    assert "/*" not in result


def test_minify_js_compresses_whitespace() -> None:
    src = "function  foo (  x  )  {  return  x  ;  }"
    result = _minify_js(src)
    assert "  " not in result


def test_minify_css_preserves_content() -> None:
    src = textwrap.dedent("""\
        .my-class {
            color: #333;
            font-size: 14px;
        }
    """)
    result = _minify_css(src)
    assert ".my-class" in result
    assert "#333" in result
    assert "14px" in result


def test_minify_empty_content() -> None:
    assert _minify_css("") == ""
    assert _minify_js("") == ""
