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
def health():
    """Liveness probe — no auth, no side effects (safe under loopback GET)."""
    return jsonify(
        {"status": "ok", "api_version": API_VERSION, "version": app_version()}
    )


# Attach resource modules' routes to ``bp``. Imported at the bottom so each
# module can ``from . import bp`` without a circular import (standard Flask
# blueprint-package idiom).
from . import app_config  # noqa: E402,F401  (Plan 2026-06-18-002 U2)
from . import pipeline  # noqa: E402,F401  (Plan 2026-06-18-002 U5)
from . import monitor  # noqa: E402,F401  (Plan 2026-06-18-002 U6)
from . import history  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
from . import drafts  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
from . import sites  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
from . import schedule  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
from . import campaigns  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
from . import profiles  # noqa: E402,F401  (Plan 2026-06-18-002 U7)
from . import settings_credentials  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings security core)
from . import channel_bind  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: general credential write)
from . import bind  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: stateful browser-bind flow)
from . import oauth  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: OAuth credential management)
from . import llm  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: LLM settings save)
from . import image_gen  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: image-gen diagnostics)
from . import medium_login  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: medium browser-login)
from . import global_settings  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: global keywords/schedule saves)
from . import channels  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: channel overview read)
from . import velog  # noqa: E402,F401  (Plan 2026-06-18-002 U7, Settings: velog status + login)

