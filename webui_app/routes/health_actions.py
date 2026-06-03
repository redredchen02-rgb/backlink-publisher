"""/ce:health maintenance actions (Plan 2026-06-03-004 Phase 2).

Three loopback-only POST endpoints let an operator act on a platform from the
health dashboard:

  U5  POST /ce:health/pause          {platform, paused?} → toggle pause flag
  U6  POST /ce:health/reverify       {platform}          → re-run setup verify
  U7  POST /ce:health/circuit-reset  {platform}          → reset tripped breaker

Perimeter: loopback-only (mirrors ``url_verify``), CSRF enforced app-level by
``_global_csrf_guard``. Every action validates the platform against the live
registry first — an unknown platform is a 400 with no side effect.

U6 runs ``verify_adapter_setup`` in **offline** mode (credential/config check),
not live: a synchronous web request must not block on a network probe, and the
sandbox blocks sockets. Live probing belongs to the pre-publish probe gate.

All handlers fail-soft: a store/breaker error returns ``{ok: False}`` with 200,
never a 500 — the dashboard stays usable.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from ..helpers.security import _LOOPBACK_HOSTS

bp = Blueprint("health_actions", __name__)

_log = logging.getLogger(__name__)


@bp.before_request
def _enforce_loopback():
    from flask import abort

    if request.remote_addr not in _LOOPBACK_HOSTS:
        abort(403)


def _config():
    from backlink_publisher.config import load_config

    return load_config()


def _known_platform(platform: str) -> bool:
    if not platform:
        return False
    try:
        from backlink_publisher.publishing.registry import registered_platforms

        return platform in registered_platforms()
    except Exception:  # noqa: BLE001 — unknown on any registry error
        return False


def _platform_arg() -> str:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("platform", "")).strip()


@bp.route("/ce:health/pause", methods=["POST"])
def pause_platform():
    platform = _platform_arg()
    if not _known_platform(platform):
        return jsonify({"ok": False, "platform": platform, "reason": "unknown_platform"}), 400

    payload = request.get_json(silent=True) or {}
    paused = bool(payload.get("paused", True))
    try:
        from backlink_publisher.health.persistence import locked_store

        new_state = locked_store.set_paused(platform, paused, _config())
    except Exception as exc:  # noqa: BLE001 — never 500
        _log.warning(f"health-actions: pause write failed for {platform}: {exc}")
        return jsonify({"ok": False, "platform": platform, "reason": "write_failed"}), 200
    return jsonify({"ok": True, "platform": platform, "paused": new_state})


@bp.route("/ce:health/reverify", methods=["POST"])
def reverify_platform():
    platform = _platform_arg()
    if not _known_platform(platform):
        return jsonify({"ok": False, "platform": platform, "reason": "unknown_platform"}), 400

    from backlink_publisher._util.errors import DependencyError
    from backlink_publisher.publishing.adapters import verify_adapter_setup

    try:
        verify_adapter_setup(platform, _config())  # offline mode
        return jsonify({"ok": True, "platform": platform, "ready": True, "reason": ""})
    except DependencyError as exc:
        return jsonify({"ok": True, "platform": platform, "ready": False, "reason": str(exc)})
    except Exception as exc:  # noqa: BLE001 — never 500
        _log.warning(f"health-actions: reverify failed for {platform}: {exc}")
        return jsonify({
            "ok": False, "platform": platform, "ready": False,
            "reason": type(exc).__name__,
        }), 200


@bp.route("/ce:health/circuit-reset", methods=["POST"])
def circuit_reset_platform():
    platform = _platform_arg()
    if not _known_platform(platform):
        return jsonify({"ok": False, "platform": platform, "reason": "unknown_platform"}), 400

    try:
        from backlink_publisher.publishing.reliability import circuit

        circuit.reset_circuit(platform, _config())
    except Exception as exc:  # noqa: BLE001 — never 500
        _log.warning(f"health-actions: circuit reset failed for {platform}: {exc}")
        return jsonify({"ok": False, "platform": platform, "reason": "reset_failed"}), 200
    return jsonify({"ok": True, "platform": platform})
