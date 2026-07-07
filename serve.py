#!/usr/bin/env python3
"""Backlink Publisher WebUI — production WSGI entrypoint (waitress).

Plan 2026-07-07-002. Thin production launcher: reuses the exact Flask
``app`` instance built by ``webui.py`` and serves it via waitress instead
of the Werkzeug development server. ``python webui.py`` remains the
interactive/debug entrypoint (e.g. for ``FLASK_DEBUG=1``); launchers meant
to run "for real" use this instead.

Run with ``python serve.py``. Same bind/port env vars as webui.py
(``PORT``, ``BIND_HOST`` — loopback-only, enforced by
``_resolve_bind_host()``), plus ``WSGI_THREADS`` (default ``1`` — see
``_resolve_threads()``).
"""

from __future__ import annotations

import os

from flask import Flask
import waitress

from webui import app
from webui_app.helpers.cli_runner import _wire_content_fetch_ttl_from_env
from webui_app.helpers.security import _resolve_bind_host

_DRAFTS_GAP_NOTE = (
    "webui_app/routes/drafts.py: the legacy POST /ce:draft/bulk-publish-now "
    "route has no single-flight lock -- it is only safe today because "
    "requests are served one at a time. WSGI_THREADS>1 makes that a live "
    "double-schedule race."
)


def _resolve_threads() -> int:
    """Waitress worker-thread count. Default 1 -- see plan Key Technical Decisions.

    Defaulting to 1 preserves the exact request serialization webui.py's
    unthreaded ``app.run()`` already provides today, so this entrypoint adds
    no new concurrency exposure. Raising it is a legitimate future choice,
    but only after closing the drafts.py gap this default stands in for.

    Rejects values below 1 -- waitress's own thread dispatcher never starts a
    worker when ``threads<=0``, which would silently hang every request
    forever (strictly worse than the race this default guards against).
    """
    raw = os.environ.get('WSGI_THREADS', '1')
    try:
        threads = int(raw)
    except ValueError:
        raise ValueError(
            f"WSGI_THREADS must be a positive integer, got: {raw!r}"
        ) from None
    if threads < 1:
        raise ValueError(
            f"WSGI_THREADS must be a positive integer, got: {threads} "
            "(threads<=0 makes waitress accept connections but never "
            "service them, hanging every request)"
        )
    return threads


def _force_production_debug_off(flask_app: Flask) -> None:
    """Hard-disable Flask debug mode, independent of ``FLASK_DEBUG``.

    Waitress has no Werkzeug-style interactive debugger, but leaving
    ``app.debug`` on risks verbose tracebacks leaking into error responses.
    Defense in depth rather than trusting env-var hygiene at every call site.
    """
    flask_app.debug = False


def _warn_if_multithreaded(threads: int) -> str | None:
    """Return (and print) a loud warning when ``threads`` risks the drafts.py race.

    A warning, not a hard refusal -- raising thread count is a legitimate
    future choice once the drafts.py gap is closed; this just makes the
    tradeoff visible at the moment of misconfiguration instead of only in
    source comments. Returns the warning text (or ``None``) so callers/tests
    don't have to scrape stdout.
    """
    if threads <= 1:
        return None
    message = f"WARNING: WSGI_THREADS={threads} -- {_DRAFTS_GAP_NOTE}"
    print(message)
    return message


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    _wire_content_fetch_ttl_from_env()
    _force_production_debug_off(app)

    port = int(os.environ.get('PORT', 8888))
    bind_host = _resolve_bind_host()
    threads = _resolve_threads()
    _warn_if_multithreaded(threads)

    print("Starting Backlink Publisher WebUI (production/waitress)...")
    print(f"Open: http://{bind_host}:{port}  (threads={threads})")
    waitress.serve(app, host=bind_host, port=port, threads=threads)
