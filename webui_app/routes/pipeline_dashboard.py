"""/ce:pipeline — pipeline orchestrator dashboard.

Shows pipeline run history, circuit breaker status, recent pipeline
lifecycle events, and operator controls (trigger/pause/resume).

GET-only helpers — the global CSRF guard covers the POST endpoints.
POST endpoints write a pause sentinel file to the config dir, or
fire the pipeline-orchestrator as a non-blocking subprocess.

Plan 2026-06-11-001 Phase 2 + Phase 3 operator controls.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

from ..helpers._request_cache import _g_cache
from ..helpers.contexts import _render

bp = Blueprint("pipeline_dashboard", __name__)

_log = logging.getLogger(__name__)

# Pipeline event kinds we care about for the dashboard
_PIPELINE_KINDS = frozenset({
    "pipeline.started",
    "pipeline.stage_completed",
    "pipeline.completed",
    "pipeline.failed",
    "pipeline.skipped",
})

_CIRCUIT_KINDS = frozenset({
    "circuit.tripped",
    "circuit.half_open",
    "circuit.reset",
})


def _recent_pipeline_events(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch the most recent pipeline lifecycle events.

    Fail-open: returns empty list on any read error so the page never 500s.
    """
    try:
        from backlink_publisher.events import EventStore

        placeholders = ",".join("?" for _ in _PIPELINE_KINDS)
        rows = EventStore().query(
            "SELECT kind, payload_json, ts_utc, target_url, host "
            f"FROM events WHERE kind IN ({placeholders}) "
            "ORDER BY ts_utc DESC LIMIT ?",
            (*sorted(_PIPELINE_KINDS), limit),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            entry = {
                "kind": row["kind"],
                "ts_utc": row["ts_utc"],
                "target_url": row["target_url"],
                "host": row["host"],
                "payload": {},
            }
            raw = row["payload_json"]
            if raw:
                try:
                    entry["payload"] = json.loads(raw)
                except (ValueError, TypeError):
                    entry["payload"] = {"_parse_error": True}
            result.append(entry)
        return result
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.warning("pipeline_dashboard: recent events read failed: %s", exc)
        return []


def _recent_circuit_events(limit: int = 30) -> list[dict[str, Any]]:
    """Fetch the most recent circuit-breaker events for each platform.

    Fail-open: returns empty list on any read error.
    """
    try:
        from backlink_publisher.events import EventStore

        placeholders = ",".join("?" for _ in _CIRCUIT_KINDS)
        rows = EventStore().query(
            "SELECT kind, payload_json, ts_utc, target_url "
            f"FROM events WHERE kind IN ({placeholders}) "
            "ORDER BY ts_utc DESC LIMIT ?",
            (*sorted(_CIRCUIT_KINDS), limit),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            entry: dict[str, Any] = {
                "kind": row["kind"],
                "ts_utc": row["ts_utc"],
                "target_url": row["target_url"],
                "payload": {},
            }
            raw = row["payload_json"]
            if raw:
                try:
                    entry["payload"] = json.loads(raw)
                except (ValueError, TypeError):
                    entry["payload"] = {"_parse_error": True}
            result.append(entry)
        return result
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.warning("pipeline_dashboard: circuit events read failed: %s", exc)
        return []


def _pipeline_run_summary() -> dict[str, Any]:
    """Aggregate pipeline run counts: total, success, failed, skipped.

    Fail-open: returns empty dict on any read error.
    """
    try:
        from backlink_publisher.events import EventStore

        rows = EventStore().query(
            "SELECT kind, COUNT(*) as cnt "
            "FROM events WHERE kind IN (?, ?, ?, ?) "
            "GROUP BY kind",
            (
                "pipeline.completed",
                "pipeline.failed",
                "pipeline.skipped",
                "pipeline.started",
            ),
        )
        summary: dict[str, int] = {}
        for row in rows:
            summary[row["kind"]] = row["cnt"]
        return summary
    except Exception as exc:  # noqa: BLE001
        _log.warning("pipeline_dashboard: run summary failed: %s", exc)
        return {}


def _circuit_status_summary() -> list[dict[str, Any]]:
    """Current circuit-breaker status per platform.

    Reads the most recent circuit.* event per platform and reports the
    latest state.  Fail-open: returns empty list.
    """
    try:
        from backlink_publisher.events import EventStore

        # Get the latest circuit event per platform by grouping on
        # json_extract(payload, '$.platform')
        rows = EventStore().query(
            "SELECT e.kind, e.payload_json, e.ts_utc "
            "FROM events e "
            "WHERE e.kind IN (?, ?, ?) "
            "AND e.rowid IN ( "
            "  SELECT MIN(sub.rowid) FROM events sub "
            "  WHERE sub.kind IN (?, ?, ?) "
            "  GROUP BY json_extract(sub.payload_json, '$.platform') "
            "  ORDER BY sub.ts_utc DESC "
            ")",
            (
                "circuit.tripped",
                "circuit.half_open",
                "circuit.reset",
                "circuit.tripped",
                "circuit.half_open",
                "circuit.reset",
            ),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = {}
            raw = row["payload_json"]
            if raw:
                try:
                    payload = json.loads(raw)
                except (ValueError, TypeError):
                    pass
            result.append({
                "kind": row["kind"],
                "ts_utc": row["ts_utc"],
                "platform": payload.get("platform", "unknown"),
            })
        return result
    except Exception as exc:  # noqa: BLE001
        _log.warning("pipeline_dashboard: circuit summary failed: %s", exc)
        return []


def _stage_breakdown() -> list[dict[str, Any]]:
    """Count of pipeline.stage_completed per unique stage name.

    Shows which stages ran most/least.  Fail-open: empty list.
    """
    try:
        from backlink_publisher.events import EventStore

        rows = EventStore().query(
            "SELECT json_extract(payload_json, '$.stage') as stage, "
            "  COUNT(*) as cnt, "
            "  ROUND(AVG(json_extract(payload_json, '$.exit_code')), 1) as avg_exit "
            "FROM events WHERE kind = ? "
            "  AND json_extract(payload_json, '$.stage') IS NOT NULL "
            "GROUP BY stage ORDER BY cnt DESC",
            ("pipeline.stage_completed",),
        )
        return [
            {
                "stage": row["stage"],
                "count": row["cnt"],
                "avg_exit_code": row["avg_exit"],
            }
            for row in rows
        ]
    except Exception as exc:  # noqa: BLE001
        _log.warning("pipeline_dashboard: stage breakdown failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Operator controls
# ---------------------------------------------------------------------------

_PAUSE_SENTINEL_NAME = "pipeline-paused"


def _paused_sentinel_path() -> Path:
    """Path to the pause sentinel file in the config directory."""
    from backlink_publisher.config import _config_dir

    return _config_dir() / _PAUSE_SENTINEL_NAME


def _pipeline_paused() -> bool:
    """True when the pause sentinel file exists on disk."""
    return _paused_sentinel_path().exists()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/ce:pipeline", methods=["GET"])
def ce_pipeline():
    try:
        recent_events = _g_cache("pipeline_events", _recent_pipeline_events)
        circuit_events = _g_cache("circuit_events", _recent_circuit_events)
        run_summary = _g_cache("pipeline_run_summary", _pipeline_run_summary)
        circuit_status = _g_cache("circuit_status", _circuit_status_summary)
        stage_breakdown = _g_cache("pipeline_stage_breakdown", _stage_breakdown)

        return _render(
            "pipeline_dashboard.html",
            recent_events=recent_events,
            circuit_events=circuit_events,
            run_summary=run_summary,
            circuit_status=circuit_status,
            stage_breakdown=stage_breakdown,
            pipeline_paused=_pipeline_paused(),
            active_page="pipeline_dashboard",
        )
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.error("pipeline_dashboard: render failed: %s", exc)
        return "<!doctype html><html><body><h1>Pipeline Dashboard</h1><p>Temporarily unavailable.</p></body></html>", 200


# ── Operator actions ─────────────────────────────────────────────────────


@bp.route("/ce:pipeline/trigger", methods=["POST"])
def ce_pipeline_trigger():
    """Trigger a pipeline run as a non-blocking background subprocess.

    Fire-and-forget: returns immediately; the operator monitors progress
    via the events table on the dashboard.
    """
    try:
        from backlink_publisher.cli.pipeline_orchestrator import (
            REPO_DIR,
            VENV_PYTHON,
        )

        python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
        subprocess.Popen(
            [python, "-m", "backlink_publisher.cli.pipeline_orchestrator"],
            cwd=str(REPO_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"ok": True, "message": "Pipeline triggered."})
    except Exception as exc:
        _log.error("pipeline trigger failed: %s", exc)
        return jsonify({"ok": False, "message": str(exc)}), 500


@bp.route("/ce:pipeline/pause", methods=["POST"])
def ce_pipeline_pause():
    """Pause the pipeline by writing the pause sentinel file."""
    try:
        path = _paused_sentinel_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("paused")
        _log.info("pipeline paused (sentinel=%s)", path)
        return jsonify({"ok": True, "paused": True})
    except Exception as exc:
        _log.error("pipeline pause failed: %s", exc)
        return jsonify({"ok": False, "message": str(exc)}), 500


@bp.route("/ce:pipeline/resume", methods=["POST"])
def ce_pipeline_resume():
    """Resume the pipeline by removing the pause sentinel file."""
    try:
        path = _paused_sentinel_path()
        path.unlink(missing_ok=True)
        _log.info("pipeline resumed (sentinel removed)")
        return jsonify({"ok": True, "paused": False})
    except Exception as exc:
        _log.error("pipeline resume failed: %s", exc)
        return jsonify({"ok": False, "message": str(exc)}), 500
