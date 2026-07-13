"""OperationWorker — background executor for async WebUI pipeline operations.

Runs ``plan`` / ``validate`` / ``publish`` / ``publish_chain`` jobs off the
request thread so the HTTP call returns an ``op_id`` immediately and the SPA
can poll ``GET /api/v1/operations/<id>`` for stage + progress.

Mirrors ``campaign_worker.py``: an in-process ``ThreadPoolExecutor`` plus a
single-flight guard. ``publish`` / ``publish_chain`` are single-flight (one at
a time) to avoid racing the ``dedup.db`` single-flight and spawning two Chrome
subprocesses at once; ``plan`` / ``validate`` are fast in-process and may run
concurrently.

Plan: docs/plans/2026-07-09-webui-operation-progress-plan.md (U2).
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import logging
from typing import Any

_log = logging.getLogger(__name__)

# Kinds that must not overlap (one running instance at a time).
_SINGLE_FLIGHT_KINDS = frozenset({"publish", "publish_chain"})


class OperationWorker:
    """In-process operation executor.

    Accepts one single-flight op (publish/chain) at a time; concurrent
    submissions of those kinds are rejected with ``AlreadyRunningError``.
    Other kinds (plan/validate) run concurrently.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running: dict[str, Future] = {}

    # ── Public API ─────────────────────────────────────────────────────────

    def start(self, op_id: str, kind: str, cfg: dict[str, Any]) -> None:
        """Submit an operation for background execution.

        Raises:
            AlreadyRunningError: if a single-flight kind (publish/chain) is
                already running.
        """
        if kind in _SINGLE_FLIGHT_KINDS and self._any_single_flight_running():
            running_id = next(
                (oid for oid, f in self._running.items()
                 if not f.done() and self._kind_of(oid) in _SINGLE_FLIGHT_KINDS),
                "unknown",
            )
            raise AlreadyRunningError(
                f"A {kind} operation is already in progress (op_id={running_id}). "
                f"Wait for it to finish before starting another."
            )
        future = self._executor.submit(_execute_operation, op_id, kind, cfg)
        self._running[op_id] = future

    def get_status(self, op_id: str) -> dict[str, Any] | None:
        """Return the op's current state from ``operation_store`` (+ running/done).

        Returns ``None`` if the op id is unknown.
        """
        from webui_store import operation_store

        op = operation_store.get(op_id)
        if op is None:
            return None
        result = dict(op)
        future = self._running.get(op_id)
        if future is not None:
            result["_running"] = future.running()
            result["_done"] = future.done()
        else:
            result["_running"] = False
            result["_done"] = True
        return result

    def cancel(self, op_id: str) -> bool:
        """Attempt to cancel a running op.

        Returns ``True`` if the op was (or could be) canceled; the store is
        marked ``canceled``. In-flight engine work may not stop immediately
        (e.g. a browser subprocess), but no further stage transitions occur.

        Also handles an orphaned ``pending``/``running`` op with no live future
        (e.g. a worker restart between submit and pick-up) so the operator can
        always recover a stuck task.
        """
        future = self._running.get(op_id)
        if future is not None and not future.done():
            cancelled = future.cancel()
            from webui_store import operation_store

            operation_store.update_fields(
                op_id, status="canceled", stage="", detail="操作已取消"
            )
            return cancelled
        # No live future: recover an orphaned in-flight op record.
        from webui_store import operation_store

        op = operation_store.get(op_id)
        if op is not None and op.get("status") in ("pending", "running"):
            operation_store.update_fields(
                op_id, status="canceled", stage="", detail="操作已取消"
            )
            return True
        return False

    def is_running(self) -> bool:
        """Return ``True`` if any operation is currently executing."""
        done_ids = [cid for cid, f in self._running.items() if f.done()]
        for cid in done_ids:
            self._running.pop(cid, None)
        return bool(self._running)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the worker pool."""
        self._executor.shutdown(wait=wait)

    # ── Internals ──────────────────────────────────────────────────────────

    def _any_single_flight_running(self) -> bool:
        return any(
            not f.done() and self._kind_of(oid) in _SINGLE_FLIGHT_KINDS
            for oid, f in self._running.items()
        )

    def _kind_of(self, op_id: str) -> str | None:
        from webui_store import operation_store

        op = operation_store.get(op_id)
        return op.get("kind") if op else None


class AlreadyRunningError(RuntimeError):
    """Raised when a single-flight operation is requested while one runs."""


# ── Internal execution ───────────────────────────────────────────────────


def _execute_operation(op_id: str, kind: str, cfg: dict[str, Any]) -> None:
    """Run one operation entirely inside a worker thread, updating the store."""
    from webui_store import operation_store

    try:
        operation_store.update_fields(op_id, status="running")
        if kind == "publish":
            _run_publish(op_id, cfg)
        elif kind == "publish_chain":
            _run_publish_chain(op_id, cfg)
        else:
            # plan / validate are handled synchronously by the route today;
            # the worker path exists for uniformity and future async use.
            operation_store.update_fields(
                op_id, status="failed", error=f"unsupported op kind: {kind}"
            )
    except Exception as exc:  # noqa: BLE001 — surface any failure to the store
        _log.exception("operation %s (%s) crashed", op_id, kind)
        try:
            operation_store.update_fields(
                op_id, status="failed", error=f"{type(exc).__name__}: {exc}"
            )
        except Exception:
            _log.exception("failed to mark operation %s as failed", op_id)


def _plans_to_jsonl(plans: Any) -> str:
    if isinstance(plans, str):
        return plans
    rows = plans if isinstance(plans, list) else []
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows if isinstance(r, dict))


def _run_publish(op_id: str, cfg: dict[str, Any]) -> None:
    from backlink_publisher.sdk.api import PipelineAPI, publish_state_summary
    from webui_store import operation_store

    from ..helpers.history import _push_history_per_row, _push_history_single_failure

    platform = cfg.get("platform", "")
    publish_mode = cfg.get("publish_mode", "publish")
    tier_1 = bool(cfg.get("tier_1", False))
    target_url = cfg.get("target_url") or "unknown"
    language = cfg.get("target_language", "zh-CN")
    plans_jsonl = _plans_to_jsonl(cfg.get("plans"))

    try:
        operation_store.update_fields(op_id, stage="发布", progress_pct=50, detail="正在发布…")
        api = PipelineAPI()
        result = api.publish(plans_jsonl, platform, publish_mode, tier_1=tier_1)
    except Exception as exc:  # noqa: BLE001
        _log.warning("publish op %s raised: %s", op_id, exc)
        operation_store.update_fields(
            op_id, status="failed", progress_pct=50,
            error=f"{type(exc).__name__}: {exc}",
        )
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    if not result.success:
        display = _format_error(result.error, result.error_class)
        operation_store.update_fields(
            op_id, status="failed", progress_pct=50, error=display
        )
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language, error=display
        )
        return

    publish_results = result.rows
    if not publish_results:
        diagnostic = "publish-backlinks returned no parseable rows"
        operation_store.update_fields(
            op_id, status="failed", progress_pct=50, error=diagnostic
        )
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language, error=diagnostic
        )
        return

    _push_history_per_row(
        publish_results,
        target_url_fallback=target_url,
        platform_fallback=platform,
        language_fallback=language,
    )
    summary = publish_state_summary(publish_results)
    operation_store.update_fields(
        op_id,
        status="success",
        stage="发布",
        progress_pct=100,
        detail="发布完成",
        result={
            "state": summary["state"],
            "n_ok": summary["n_ok"],
            "n_failed": summary["n_failed"],
            "failure_detail": summary.get("failure_detail"),
            "results": publish_results,
        },
    )


def _run_publish_chain(op_id: str, cfg: dict[str, Any]) -> None:
    from backlink_publisher.sdk.api import PipelineAPI, publish_state_summary
    from webui_store import operation_store

    from ..helpers.history import _push_history_per_row, _push_history_single_failure
    from ..services.pipeline_service import build_generate_seed

    urls = cfg.get("urls") or []
    platform = cfg.get("platform", "medium")
    url_mode = cfg.get("url_mode", "C")
    publish_mode = cfg.get("publish_mode", "publish")
    target_language = cfg.get("target_language", "zh-CN")
    custom_title = (cfg.get("custom_title") or "").strip()
    custom_tags = (cfg.get("custom_tags") or "").strip()
    fetch_tdk = cfg.get("fetch_tdk", "no")
    tier_1 = bool(cfg.get("tier_1", False))
    main_url = urls[0] if urls else "unknown"

    tdk_data: dict[str, Any] = {}
    if fetch_tdk == "yes":
        try:
            from ..helpers.url_meta import fetch_full_tdk

            tdk_data = fetch_full_tdk(main_url)
        except Exception as exc:  # noqa: BLE001
            _log.warning("chain op %s tdk fetch failed: %s", op_id, exc)

    try:
        seed = build_generate_seed(
            urls=urls,
            platform=platform,
            url_mode=url_mode,
            publish_mode=publish_mode,
            target_language=target_language,
            custom_title=custom_title,
            custom_tags=custom_tags,
            tdk_data=tdk_data,
        )
        seed_json = json.dumps(seed, ensure_ascii=False)

        operation_store.update_fields(op_id, stage="生成", progress_pct=10, detail="正在生成…")
        api = PipelineAPI()
        plan_res = api.plan(seed_json)
        if not plan_res.success:
            _fail_chain(op_id, main_url, platform, target_language,
                        plan_res.error or "生成失败")
            return

        operation_store.update_fields(op_id, stage="验证", progress_pct=45, detail="正在验证…")
        val_res = api.validate(plan_res.stdout, no_check_urls=True)
        if not val_res.success:
            _fail_chain(op_id, main_url, platform, target_language,
                        val_res.error or "验证失败")
            return

        operation_store.update_fields(op_id, stage="发布", progress_pct=75, detail="正在发布…")
        pub_res = api.publish(val_res.stdout, platform, publish_mode, tier_1=tier_1)
        if not pub_res.success:
            display = _format_error(pub_res.error, pub_res.error_class)
            operation_store.update_fields(op_id, status="failed", progress_pct=75, error=display)
            _push_history_single_failure(
                target_url=main_url, platform=platform, language=target_language,
                error=display,
            )
            return

        publish_results = pub_res.rows
        if not publish_results:
            diagnostic = "publish-backlinks returned no parseable rows"
            operation_store.update_fields(op_id, status="failed", progress_pct=75, error=diagnostic)
            _push_history_single_failure(
                target_url=main_url, platform=platform, language=target_language,
                error=diagnostic,
            )
            return

        _push_history_per_row(
            publish_results,
            target_url_fallback=main_url,
            platform_fallback=platform,
            language_fallback=target_language,
        )
        summary = publish_state_summary(publish_results)
        operation_store.update_fields(
            op_id,
            status="success",
            stage="发布",
            progress_pct=100,
            detail="发布完成",
            result={
                "state": summary["state"],
                "n_ok": summary["n_ok"],
                "n_failed": summary["n_failed"],
                "failure_detail": summary.get("failure_detail"),
                "results": publish_results,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("chain op %s raised: %s", op_id, exc)
        operation_store.update_fields(
            op_id, status="failed", progress_pct=75,
            error=f"{type(exc).__name__}: {exc}",
        )
        _push_history_single_failure(
            target_url=main_url, platform=platform, language=target_language,
            error=f"{type(exc).__name__}: {exc}",
        )


def _fail_chain(
    op_id: str, target_url: str, platform: str, language: str, error: str
) -> None:
    from webui_store import operation_store

    from ..helpers.history import _push_history_single_failure

    operation_store.update_fields(op_id, status="failed", error=error)
    _push_history_single_failure(
        target_url=target_url, platform=platform, language=language, error=error
    )


def _format_error(error: str | None, error_class: str | None) -> str:
    msg = error or "发布失败"
    if error_class and error_class != "unrecognized":
        return f"[{error_class}] {msg}"
    return msg
