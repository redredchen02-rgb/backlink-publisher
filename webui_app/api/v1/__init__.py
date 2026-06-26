"""``/api/v1`` — the versioned JSON API surface (Plan 2026-06-18-002 U1).

First unit of the WebUI front/back separation. This is a plain Flask blueprint
(NOT an APIFlask app swap — that base-class change reroutes 404s to JSON and
would ripple through the existing suite; deferred to a dedicated step with
full-suite verification). The OpenAPI 3.1 contract is generated from
``spec.py`` and gated in CI; errors use RFC 9457 problem+json (``errors.py``).

Call ``register_blueprint(bp)`` + ``register_api_error_handlers(app)`` from the
app factory. The CSRF guard (POST/PUT/PATCH/DELETE) stays the FIRST
before_request hook — registering this blueprint does not change guard ordering
(invariant: tests/test_webui_csrf_ordering.py).
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify

from .errors import (  # noqa: F401 - re-export for callers
    ApiProblem,
    from_pipe_result,
    problem_response,
    register_api_error_handlers,
)
from .spec import API_VERSION, app_version

API_V1_PREFIX = "/api/v1"

bp = Blueprint("api_v1", __name__, url_prefix=API_V1_PREFIX)


@bp.get("/health")
def health() -> Any:
    """Liveness probe — no auth, no side effects (safe under loopback GET)."""
    return jsonify(
        {"status": "ok", "api_version": API_VERSION, "version": app_version()}
    )


# Attach resource modules' routes to ``bp``. Imported at the bottom so each
# module can ``from . import bp`` without a circular import (standard Flask
# blueprint-package idiom).
from . import (
    app_config,  # noqa: E402,F401  (Plan 2026-06-18-002 U2)
    bind,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: stateful browser-bind flow)
    campaigns,  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
    channel_bind,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: general credential write)
    channels,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: channel overview read)
    drafts,  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
    global_settings,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: global keywords/schedule saves)
    history,  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
    image_gen,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: image-gen diagnostics)
    llm,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: LLM settings save)
    medium_login,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: medium browser-login)
    monitor,  # noqa: E402,F401  (Plan 2026-06-18-002 U6)
    oauth,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: OAuth credential management)
    pipeline,  # noqa: E402,F401  (Plan 2026-06-18-002 U5)
    profiles,  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
    schedule,  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
    settings_credentials,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings security core)
    sites,  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
    velog,  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: velog status + login)
)

