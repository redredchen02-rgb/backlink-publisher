"""render_to_html_safe sanitizes raw HTML for operator-facing previews (audit [26][27]).

render_to_html uses MarkdownIt('commonmark') with html:True, so raw HTML in the
(LLM-generated) markdown passes through verbatim. Fed into the admin plan preview
via `| safe` and into profiles.js `preview.innerHTML`, that is stored/DOM XSS.
render_to_html_safe disables raw-HTML passthrough (html:False) for previews while
render_to_html keeps passthrough for the actual publish path.
"""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher._util.markdown import render_to_html, render_to_html_safe


def test_safe_renderer_escapes_script_and_event_handler_html():
    out = render_to_html_safe("hi <script>alert(1)</script> <img src=x onerror=alert(2)>")
    assert "<script>" not in out
    assert "<img" not in out  # raw tag escaped, not emitted as a live element
    # content is escaped (not silently dropped)
    assert "alert(1)" in out


def test_safe_renderer_still_renders_real_markdown():
    out = render_to_html_safe("**bold** and [link](https://example.com/x)")
    assert "<strong>bold</strong>" in out
    assert 'href="https://example.com/x"' in out


def test_safe_renderer_drops_javascript_url():
    # markdown-it's link validator refuses javascript: — no anchor/href is emitted
    # (the text is left inert). The security property is "no javascript href".
    out = render_to_html_safe("[click](javascript:alert(1))")
    assert 'href="javascript' not in out.lower()


def test_publish_renderer_still_passes_raw_html_through():
    # The publish path intentionally keeps HTML passthrough for real articles.
    out = render_to_html("<div class=\"box\">hello</div>")
    assert "<div" in out
