import json
import uuid
from datetime import datetime, timedelta, timezone

from apscheduler.executors.pool import ThreadPoolExecutor as APSThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from backlink_publisher._util.logger import plan_logger

from webui_store import batch_ops_store as _batch_ops_store
from webui_store import drafts_store as _drafts_store
from webui_store import history_store as _hist_store
from webui_store import queue_store as _queue_store
from webui_store import schedule_store as _sched_store

from .api.pipeline_api import PipelineAPI
from .services.keepalive_job import run_keepalive_for_site
from .helpers.cli_runner import strip_cli_diagnostic_banner
from .helpers.history import (
    _parse_publish_results,
    _push_history_per_row,
    _push_history_single_failure,
)


_RATE_LIMIT_RETRY_DELAY_S: int = 300

_scheduler = BackgroundScheduler(
    executors={'default': APSThreadPoolExecutor(max_workers=1)},
    job_defaults={'misfire_grace_time': 3600},
)

def _process_queue_job() -> None:
    """轮询队列中的 pending 任务并执行发布，支持 429 自动退避。"""
    tasks = _queue_store.load()
    now = datetime.now()
    
    # 查找任务：PENDING 且 不在退避时间内
    pending = [t for t in tasks if t.get('status') in ('pending', 'failed') 
               and (not t.get('next_retry_at') or datetime.fromisoformat(t['next_retry_at']) <= now)]
    
    if not pending:
        return

    task = pending[0]
    task_id = task['id']
    _queue_store.update_task(task_id, {'status': 'processing'})

    try:
        config = task['config']
        urls = task['urls']
        target_url = urls[0] if urls else ''
        
        seed = {
            'target_url': target_url,
            'platform': config.get('platform', 'medium'),
            'language': config.get('target_language', 'zh-CN'),
            'url_mode': config.get('url_mode', 'A'),
            'publish_mode': 'draft',
            'custom_title': config.get('custom_title', ''),
            'custom_tags': config.get('custom_tags', ''),
            'extra_urls': urls[1:] if urls else [],
        }
        
        result = PipelineAPI().publish_seed(json.dumps([seed]))
        if result.success:
            _queue_store.update_task(task_id, {
                'status': 'success',
                'completed_at': now.isoformat()
            })
        else:
            # publish failed — capture the typed error, detect 429 backoff.
            # The string check is kept (not error_class) so backoff fires even
            # when the rate-limit surfaces only in the message text.
            err = result.error or '发布失败'
            if "429" in err or "Too Many Requests" in err:
                retry_delay = _RATE_LIMIT_RETRY_DELAY_S
                next_retry = now + timedelta(seconds=retry_delay)
                _queue_store.update_task(task_id, {
                    'status': 'failed',
                    'error': f'频率限制 (429)，将在 {next_retry.strftime("%H:%M")} 重试',
                    'next_retry_at': next_retry.isoformat()
                })
            else:
                _queue_store.update_task(task_id, {
                    'status': 'failed',
                    'error': err
                })
    except Exception as exc:
        # Defensive: PipelineAPI returns a PipeResult rather than raising, so
        # this catches only seed-construction / store errors — still mark the
        # task failed rather than leaving it wedged in 'processing'.
        _queue_store.update_task(task_id, {
            'status': 'failed',
            'error': str(exc) or '发布失败'
        })


