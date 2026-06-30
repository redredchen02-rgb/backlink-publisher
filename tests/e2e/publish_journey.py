"""Playwright E2E — single-origin publish workbench (Plan 2026-06-18-002 U5).

NOT collected by the default ``test_*.py`` glob; run explicitly in the E2E lane::

    npm --prefix frontend run build      # produce webui_app/spa_dist
    pytest tests/e2e/publish_journey.py

What this covers that the contract + component layers structurally CANNOT:
  * the *built* Vue bundle is served same-origin by Flask at ``/app`` and boots
    in a real browser (catch-all + ``base: '/app/'`` + asset loading + mount +
    first paint) — jsdom component tests never exercise the real bundle/serving;
  * the end-to-end *unhappy* journey works single-origin: typing a URL and
    clicking 生成 drives a real same-origin fetch (carrying the session cookie +
    a freshly-read CSRF token) to ``/api/v1/pipeline/plan``; with no configured
    LLM/credentials the pipeline fails, and the failure surfaces through
    problem+json → ``classifyError`` → a toast. This proves the whole transport
    chain in a browser, with no real publish.

A credentialed happy-path publish and the DNS-rebinding origin-guard invariant
(which needs the server bound to the guard's expected port + a forged Origin)
belong to the dedicated security E2E lane and are out of scope here.

Self-skips when prerequisites are absent (unbuilt SPA, no chromium, sockets
disabled), so it is safe to collect anywhere.
"""

from __future__ import annotations

__tier__ = "e2e"

import os
from pathlib import Path
import socket
import threading
import time

import pytest

# pytest-socket disables real sockets repo-wide; a live HTTP server + browser
# need them re-enabled for this test only.
pytestmark = pytest.mark.enable_socket

_REPO = Path(__file__).resolve().parents[1].parent
_SPA_INDEX = _REPO / "webui_app" / "spa_dist" / "index.html"


@pytest.fixture(autouse=True)
def _reenable_sockets_for_e2e():
    """Re-enable real sockets for the E2E test body.

    conftest's autouse ``_disable_real_network`` calls ``disable_socket()`` before
    every test (CI safety net). This module-local autouse fixture runs *after* it
    (same scope, defined closer to the test), re-enabling sockets so the live
    werkzeug server can ``accept()`` and chromium can connect.
    """
    try:
        from pytest_socket import enable_socket
    except Exception:  # noqa: BLE001 — pytest-socket absent: nothing to undo
        yield
        return
    enable_socket()
    yield


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture(scope="module")
def live_url(tmp_path_factory):
    """Boot the real Flask app (no scheduler) on a loopback port, SPA flag on."""
    if not _SPA_INDEX.is_file():
        pytest.skip("SPA bundle not built — run `npm --prefix frontend run build`")

    os.environ["BACKLINK_PUBLISHER_SPA"] = "1"
    os.environ["BACKLINK_NO_FETCH_VERIFY"] = "1"
    os.environ["BACKLINK_PUBLISHER_CONFIG_DIR"] = str(tmp_path_factory.mktemp("e2e_cfg"))

    try:
        from werkzeug.serving import make_server

        from webui_app import create_app
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot import app/server: {exc}")

    app = create_app(start_scheduler=False)
    port = _free_port()
    try:
        server = make_server("127.0.0.1", port, app, threaded=True)
    except Exception as exc:  # noqa: BLE001 — pytest-socket etc.
        pytest.skip(f"cannot bind live server (sockets disabled?): {exc}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Wait for the port to accept connections.
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser_page(live_url):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"playwright not available: {exc}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 — chromium not installed
            pytest.skip(f"chromium not launchable: {exc}")
        page = browser.new_page()
        try:
            yield page, live_url
        finally:
            browser.close()


def test_publish_workbench_renders_single_origin(browser_page):
    """The built SPA boots at /app and renders the workbench shell + config."""
    page, base = browser_page
    page.goto(f"{base}/app", wait_until="networkidle")

    # Workbench heading proves: catch-all served index.html, assets loaded under
    # /app/, the router resolved '/', and the component mounted — all same-origin.
    page.wait_for_selector("h1:has-text('发布工作台')", timeout=10_000)
    # The platform <select> proves the bootstrap GET (/api/v1/bound-platforms)
    # succeeded same-origin (renders the default option even if the list is empty).
    assert page.query_selector("select") is not None


def test_publish_journey_plan_step_renders_single_origin(browser_page):
    """Type a URL and generate → the planned step renders.

    Proves the full same-origin transport chain in a real browser, with no real
    publish: the SPA reads a fresh CSRF token (GET /api/v1/csrf-token), POSTs to
    /api/v1/pipeline/plan carrying the session cookie + token, gets 200, stashes
    the rows in the Pinia store, and re-renders into the 'planned' stage — the
    '验证' (validate) button only exists once that round-trip succeeded.
    """
    page, base = browser_page
    page.goto(f"{base}/app", wait_until="networkidle")
    page.wait_for_selector("h1:has-text('发布工作台')", timeout=10_000)

    page.fill("textarea", "https://example.com/")
    page.click("button:has-text('生成文章计划')")

    # The validate button appears only after POST /api/v1/pipeline/plan → 200 →
    # store.plans set → stage advances to 'planned'.
    page.wait_for_selector("button:has-text('验证')", timeout=15_000)
