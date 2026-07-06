"""Three-state feedback consistency + error taxonomy — Plan 2026-06-18-001 U4 (R4).

Zero-build ESM has no in-process JS runner, so (like test_webui_empty_state.py)
the wiring/anti-rot assertions read the served JS source. The taxonomy's runtime
behaviour, however, is *the* deliverable — so where `node` is available we import
the REAL ui/errors.js (no inlined copy to drift) and assert classifyError's
category mapping directly:

  - a TypeError / network failure          -> 'network'
  - a 403 / 419 (CSRF / session)           -> 'permission'
  - a 500                                  -> 'server'
  - an unrecognized failure                -> 'unknown' fallback
  every result carries a non-empty title + message from a FIXED template (never
  raw server text), and the core renderError call-sites route through it so the
  copy is identical across pages — no bare「加载失败」literal remains as the source.

Integration: a failed monitor-hub fetch lands in renderError WITH a retry that
re-invokes the loader (skeleton -> error -> retry -> data).
"""
from __future__ import annotations

__tier__ = "unit"

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from webui_app import create_app

_JS_DIR = Path(__file__).resolve().parents[1] / "webui_app" / "static" / "js"
_ERRORS_JS = (_JS_DIR / "ui" / "errors.js").read_text(encoding="utf-8")
_MONITOR_JS = (_JS_DIR / "monitor_hub.js").read_text(encoding="utf-8")
_INDEX_JS = (_JS_DIR / "index.js").read_text(encoding="utf-8")
_STATES_JS = (_JS_DIR / "ui" / "states.js").read_text(encoding="utf-8")

_NODE = shutil.which("node")
_needs_node = pytest.mark.skipif(_NODE is None, reason="node not available for ESM runtime checks")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    # GET-only tests (served static JS + rendered pages); CSRF guards mutating
    # methods only, so no CSRF toggle is needed (and raw mutation is gated).
    return app.test_client()