def _publish_draft_job(item_id: str) -> None:
    """APScheduler job: publish a draft item and update history."""
    item = _drafts_store.get_item(item_id)
    if not item or item.get('status') != 'scheduled':
        return

    platform = item.get('platform', 'medium')
    publish_mode = item.get('publish_mode', 'draft')
    plans_jsonl = item.get('plans_jsonl', '')

    try:
        result = PipelineAPI().publish(plans_jsonl, platform, publish_mode)
        if not result.success:
            raise RuntimeError(result.error or '发布失败')
        published = result.stdout

        if not published.strip():
            raise RuntimeError(result.error or '发布失败，无输出')

        publish_results = _parse_publish_results(published)
        article_urls = [
            u for r in publish_results
            for u in ((r.get('published_url'), r.get('draft_url')))
            if u
        ]

        # Reflect aggregate outcome on the draft row itself. If any row is
        # `*_unverified`, the draft is marked `published_unverified` so the
        # UI badge tells the truth even before recheck runs.
        draft_status = 'published'
        any_unverified = any(
            (r.get('status') or '').endswith('_unverified') for r in publish_results
        )
        if any_unverified:
            draft_status = 'published_unverified'
        _drafts_store.update_item(
            item_id, status=draft_status,
            article_urls=article_urls,
            published_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
        )

        # Plan 2026-05-19-006 Unit 1: per-row truth-propagation. The old
        # implementation hard-wrote `'drafted'` / `'published'` regardless
        # of per-row `status`, hiding `*_unverified` rows as solid ✓.
        _push_history_per_row(
            publish_results,
            target_url_fallback=item.get('target_url', 'unknown'),
            platform_fallback=platform,
            language_fallback=item.get('language', 'zh-CN'),
        )
    except Exception as exc:
        msg = strip_cli_diagnostic_banner(str(exc)) or str(exc)
        _drafts_store.update_item(item_id, status='failed', error=msg)
        _push_history_single_failure(
            target_url=item.get('target_url', 'unknown'),
            platform=platform,
            language=item.get('language', 'zh-CN'),
            error=msg,
        )


def _schedule_draft_job(item_id: str, run_date: datetime) -> None:
    _scheduler.add_job(
        _publish_draft_job, trigger='date', run_date=run_date,
        id=item_id, args=[item_id], replace_existing=True,
    )


def _restore_processing_tasks() -> None:
    """Reset queue tasks left in 'processing' back to 'pending'.

    If the WebUI was killed (SIGKILL / power loss / OOM) while a queue
    processor was mid-flight, the task sits permanently in 'processing'
    and never gets picked up again because the queue processor only reads
    'pending' and 'failed' statuses.  Resetting them on every startup is
    the simplest recovery — the next interval tick re-processes the task.

    This call is idempotent: no 'processing' tasks at startup = no-op.
    """
    _queue_store.update(lambda tasks: [
        {**t, 'status': 'pending'} if t.get('status') == 'processing' else t
        for t in tasks
    ])


def _drain_batch_ops() -> None:
    """Process one pending batch_ops row per tick (60s interval).

    Dispatches to the appropriate service based on ``operation``.
    Single-row-per-tick ensures throttle settings are respected and
    a slow site cannot starve subsequent items indefinitely.
    """
    row = _batch_ops_store.get_pending_one()
    if row is None:
        return

    row_id = row["id"]
    site_url = row["site_url"]
    operation = row["operation"]
    _batch_ops_store.update_row(row_id, "processing")

    try:
        if operation == "keep_alive":
            # run_keepalive_for_site extracted in U7; raise ImportError until then
            from .services.keepalive_job import run_keepalive_for_site  # type: ignore[attr-defined]
            run_keepalive_for_site(site_url)
        elif operation == "recheck":
            from .services.recheck import recheck_many
            recheck_many([{"target_url": site_url, "platform": ""}], verify_fn=None)
        elif operation == "channel_health":
            from .services.credential_service import probe_channel_liveness
            probe_channel_liveness(site_url)
        else:
            raise ValueError(f"unknown operation: {operation}")
        _batch_ops_store.update_row(row_id, "done")
    except Exception as exc:
        _batch_ops_store.update_row(row_id, "failed", error=str(exc))
        plan_logger.warn("batch_ops_drain_failed", row_id=row_id, operation=operation, error=str(exc))