def _classify(input_expr: str) -> dict:
    """Import the REAL errors.js in node and classify `input_expr` (a JS expr)."""
    url = (_JS_DIR / "ui" / "errors.js").as_uri()
    driver = (
        f"import {{ classifyError }} from {json.dumps(url)};\n"
        f"globalThis.process.stdout.write(JSON.stringify(classifyError({input_expr})));\n"
    )
    out = subprocess.run(
        [_NODE, "--input-type=module", "-e", driver],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert out.returncode == 0, f"node failed: {out.stderr}"
    return json.loads(out.stdout)


# ── the served module + the finite category set ────────────────────────────

def test_errors_js_served_and_exports_classifier(client):
    """ui/errors.js is served and exports classifyError + the finite CATEGORIES set."""
    resp = client.get("/static/js/ui/errors.js")
    assert resp.status_code == 200
    assert "javascript" in resp.content_type
    assert "export function classifyError" in _ERRORS_JS
    # The taxonomy is a CLOSED set of exactly these four categories.
    m = re.search(r"export const CATEGORIES\s*=\s*(\[[^\]]*\])", _ERRORS_JS)
    assert m, "CATEGORIES export not found"
    cats = set(re.findall(r"'([a-z]+)'", m.group(1)))
    assert cats == {"network", "permission", "server", "unknown"}


# ── classifyError runtime mapping (the unit's core deliverable) ─────────────

@_needs_node
def test_classify_network_from_typeerror():
    r = _classify("new TypeError('Failed to fetch')")
    assert r["category"] == "network"
    assert r["title"] and r["message"]


@_needs_node
def test_classify_permission_from_403_and_419():
    for status in (401, 403, 419):
        r = _classify(f"{{ ok: false, status: {status} }}")
        assert r["category"] == "permission", status
        assert r["title"] and r["message"]


@_needs_node
def test_classify_server_from_5xx():
    r = _classify("{ status: 500 }")
    assert r["category"] == "server"
    assert r["title"] and r["message"]
    # a thrown non-JSON HTTP 503 (fetchJson bakes the code into the message) too
    r2 = _classify("new Error('服务器返回非 JSON 响应 (HTTP 503 text/html)')")
    assert r2["category"] == "server"


@_needs_node
def test_classify_unknown_fallback():
    # No status, not a network signal -> unknown fallback, still non-empty copy.
    r = _classify("{ ok: false, error: 'weird' }")
    assert r["category"] == "unknown"
    assert r["title"] and r["message"]
    r2 = _classify("undefined")
    assert r2["category"] == "unknown"
    assert r2["title"] and r2["message"]


@_needs_node
def test_every_category_yields_nonempty_title_and_message():
    cases = ["new TypeError('x')", "{ status: 403 }", "{ status: 502 }", "{ status: 418 }"]
    for expr in cases:
        r = _classify(expr)
        assert isinstance(r["title"], str) and r["title"].strip()
        assert isinstance(r["message"], str) and r["message"].strip()


@_needs_node
def test_classify_does_not_leak_raw_server_text_into_message():
    """A hostile server `error` string must NOT appear verbatim in title/message —
    those come only from the fixed template. (detail may carry sanitized text.)"""
    payload = "{ status: 500, error: '<img src=x onerror=alert(1)>' }"
    r = _classify(payload)
    assert "<img" not in r["title"]
    assert "<img" not in r["message"]
    assert "onerror" not in r["message"]


@_needs_node
def test_detail_is_sanitized_and_capped():
    """detail strips control chars and caps length (can't bloat/garble the UI)."""
    r = _classify(r"{ status: 500, error: 'line1\nline2\t' + 'x'.repeat(500) }")
    assert "\n" not in r["detail"] and "\t" not in r["detail"]
    assert len(r["detail"]) <= 140


# ── call-sites route through the taxonomy (no bare ad-hoc strings) ──────────

def test_monitor_hub_imports_and_uses_classify_error():
    """monitor_hub routes BOTH error paths through classifyError — the old ad-hoc
    「加载失败」/「聚合不可用」titles are no longer the message source."""
    assert "import { classifyError } from './ui/errors.js'" in _MONITOR_JS
    assert "classifyError(" in _MONITOR_JS
    # The ad-hoc literals must not survive as the renderError title source.
    assert "title: '加载失败'" not in _MONITOR_JS
    assert "title: '聚合不可用'" not in _MONITOR_JS
    # Both failure branches now feed the shared helper.
    assert _MONITOR_JS.count("showError(") >= 2


def test_index_error_path_routes_through_classify_error():
    assert "import { classifyError } from './ui/errors.js'" in _INDEX_JS
    assert "classifyError(err)" in _INDEX_JS
    # The page-state error still renders renderError with a retry.
    assert "renderError(container" in _INDEX_JS
    assert "onRetry: () => window.location.reload()" in _INDEX_JS


# ── health bar: "never published yet" vs a real degraded state (Plan 2026-07-02-001 U15 B2) ──

def test_health_bar_distinguishes_never_published_from_real_degraded():
    """_initHealthBar shows the neutral 'pending' state (not the alarming
    'degraded' state) ONLY when degraded_reasons is exactly ['pipeline:never_run'].
    Any other or additional reason must still render as 'degraded' -- the safe
    case is allowlisted, not the dangerous case denylisted, so an unrecognized
    future reason code defaults to the alarming treatment rather than silently
    being treated as safe (see docs/solutions/logic-errors/
    projector-silent-drop-status-vocabulary-drift-2026-05-26.md for why the
    inverse would be unsafe)."""
    assert "reasons.length === 1 && reasons[0] === 'pipeline:never_run'" in _INDEX_JS
    assert "bar.classList.toggle('pending', neverPublished)" in _INDEX_JS
    assert "bar.classList.toggle('degraded', !healthy && !neverPublished)" in _INDEX_JS


def test_health_bar_pending_state_has_distinct_icon_and_copy():
    """The pending state gets its own icon/copy -- never falls back to the
    alarming "系统降级" text used for a genuine failure."""
    assert "icon.textContent = healthy ? '✅' : (neverPublished ? 'ℹ️' : '⚠️')" in _INDEX_JS
    assert "尚未发布任何内容" in _INDEX_JS
    assert "系统降级" in _INDEX_JS  # the alarming copy still exists for real degraded states


def test_health_bar_pending_css_reuses_info_soft_token():
    """.pending reuses the existing --info-soft token -- no new raw color literal,
    so tests/test_webui_css_no_raw_colors.py's ceiling budget is untouched."""
    css = (_JS_DIR.parent / "css" / "index.css").read_text(encoding="utf-8")
    assert ".health-summary-bar.pending" in css
    assert "background: var(--info-soft);" in css


def test_health_bar_never_run_literal_matches_backend():
    """index.js's neverPublished check hardcodes the same 'pipeline:never_run'
    string health_projection.py emits for an empty publish history. If either
    side is ever renamed without the other, this test fails loudly instead of
    the presentational fix silently regressing to always showing 'degraded'."""
    backend_src = (
        Path(__file__).resolve().parents[1] / "webui_app" / "services" / "health_projection.py"
    ).read_text(encoding="utf-8")
    assert '"pipeline:never_run"' in backend_src
    assert "reasons[0] === 'pipeline:never_run'" in _INDEX_JS


def test_health_bar_fetch_resolution_rechecks_dismiss_before_showing():
    """backlog B5 (found in B2's code review): the /health fetch's .then()
    callback must re-check the dismiss flag before removing 'd-none' -- else a
    response that resolves after the user clicks dismiss silently un-hides the
    bar they just closed. The check must appear a second time (inside the
    callback), not just once at _initHealthBar's own top (which only guards
    against starting the fetch at all, not a late-resolving one already in
    flight when the user dismisses)."""
    dismiss_check = (
        "try { if (sessionStorage.getItem(DISMISS_KEY)) return; } catch (_) { /* ignore */ }"
    )
    assert _INDEX_JS.count(dismiss_check) == 2

    # Anchor to POSITION, not just count: a whole-file count of 2 would also
    # pass if the second occurrence sat somewhere unrelated -- e.g. right
    # after the dismiss-button handler instead of inside the fetch's .then().
    # Pin it specifically inside the fetchJson('/health').then((data) => {
    # ... }) callback body, which is the actual guard this test is about.
    start_marker = "fetchJson('/health').then((data) => {"
    start = _INDEX_JS.index(start_marker) + len(start_marker)
    end = _INDEX_JS.index("}).catch(", start)
    callback_body = _INDEX_JS[start:end]
    assert dismiss_check in callback_body


# test_settings_error_path_routes_through_classify_error removed — settings.js
# retired in U8 (Plan 2026-06-18-002).

# ── concurrency: rapid refresh must not render stale (out-of-order) data ────

def test_monitor_hub_load_guards_against_out_of_order_render():
    """Rapid refresh (or refresh racing the initial load) fires concurrent
    load()s. The loader aborts the prior in-flight fetch and drops any response
    whose controller was superseded, so a slower EARLIER request can't overwrite
    a faster LATER one. Lock the AbortController guard in source."""
    # A fresh controller per load, and the prior one is aborted on re-entry.
    assert "new AbortController()" in _MONITOR_JS
    assert ".abort()" in _MONITOR_JS
    # The signal is actually threaded into the fetch (else abort is inert).
    assert "signal: ctrl.signal" in _MONITOR_JS
    # Superseded responses are dropped on BOTH paths: the abort-reject in catch
    # and the post-await check before rendering.
    assert _MONITOR_JS.count("ctrl.signal.aborted") >= 2


# ── loading consistency: core lists use renderSkeleton ─────────────────────

def test_monitor_hub_loading_uses_skeleton():
    """The core monitor list shows the shared skeleton while loading (not a bare
    spinner / blank), keeping the three-state flow uniform."""
    assert "renderSkeleton(grid" in _MONITOR_JS


# ── integration: full three-state flow + retry re-invokes the loader ───────

def test_monitor_hub_full_three_state_flow_with_retry():
    """skeleton -> renderError(onRetry: load) -> renderEmpty -> data, with the
    retry button re-invoking the same loader (load)."""
    assert "renderSkeleton(grid" in _MONITOR_JS      # loading
    assert "onRetry: load" in _MONITOR_JS            # error -> retry re-runs load()
    assert "renderEmpty(grid" in _MONITOR_JS         # empty
    assert "grid.replaceChildren(...cards" in _MONITOR_JS  # data
    # error is built from the taxonomy, not an inline literal title.
    assert "title: c.title" in _MONITOR_JS and "message: c.message" in _MONITOR_JS


# ── boundary doc + anti-rot ────────────────────────────────────────────────

def test_toast_vs_inline_boundary_documented():
    """The toast-vs-inline boundary is stated in a code comment (region load
    failure -> inline renderError; transient action feedback -> toast)."""
    blob = _ERRORS_JS + _MONITOR_JS
    assert "toast" in blob.lower()
    assert "inline" in blob.lower() or "renderError" in blob


def test_no_inline_on_handlers_in_taxonomy_and_callsites():
    for src in (_ERRORS_JS, _MONITOR_JS):
        assert not re.search(r"""['"]on(click|change|submit|input|keyup)['"]\s*:""", src)


def test_taxonomy_has_no_window_api_global():
    """errors.js exposes no window.* API surface (cross-component via CustomEvent,
    per anti-rot). It is a pure module: import classifyError, no globals."""
    assert "window." not in _ERRORS_JS


def test_error_copy_rides_textcontent_not_innerhtml():
    """renderError renders title/message via textContent; the taxonomy never hands
    markup to innerHTML, and no call-site assembles the error card via innerHTML."""
    assert "text: title" in _STATES_JS and "text: message" in _STATES_JS
    # The taxonomy never assigns innerHTML at all (it produces strings only).
    assert not re.search(r"\.innerHTML\s*=", _ERRORS_JS)
    # The error call-sites don't hand-build the error card markup; they pass the
    # classified strings to renderError, which renders via textContent.
    for src in (_MONITOR_JS, _INDEX_JS):
        assert "ui-error__" not in src