def _restore_scheduled_jobs() -> None:
    """On startup, re-register any 'scheduled' draft items into APScheduler."""
    _restore_processing_tasks()

    _scheduler.add_job(
        _process_queue_job,
        trigger='interval',
        minutes=1,
        id='queue_processor',
        replace_existing=True,
    )

    _scheduler.add_job(
        _drain_batch_ops,
        trigger='interval',
        seconds=60,
        id='batch_ops_drain',
        replace_existing=True,
    )
    
    now = datetime.now()
    for item in _drafts_store.load():
        if item.get('status') != 'scheduled':
            continue
        item_id = item.get('id')
        ts = item.get('scheduled_at')
        if not item_id or not ts:
            continue
        try:
            run_date = datetime.fromisoformat(ts)
            if run_date < now:
                run_date = now + timedelta(seconds=5)
            _schedule_draft_job(item_id, run_date)
        except Exception as e:
            plan_logger.warn("restore_scheduled_job_failed", item_id=item_id, ts=ts, error=str(e))

    # Autopilot: register one interval job per enabled site (skip under maintenance).
    sched_settings = _sched_store.load()
    maintenance = sched_settings.get("maintenance_mode", False)
    if not maintenance:
        for site_url, cfg in sched_settings.get("autopilot_targets", {}).items():
            if cfg.get("enabled"):
                interval_s = int(cfg.get("interval_seconds", 86400))
                _register_autopilot_job(site_url, interval_s)


def _autopilot_job_id(site_url: str) -> str:
    """Deterministic, scheduler-safe job ID for a given site URL."""
    return "autopilot_" + site_url.replace("://", "_").replace("/", "_").rstrip("_")


def _register_autopilot_job(site_url: str, interval_seconds: int) -> None:
    """Add or replace an autopilot interval job for ``site_url``."""
    _scheduler.add_job(
        _keepalive_cycle_job,
        trigger='interval',
        seconds=interval_seconds,
        id=_autopilot_job_id(site_url),
        replace_existing=True,
        args=[site_url],
    )


def _keepalive_cycle_job(site_url: str) -> None:
    """APScheduler job: run a keep-alive cycle for one site.

    Writes a history entry with ``extra_json={"source": "autopilot"}``.
    On failure, sets ``alert_pending: true`` in ``autopilot_targets``.
    Never raises — protects the APScheduler thread.
    """
    import uuid as _uuid

    try:
        result = run_keepalive_for_site(site_url)
    except Exception as exc:  # noqa: BLE001
        result_success = False
        result_error = str(exc)
        result_checked = 0
    else:
        result_success = result.success
        result_error = result.error
        result_checked = result.checked

    now_iso = datetime.now(timezone.utc).isoformat()

    # Persist history entry with source badge
    entry = {
        "id": _uuid.uuid4().hex,
        "status": "autopilot_ok" if result_success else "autopilot_fail",
        "platform": "autopilot",
        "target_url": site_url,
        "article_urls": [],
        "verified_at": now_iso,
        "extra_json": {"source": "autopilot", "checked": result_checked, "error": result_error},
    }
    try:
        _hist_store.update(lambda hist: [entry, *hist][:200])
    except Exception:  # noqa: BLE001
        plan_logger.debug("history_update_failed", site_url=site_url, exc_info=True)

    # Update autopilot_targets: last_run + alert_pending
    alert = not result_success
    def _update_autopilot(settings: dict) -> dict:
        targets = dict(settings.get("autopilot_targets", {}))
        site_cfg = dict(targets.get(site_url, {}))
        site_cfg["last_run"] = now_iso
        site_cfg["alert_pending"] = alert
        targets[site_url] = site_cfg
        return {**settings, "autopilot_targets": targets}

    try:
        _sched_store.update(_update_autopilot)
    except Exception:  # noqa: BLE001
        plan_logger.debug("autopilot_state_update_failed", site_url=site_url, exc_info=True)

    plan_logger.info(
        "autopilot_cycle_done",
        site_url=site_url, success=result_success, checked=result_checked,
    )
